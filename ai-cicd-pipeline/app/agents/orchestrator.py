import asyncio
import json
import uuid
from typing import Any

import redis
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.approval_agent import ApprovalAgent
from app.agents.deployment_agent import DeploymentAgent
from app.agents.full_scan_orchestrator import FullScanOrchestrator
from app.agents.monitoring_agent import MonitoringAgent
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.auto_pr_service import AutoPRService
from app.services.git_service import GitService
from app.services.github_service import GitHubService
from app.services.slack_service import SlackService
from app.utils.logger import pipeline_logger


def _emit_ws(pipeline_run_id: uuid.UUID, message: dict[str, Any]) -> None:
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.publish(f"pipeline:{pipeline_run_id}", json.dumps(message))
        r.close()
    except Exception as exc:
        pipeline_logger.debug("redis publish failed: %s", exc)


class PipelineOrchestrator:
    def __init__(self) -> None:
        self.anthropic: AsyncAnthropic | None = None
        self.git_service = GitService()
        self.slack = SlackService()
        self._github_token: str | None = None

    def _client(self) -> AsyncAnthropic:
        if self.anthropic is None:
            self.anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self.anthropic

    async def _handle_block(
        self,
        status: str,
        result: dict[str, Any],
        run: PipelineRun,
        gh: GitHubService,
    ) -> None:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(PipelineRun).where(PipelineRun.id == run.id))
            row = r.scalar_one_or_none()
            if row:
                row.status = status
                row.error_message = json.dumps(result)[:8000]
                await db.commit()
        try:
            await gh.set_commit_status(
                run.repo_full_name,
                run.commit_id,
                "failure",
                "ORION blocked pipeline",
            )
        except Exception as exc:
            pipeline_logger.warning("github status failure: %s", exc)
        await self.slack.send_pipeline_blocked(
            run.id,
            reason=status,
            agent="orchestrator",
            details=json.dumps(result)[:3000],
        )

    def _combined_requires_block(self, combined: dict[str, Any]) -> bool:
        code = combined.get("code_issues") or {}
        if isinstance(code, dict) and not code.get("skipped"):
            sev = str(code.get("severity", "")).lower()
            if sev == "fail":
                return True
            if int(code.get("critical_issues_count", 0) or 0) > 0:
                return True

        sec = combined.get("security_issues") or {}
        if isinstance(sec, dict) and not sec.get("skipped"):
            hs = str(sec.get("highest_severity", "")).lower()
            order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            max_allowed = str(settings.max_security_severity).lower()
            if order.get(hs, 0) > order.get(max_allowed, 1):
                return True

        qa = combined.get("qa_issues") or {}
        if isinstance(qa, dict) and not qa.get("skipped"):
            if str(qa.get("verdict", "")).lower() == "fail":
                return True

        return False

    async def execute_pipeline(
        self, pipeline_run_id: str, github_token: str | None = None
    ) -> None:
        self._github_token = github_token
        run_uuid = uuid.UUID(pipeline_run_id)
        gh = GitHubService(token=self._github_token)

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(PipelineRun).where(PipelineRun.id == run_uuid))
            run = r.scalar_one_or_none()
            if not run:
                pipeline_logger.error("Pipeline run not found: %s", pipeline_run_id)
                await gh.close()
                return

            client = self._client()
            _emit_ws(run_uuid, {"kind": "stage-update", "stage": "ingesting", "status": "running"})

            try:
                run.status = "ingesting"
                await db.commit()

                await self.slack.send_pipeline_start(
                    run.id, run.commit_id, run.branch, run.pusher
                )

                repo_path = await self.git_service.clone_repo(run.clone_url, run.id)
                diff_text = await self.git_service.get_diff(repo_path)
                meta = {
                    "branch": run.branch,
                    "commit": run.commit_id,
                    "pusher": run.pusher,
                    "repo": run.repo_full_name,
                }
                db.add(
                    PipelineArtifact(
                        pipeline_run_id=run.id,
                        artifact_type="diff",
                        content={"diff": diff_text[:200000]},
                        raw_output=diff_text[:50000],
                    )
                )
                db.add(
                    PipelineArtifact(
                        pipeline_run_id=run.id,
                        artifact_type="metadata",
                        content=meta,
                    )
                )
                await db.commit()

                run.status = "analyzing_code"
                await db.commit()
                _emit_ws(
                    run_uuid,
                    {"kind": "stage-update", "stage": "analyzing_code", "status": "running"},
                )

                full = FullScanOrchestrator(
                    run.id, db, client, repo_path, diff_text
                )
                combined = await full.execute()

                if self._combined_requires_block(combined):
                    run.status = "analyzing_code"
                    await db.commit()
                    try:
                        pr_service = AutoPRService(
                            self._github_token,
                            run.repo_full_name,
                            run.clone_url,
                        )
                        bundles = await pr_service.open_all_prs(
                            combined, repo_path, run.id, client
                        )
                        await pr_service.save_pr_registry(db, run.id, bundles)
                        await pr_service.close()
                    except Exception as exc:
                        pipeline_logger.warning("AutoPR failed: %s", exc)

                    await self._handle_block(
                        "blocked_with_prs_sent",
                        {"combined": combined},
                        run,
                        gh,
                    )
                    _emit_ws(
                        run_uuid,
                        {
                            "kind": "stage-update",
                            "stage": "blocked",
                            "status": "blocked_with_prs_sent",
                        },
                    )
                    return

                run.status = "awaiting_approval"
                await db.commit()
                _emit_ws(
                    run_uuid,
                    {
                        "kind": "stage-update",
                        "stage": "awaiting_approval",
                        "status": "running",
                    },
                )

                approval = ApprovalAgent(run.id, db, client)
                decision = await approval.execute()
                if str(decision.get("decision", "")).lower() == "rejected":
                    run.status = "rejected"
                    await db.commit()
                    await gh.set_commit_status(
                        run.repo_full_name,
                        run.commit_id,
                        "failure",
                        "ORION approval rejected",
                    )
                    return

                run.status = "deploying"
                await db.commit()
                _emit_ws(
                    run_uuid,
                    {"kind": "stage-update", "stage": "deploying", "status": "running"},
                )

                deploy = DeploymentAgent(
                    run.id, db, client, repo_path, run.commit_id
                )
                dep_res = await deploy.execute()
                if not dep_res.get("success"):
                    run.status = "failed"
                    await db.commit()
                    await gh.set_commit_status(
                        run.repo_full_name,
                        run.commit_id,
                        "failure",
                        "ORION deployment failed",
                    )
                    return

                asyncio.create_task(self._run_monitoring(run.id))

                run.status = "deployed"
                await db.commit()
                _emit_ws(
                    run_uuid,
                    {"kind": "stage-update", "stage": "deployed", "status": "completed"},
                )

                await gh.set_commit_status(
                    run.repo_full_name,
                    run.commit_id,
                    "success",
                    "ORION deployed successfully",
                )
                await self.slack.send_pipeline_deployed(
                    run.id,
                    run.commit_id,
                    settings.deploy_environment,
                )
            finally:
                self.git_service.cleanup_repo(run.id)
                await gh.close()

    async def _run_monitoring(self, run_id: uuid.UUID) -> None:
        async with AsyncSessionLocal() as db:
            client = self._client()
            mon = MonitoringAgent(run_id, db, client)
            await mon.execute()


orchestrator = PipelineOrchestrator()

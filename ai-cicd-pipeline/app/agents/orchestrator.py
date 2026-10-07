import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.approval_agent import ApprovalAgent
from app.agents.deployment_agent import DeploymentAgent, resolved_deploy_mode
from app.agents.full_scan_orchestrator import FullScanOrchestrator
from app.agents.monitoring_agent import MonitoringAgent
from app.agents.software_engineer_agent import SoftwareEngineerAgent
from app.agents.stress_test_agent import StressTestAgent
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import TERMINAL_STATUSES, PipelineRun
from app.services.approval_enrichment import (
    enterprise_approval_ready,
    init_enterprise_approval,
)
from app.services.auto_pr_service import AutoPRService, IssueBundle
from app.services.events import publish_event
from app.services.git_service import GitService
from app.services.github_service import GitHubService
from app.services.phase1_enrichment import persist_release_passport, run_phase1_enrichment
from app.services.developer_ux_enrichment import persist_developer_ux_intelligence
from app.services.iam_enrichment import persist_iam_intelligence
from app.services.dr_enrichment import persist_dr_intelligence
from app.services.autopilot_enrichment import persist_autopilot_intelligence
from app.services.unified_risk_enrichment import persist_unified_risk_intelligence
from app.services.knowledge_graph_enrichment import persist_knowledge_graph_intelligence
from app.services.reliability_enrichment import persist_reliability_intelligence
from app.services.release_enrichment import persist_release_intelligence
from app.services.catalog_enrichment import persist_service_catalog_intelligence
from app.services.cloud_enrichment import persist_cloud_intelligence
from app.services.deployment_enrichment import persist_deployment_intelligence
from app.services.observability_enrichment import persist_observability_intelligence
from app.services.remediation_enrichment import persist_remediation_intelligence
from app.services.multimodal_enrichment import persist_multimodal_intelligence
from app.services.code_review_enrichment import persist_code_review_intelligence
from app.services.dast_enrichment import persist_dast_report
from app.services.performance_enrichment import persist_performance_intelligence
from app.services.phase2_enrichment import run_phase2_enrichment
from app.services.phase3_enrichment import run_phase3_observability
from app.services.phase4_enrichment import run_phase4_enrichment, run_phase4_policy_gate
from app.services.hybrid_retriever import build_retriever, index_repository
from app.services.memory_store import build_memory_store
from app.services.phase5_enrichment import run_phase5_enrichment
from app.services.pr_intelligence import post_pr_intelligence
from app.services.slack_service import SlackService
from app.utils.logger import get_logger
from app.utils.change_risk import compute_change_risk
from app.utils.gate_fusion import fuse_stage_results
from app.utils.multimodal_intelligence import collect_multimodal_artifacts
from app.utils.prompt_injection_firewall import scan_repository_submission
from app.utils.enterprise_approval import evaluate_enterprise_approval
from app.utils.severity import exceeds_threshold, severity_rank

AGENT_STAGE = {"code_issues": "analyzing_code", "security_issues": "analyzing_security", "qa_issues": "running_qa"}


async def _load_artifact_map(db: AsyncSession, run_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    rows = (
        await db.execute(
            select(PipelineArtifact)
            .where(PipelineArtifact.pipeline_run_id == run_id)
            .order_by(PipelineArtifact.created_at.asc())
        )
    ).scalars().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[row.artifact_type] = row.content or {}
    return latest


async def _load_artifacts_for_runs(
    db: AsyncSession, run_ids: list[uuid.UUID]
) -> dict[str, dict[str, dict[str, Any]]]:
    if not run_ids:
        return {}
    rows = (
        await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id.in_(run_ids)))
    ).scalars().all()
    by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        rid = str(row.pipeline_run_id)
        by_run.setdefault(rid, {})[row.artifact_type] = row.content or {}
    return by_run


def _has_full_scan(artifacts: dict[str, dict[str, Any]]) -> bool:
    if "full_scan_combined" in artifacts:
        return True
    return all(key in artifacts for key in ("code_analysis", "security_scan", "qa_report"))


def _combined_from_artifacts(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if "full_scan_combined" in artifacts:
        return artifacts["full_scan_combined"]
    return {
        "code_issues": artifacts.get("code_analysis", {}),
        "security_issues": artifacts.get("security_scan", {}),
        "qa_issues": artifacts.get("qa_report", {}),
    }


def emit_ws(pipeline_run_id: uuid.UUID | str, message: dict[str, Any]) -> None:
    publish_event(pipeline_run_id, message)


def block_status_for(combined: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Decide whether the full scan blocks the pipeline. Returns (status, reasons)."""
    reasons: list[str] = []
    status: str | None = None

    code = combined.get("code_issues") or {}
    if isinstance(code, dict) and not code.get("skipped") and str(code.get("severity", "")).lower() == "fail":
        status = status or "blocked_code"
        reasons.append(f"code analysis failed ({code.get('critical_issues_count', 0)} critical issues)")

    sec = combined.get("security_issues") or {}
    if isinstance(sec, dict) and not sec.get("skipped"):
        if exceeds_threshold(sec.get("highest_severity"), settings.max_security_severity):
            status = status or "blocked_security"
            reasons.append(f"security severity {sec.get('highest_severity')} exceeds {settings.max_security_severity}")

    qa = combined.get("qa_issues") or {}
    if isinstance(qa, dict) and not qa.get("skipped") and str(qa.get("verdict", "")).lower() == "fail":
        status = status or "blocked_tests"
        reasons.append("tests failed")

    return status, reasons


def has_warnings(combined: dict[str, Any]) -> bool:
    code = combined.get("code_issues") or {}
    sec = combined.get("security_issues") or {}
    return (
        str(code.get("severity", "")).lower() == "warn"
        or severity_rank(sec.get("highest_severity")) >= 0
        or any(isinstance(v, dict) and v.get("skipped") for v in combined.values())
    )


async def _persist_change_risk_report(
    db: AsyncSession,
    run: PipelineRun,
    *,
    diff_text: str,
    changed_files: list[str] | None,
    combined: dict[str, Any],
    stress: dict[str, Any],
    skip_if_present: bool,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("change_risk_report"):
        return artifacts["change_risk_report"]

    code = artifacts.get("code_analysis") or combined.get("code_issues") or {}
    security = artifacts.get("security_scan") or combined.get("security_issues") or {}
    qa = artifacts.get("qa_report") or combined.get("qa_issues") or {}
    stress_art = stress or artifacts.get("stress_report") or {}
    fused = fuse_stage_results(code=code, security=security, qa=qa, stress=stress_art)
    analysis_mode = "heuristic"
    for component in (code, security, qa):
        if isinstance(component, dict) and str(component.get("analysis_mode", "")).lower() == "llm":
            analysis_mode = "llm"
            break

    report = compute_change_risk(
        diff_text=diff_text,
        changed_files=changed_files,
        code=code,
        security=security,
        qa=qa,
        stress=stress_art,
        gate_fusion=fused,
        analysis_mode=analysis_mode,
    )
    graph = artifacts.get("service_graph") or {}
    if graph.get("downstream_hint"):
        report.setdefault("blast_radius_analysis", {})["downstream_services"] = graph.get("downstream_hint")
        report.setdefault("recommendations", [])
        if graph.get("changed_services"):
            report["recommendations"].append(
                f"affected services: {', '.join(graph['changed_services'][:5])}"
            )
    db.add(
        PipelineArtifact(
            pipeline_run_id=run.id,
            artifact_type="change_risk_report",
            content=report,
        )
    )
    await db.commit()
    emit_ws(
        run.id,
        {
            "kind": "artifact",
            "artifact_type": "change_risk_report",
            "agent": "change_risk",
            "summary": f"Change risk {report['final_risk']}/100 ({report['risk_level']})",
        },
    )
    return report


class PipelineCancelled(Exception):
    """Raised at a stage boundary when an operator cancelled the run."""


class PipelineOrchestrator:
    def __init__(self) -> None:
        self._anthropic: AsyncAnthropic | None = None
        self.git_service = GitService()
        self.slack_service = SlackService()
        self.logger = get_logger("orchestrator")

    @property
    def anthropic_client(self) -> AsyncAnthropic:
        if self._anthropic is None:
            self._anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._anthropic

    async def _set_status(
        self, db: AsyncSession, run: PipelineRun, status: str, error_message: str | None = None
    ) -> None:
        await db.refresh(run, ["status"])
        if run.status == "cancelled":
            raise PipelineCancelled()
        run.status = status
        if error_message is not None:
            run.error_message = error_message[:8000]
        elif status in ("deployed", "approved", "monitoring", "completed"):
            run.error_message = None
        if status in TERMINAL_STATUSES:
            run.completed_at = datetime.now(timezone.utc)
            try:
                from app.observability.metrics import pipeline_runs_total

                pipeline_runs_total.inc(status=status)
            except Exception:  # noqa: BLE001
                pass
            try:
                from app.services.memory_gateway_service import extract_pipeline_episodic_memory
                from app.services.platform_events import publish_platform_event

                artifacts = await _load_artifact_map(db, run.id)
                cid = run.correlation_id or str(run.id)
                await extract_pipeline_episodic_memory(
                    run_id=str(run.id),
                    repo_full_name=run.repo_full_name,
                    status=status,
                    artifacts=artifacts,
                    correlation_id=cid,
                    trace_id=cid,
                )
                publish_platform_event(
                    "pipeline.completed",
                    correlation_id=cid,
                    tenant_id=(run.repo_full_name or "default").split("/")[0],
                    trace_id=cid,
                    payload={"run_id": str(run.id), "status": status, "repo": run.repo_full_name},
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("terminal memory/event hook failed: %s", exc)
        await db.commit()
        emit_ws(run.id, {"kind": "stage-update", "stage": status, "status": status})

    async def _handle_block(
        self,
        db: AsyncSession,
        run: PipelineRun,
        gh: GitHubService,
        status: str,
        result: dict[str, Any],
        agent: str,
        pr_urls: list[str] | None = None,
    ) -> None:
        summary = result.get("summary") or result.get("reason") or json.dumps(result, default=str)[:1000]
        await self._set_status(db, run, status, error_message=str(summary))
        await gh.safe_commit_status(run.repo_full_name, run.commit_id, "failure", f"Pipeline blocked: {status}")
        await self.slack_service.send_pipeline_blocked(run.id, reason=status, agent=agent, details=result, pr_urls=pr_urls)
        self.logger.warning("run %s blocked: %s (%s)", run.id, status, summary)
        try:
            artifacts = await _load_artifact_map(db, run.id)
            await persist_remediation_intelligence(db, run, artifacts=artifacts)
        except Exception as exc:
            self.logger.debug("remediation intelligence persist skipped: %s", exc)

    async def _open_fix_prs(
        self, db: AsyncSession, run: PipelineRun, combined: dict[str, Any], repo_path: str, github_token: str | None
    ) -> list[IssueBundle]:
        try:
            service = AutoPRService(github_token, run.repo_full_name, run.clone_url, run.branch)
        except ValueError as exc:
            self.logger.info("Auto-PR skipped for run %s: %s", run.id, exc)
            return []
        try:
            bundles = await service.open_all_prs(combined, repo_path, run.id, self.anthropic_client)
            if bundles:
                await service.save_pr_registry(db, run.id, bundles)
                sec = combined.get("security_issues") or {}
                qa = combined.get("qa_issues") or {}
                engineer = SoftwareEngineerAgent(run.id, db, self.anthropic_client)
                fix_report = await engineer.execute(
                    repo_path,
                    bundles,
                    security_passed=sec.get("passed") is not False,
                    qa_verdict=str(qa.get("verdict", "pass")),
                )
                artifacts = await _load_artifact_map(db, run.id)
                await persist_remediation_intelligence(
                    db,
                    run,
                    artifacts=artifacts,
                    fix_loop_report=fix_report,
                )
            return bundles
        except Exception as exc:
            self.logger.error("Auto-PR failed for run %s: %s", run.id, exc)
            return []
        finally:
            await service.close()

    async def _finish_without_deploy(self, db: AsyncSession, run: PipelineRun, gh: GitHubService) -> None:
        reason = "DEPLOY_MODE=skip"
        db.add(
            PipelineArtifact(
                pipeline_run_id=run.id,
                artifact_type="deployment_info",
                content={
                    "success": False,
                    "skipped": True,
                    "environment": settings.deploy_environment,
                    "summary": f"All quality gates passed; deployment skipped because {reason}.",
                },
            )
        )
        await db.commit()
        await self._set_status(db, run, "approved")
        await gh.safe_commit_status(
            run.repo_full_name, run.commit_id, "success", "All gates passed (deployment skipped)"
        )
        await self.slack_service.send_pipeline_deployed(
            run.id, run.commit_id, f"{settings.deploy_environment} (not deployed: {reason})"
        )
        self.logger.info("run %s approved; deployment skipped (%s)", run.id, reason)

    def _start_monitoring(self, run_id: uuid.UUID) -> None:
        from app.tasks.dispatch import dispatch_monitoring

        try:
            dispatch_monitoring(run_id)
        except Exception as exc:
            self.logger.warning("monitoring task dispatch failed (%s); running in-process", exc)
            asyncio.get_running_loop().create_task(self.run_monitoring(str(run_id)))

    async def execute_pipeline(
        self, pipeline_run_id: str, github_token: str | None = None, *, resume: bool = False
    ) -> None:
        run_uuid = uuid.UUID(str(pipeline_run_id))
        gh = GitHubService(token=github_token)

        async with AsyncSessionLocal() as db:
            run = (await db.execute(select(PipelineRun).where(PipelineRun.id == run_uuid))).scalar_one_or_none()
            if run is None:
                await gh.close()
                raise ValueError(f"Pipeline run not found: {pipeline_run_id}")

            mode_label = "resume" if resume else "start"
            self.logger.info("%s pipeline for run %s commit %s", mode_label, run.id, run.short_commit_id)
            if not resume:
                try:
                    from app.services.platform_events import publish_platform_event

                    cid = run.correlation_id or str(run.id)
                    publish_platform_event(
                        "pipeline.started",
                        correlation_id=cid,
                        tenant_id=(run.repo_full_name or "default").split("/")[0],
                        trace_id=cid,
                        payload={
                            "run_id": str(run.id),
                            "repo": run.repo_full_name,
                            "branch": run.branch,
                            "commit": run.commit_id,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("pipeline.started event publish failed: %s", exc)
            if "_orion_memory" not in db.info:
                db.info["_orion_memory"] = build_memory_store()
            if "_orion_retriever" not in db.info:
                db.info["_orion_retriever"] = build_retriever()
            client = self.anthropic_client
            stage = "ingesting"
            artifacts = await _load_artifact_map(db, run.id) if resume else {}
            repo_path = ""
            skip_ingest = resume and "metadata" in artifacts
            skip_scan = resume and _has_full_scan(artifacts)
            skip_stress = resume and "stress_report" in artifacts
            skip_approval_agent = (
                resume
                and str((artifacts.get("approval") or {}).get("decision", "")).lower() == "approved"
            )
            changed_files_list: list[str] = []
            try:
                if not skip_ingest:
                    await self._set_status(db, run, "ingesting")
                    await gh.safe_commit_status(run.repo_full_name, run.commit_id, "pending", "Pipeline running...")
                    await self.slack_service.send_pipeline_start(run.id, run.commit_id, run.branch, run.pusher)
                    repo_path = await self.git_service.clone_repo(run.clone_url, run.id, branch=run.branch)
                    index_repository(db.info["_orion_retriever"], repo_path)
                    diff_text = await self.git_service.get_diff(repo_path)
                    changed_files = await self.git_service.get_changed_files(repo_path)
                    changed_files_list = changed_files
                    commit_message = await self.git_service.get_commit_message(repo_path)
                    db.add_all(
                        [
                            PipelineArtifact(
                                pipeline_run_id=run.id,
                                artifact_type="metadata",
                                content={
                                    "repo": run.repo_full_name,
                                    "branch": run.branch,
                                    "commit": run.commit_id,
                                    "pusher": run.pusher,
                                    "commit_message": commit_message,
                                    "changed_files": changed_files,
                                },
                            ),
                            PipelineArtifact(
                                pipeline_run_id=run.id,
                                artifact_type="diff",
                                content={"diff": diff_text[:200000], "truncated": len(diff_text) > 200000},
                                raw_output=diff_text[:50000],
                            ),
                        ]
                    )
                    await db.commit()
                    injection = scan_repository_submission(commit_message, diff_text)
                    db.add(
                        PipelineArtifact(
                            pipeline_run_id=run.id,
                            artifact_type="prompt_injection_scan",
                            content=injection,
                        )
                    )
                    await db.commit()
                    if settings.prompt_injection_gate_enabled and injection.get("blocked"):
                        await self._handle_block(
                            db,
                            run,
                            gh,
                            "blocked_injection",
                            {
                                "summary": injection.get("summary"),
                                "findings": (injection.get("findings") or [])[:5],
                            },
                            "prompt_injection_firewall",
                        )
                        return
                else:
                    await gh.safe_commit_status(
                        run.repo_full_name, run.commit_id, "pending", "Pipeline resuming from checkpoint"
                    )
                    repo_path = await self.git_service.ensure_repo(run.clone_url, run.id, branch=run.branch)
                    index_repository(db.info["_orion_retriever"], repo_path)
                    diff_text = (artifacts.get("diff") or {}).get("diff") or await self.git_service.get_diff(repo_path)
                    meta = artifacts.get("metadata") or {}
                    if isinstance(meta.get("changed_files"), list):
                        changed_files_list = meta["changed_files"]

                if not skip_scan:
                    stage = "analyzing_code"
                    await self._set_status(db, run, "analyzing_code")

                    def _agent_done(label: str, result: dict[str, Any]) -> None:
                        agent_stage = AGENT_STAGE[label]
                        emit_ws(
                            run.id,
                            {
                                "kind": "agent-complete",
                                "stage": agent_stage,
                                "result_keys": list(result.keys()) if isinstance(result, dict) else [],
                            },
                        )
                        emit_ws(run.id, {"kind": "stage-update", "stage": agent_stage, "status": agent_stage})

                    combined = await FullScanOrchestrator(
                        run.id,
                        db,
                        client,
                        repo_path,
                        diff_text,
                        changed_files_list,
                        on_agent_complete=_agent_done,
                    ).execute()

                    block, reasons = block_status_for(combined)
                    if block:
                        bundles = await self._open_fix_prs(db, run, combined, repo_path, github_token)
                        opened = [b for b in bundles if b.pr_number]
                        pr_urls = [b.pr_url for b in opened if b.pr_url]
                        if opened:
                            block = "blocked_with_prs_sent"
                            summary = f"Pipeline blocked. {len(opened)} fix PRs opened: {', '.join(pr_urls)}"
                        else:
                            summary = "Pipeline blocked: " + "; ".join(reasons)
                        await self._handle_block(
                            db, run, gh, block, {"summary": summary, "reasons": reasons}, "full_scan", pr_urls=pr_urls
                        )
                        return

                    if has_warnings(combined):
                        run.has_warnings = True
                        await db.commit()

                    artifacts = await _load_artifact_map(db, run.id)
                    enrichment = await run_phase1_enrichment(
                        db,
                        run,
                        repo_path=repo_path,
                        diff_text=diff_text,
                        changed_files=changed_files_list,
                        skip_if_present=resume,
                        existing=artifacts,
                    )
                    secrets_scan = enrichment.get("secrets_scan") or artifacts.get("secrets_scan") or {}
                    if int(secrets_scan.get("critical_count") or 0) > 0:
                        await self._handle_block(
                            db,
                            run,
                            gh,
                            "blocked_secrets",
                            {
                                "summary": secrets_scan.get("summary"),
                                "findings": secrets_scan.get("findings", [])[:5],
                            },
                            "secrets_guardian",
                        )
                        return

                    test_intel = enrichment.get("test_intelligence") or artifacts.get("test_intelligence") or {}
                    if settings.test_coverage_gate_enabled and test_intel.get("gate_verdict") == "fail":
                        await self._handle_block(
                            db,
                            run,
                            gh,
                            "blocked_tests",
                            {
                                "summary": test_intel.get("summary"),
                                "violations": (test_intel.get("gates") or {}).get("violations", [])[:5],
                            },
                            "test_intelligence",
                        )
                        return

                    await run_phase2_enrichment(
                        db,
                        run,
                        repo_path=repo_path,
                        changed_files=changed_files_list,
                        skip_if_present=resume,
                        existing=await _load_artifact_map(db, run.id),
                    )
                else:
                    combined = _combined_from_artifacts(artifacts)
                    if not (resume and artifacts.get("service_graph")):
                        artifacts = await _load_artifact_map(db, run.id)
                        await run_phase1_enrichment(
                            db,
                            run,
                            repo_path=repo_path,
                            diff_text=diff_text,
                            changed_files=changed_files_list,
                            skip_if_present=False,
                            existing=artifacts,
                        )
                    if not (resume and artifacts.get("contract_test_report")):
                        await run_phase2_enrichment(
                            db,
                            run,
                            repo_path=repo_path,
                            changed_files=changed_files_list,
                            skip_if_present=True,
                            existing=await _load_artifact_map(db, run.id),
                        )

                if not skip_stress:
                    stage = "running_stress"
                    await self._set_status(db, run, "running_stress")
                    stress = await StressTestAgent(run.id, db, client, repo_path).execute()
                    verdict = str(stress.get("performance_verdict", "")).lower()
                    if verdict == "fail":
                        await self._handle_block(db, run, gh, "blocked_stress", stress, "stress_test")
                        return
                    if verdict == "warn":
                        run.has_warnings = True
                        await db.commit()
                    perf_intel = await persist_performance_intelligence(
                        db,
                        run,
                        stress_report=stress if isinstance(stress, dict) else {},
                        skip_if_present=resume,
                        existing=await _load_artifact_map(db, run.id),
                    )
                    if settings.performance_baseline_gate_enabled and perf_intel.get("gate_verdict") == "fail":
                        await self._handle_block(
                            db,
                            run,
                            gh,
                            "blocked_stress",
                            {
                                "summary": perf_intel.get("summary"),
                                "violations": (perf_intel.get("gates") or {}).get("violations", [])[:5],
                            },
                            "performance_intelligence",
                        )
                        return
                    dast = await persist_dast_report(
                        db,
                        run,
                        skip_if_present=resume,
                        existing=await _load_artifact_map(db, run.id),
                    )
                    if settings.dast_gate_enabled and dast.get("gate_verdict") == "fail":
                        await self._handle_block(
                            db,
                            run,
                            gh,
                            "blocked_dast",
                            {
                                "summary": dast.get("summary"),
                                "violations": (dast.get("gates") or {}).get("violations", [])[:5],
                            },
                            "dast_scan",
                        )
                        return
                    if dast.get("verdict") == "warn":
                        run.has_warnings = True
                        await db.commit()
                else:
                    stress = artifacts.get("stress_report") or {}
                    if stress and not stress.get("skipped"):
                        await persist_performance_intelligence(
                            db,
                            run,
                            stress_report=stress,
                            skip_if_present=resume,
                            existing=artifacts,
                        )

                stage = "change_risk"
                artifacts = await _load_artifact_map(db, run.id)
                metadata = artifacts.get("metadata") or {}
                await _persist_change_risk_report(
                    db,
                    run,
                    diff_text=diff_text,
                    changed_files=metadata.get("changed_files") if isinstance(metadata.get("changed_files"), list) else None,
                    combined=combined if isinstance(combined, dict) else _combined_from_artifacts(artifacts),
                    stress=stress if isinstance(stress, dict) else {},
                    skip_if_present=resume,
                    artifacts=artifacts,
                )

                artifacts = await _load_artifact_map(db, run.id)

                await persist_code_review_intelligence(
                    db,
                    run,
                    artifacts=artifacts,
                    skip_if_present=resume,
                )
                artifacts = await _load_artifact_map(db, run.id)

                stage = "enterprise_enrichment"
                await run_phase4_enrichment(
                    db,
                    run,
                    artifacts=artifacts,
                    skip_if_present=resume,
                    include_policy=False,
                )

                if not skip_approval_agent:
                    stage = "awaiting_approval"
                    await self._set_status(db, run, "awaiting_approval")
                    decision = await ApprovalAgent(run.id, db, client).execute()
                    if str(decision.get("decision", "")).lower() == "rejected":
                        await self._handle_block(db, run, gh, "rejected", decision, "approval")
                        return
                else:
                    decision = artifacts.get("approval") or {}

                artifacts = await _load_artifact_map(db, run.id)
                if not artifacts.get("enterprise_approval"):
                    enterprise = await init_enterprise_approval(
                        db, run, automated_approval=decision, artifacts=artifacts
                    )
                else:
                    enterprise = {
                        **artifacts["enterprise_approval"],
                        **evaluate_enterprise_approval(artifacts["enterprise_approval"]),
                    }

                if str(enterprise.get("status")) == "rejected":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "rejected",
                        {
                            "summary": enterprise.get("summary"),
                            "violations": (enterprise.get("violations") or [])[:5],
                        },
                        "enterprise_approval",
                    )
                    return

                if settings.enterprise_approval_enforcement_enabled and not enterprise_approval_ready(enterprise):
                    await self._set_status(db, run, "awaiting_approval")
                    await gh.safe_commit_status(
                        run.repo_full_name,
                        run.commit_id,
                        "pending",
                        (
                            "Awaiting enterprise approval "
                            f"({enterprise.get('received_approvals', 0)}/{enterprise.get('required_approvals', 1)})"
                        ),
                    )
                    emit_ws(
                        run.id,
                        {
                            "kind": "artifact",
                            "artifact_type": "approval_intelligence",
                            "agent": "enterprise_approval",
                            "summary": enterprise.get("summary", "Awaiting enterprise sign-offs"),
                        },
                    )
                    self.logger.info(
                        "Pipeline %s paused for enterprise approval (%s/%s)",
                        run.id,
                        enterprise.get("received_approvals"),
                        enterprise.get("required_approvals"),
                    )
                    return

                artifacts = await _load_artifact_map(db, run.id)
                policy_eval = await run_phase4_policy_gate(db, run, artifacts=artifacts)
                if settings.policy_enforcement_enabled and not policy_eval.get("passed", True):
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_policy",
                        {
                            "summary": policy_eval.get("summary"),
                            "violations": (policy_eval.get("violations") or [])[:5],
                        },
                        "policy_engine",
                    )
                    return

                stage = "ai_governance"
                artifacts = await _load_artifact_map(db, run.id)
                phase5 = await run_phase5_enrichment(
                    db,
                    run,
                    artifacts=artifacts,
                    skip_if_present=resume,
                    memory_store=db.info.get("_orion_memory"),
                    retriever=db.info.get("_orion_retriever"),
                    repo_path=repo_path or None,
                )
                agent_eval = phase5.get("agent_eval_report") or artifacts.get("agent_eval_report") or {}
                if settings.agent_eval_gate_enabled and agent_eval.get("human_review_required"):
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_agent_eval",
                        {
                            "summary": agent_eval.get("summary"),
                            "low_scoring_artifacts": agent_eval.get("low_scoring_artifacts", []),
                        },
                        "agent_eval",
                    )
                    return

                governance_intel = phase5.get("ai_governance_intelligence") or {}
                if settings.ai_governance_gate_enabled and governance_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_governance",
                        {
                            "summary": governance_intel.get("summary"),
                            "escalations": (governance_intel.get("escalations") or [])[:5],
                            "violations": (governance_intel.get("gates") or {}).get("violations", [])[:5],
                        },
                        "ai_governance",
                    )
                    return

                mesh_intel = phase5.get("agent_mesh_intelligence") or {}
                if settings.agent_mesh_gate_enabled and mesh_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_mesh",
                        {
                            "summary": mesh_intel.get("summary"),
                            "violations": (mesh_intel.get("health") or {}).get("violations", [])[:5],
                        },
                        "agent_mesh",
                    )
                    return

                finops_intel = phase5.get("finops_intelligence") or {}
                if settings.finops_gate_enabled and finops_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_finops",
                        {
                            "summary": finops_intel.get("summary"),
                            "violations": (finops_intel.get("gates") or {}).get("violations", [])[:5],
                        },
                        "finops",
                    )
                    return

                artifacts = await _load_artifact_map(db, run.id)
                deploy_mode = await asyncio.to_thread(resolved_deploy_mode)
                from app.utils.cloud_intelligence import build_cloud_intelligence_report

                cloud_check = build_cloud_intelligence_report(
                    repo=run.repo_full_name,
                    repo_path=repo_path,
                    environment=settings.deploy_environment,
                    deploy_mode=deploy_mode,
                    kubernetes_manifest_scan=artifacts.get("kubernetes_manifest_scan"),
                    iac_security_scan=artifacts.get("iac_security_scan"),
                    container_security_scan=artifacts.get("container_security_scan"),
                    dockerfile_analysis=artifacts.get("dockerfile_analysis"),
                    service_graph=artifacts.get("service_graph"),
                )
                if settings.cloud_intelligence_gate_enabled and cloud_check.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_cloud",
                        {
                            "summary": cloud_check.get("summary"),
                            "violations": (cloud_check.get("gates") or {}).get("violations", [])[:5],
                        },
                        "cloud_intelligence",
                    )
                    return

                from app.utils.service_catalog_intelligence import build_service_catalog_intelligence_report

                catalog_check = build_service_catalog_intelligence_report(
                    repo=run.repo_full_name,
                    repo_path=repo_path,
                    artifacts=artifacts,
                )
                if settings.service_catalog_gate_enabled and catalog_check.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_catalog",
                        {
                            "summary": catalog_check.get("summary"),
                            "violations": (catalog_check.get("gates") or {}).get("violations", [])[:5],
                        },
                        "service_catalog",
                    )
                    return
                passport = await persist_release_passport(
                    db,
                    run,
                    artifacts,
                    deploy_mode=deploy_mode,
                    environment=settings.deploy_environment,
                )
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "release_passport",
                        "agent": "release_passport",
                        "summary": f"Release passport {'PASS' if passport.get('all_checks_passed') else 'WARN'}",
                    },
                )
                artifacts = await _load_artifact_map(db, run.id)
                release_intel = await persist_release_intelligence(
                    db,
                    run,
                    artifacts=artifacts,
                    deploy_mode=deploy_mode,
                    environment=settings.deploy_environment,
                )
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "release_intelligence",
                        "agent": "release_intelligence",
                        "summary": release_intel.get("summary", "Release intelligence complete"),
                    },
                )
                if settings.release_intelligence_gate_enabled and release_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_release",
                        {
                            "summary": release_intel.get("summary"),
                            "violations": (release_intel.get("gates") or {}).get("violations", [])[:5],
                            "failure_probability": (release_intel.get("release_prediction") or {}).get(
                                "failure_probability_percent"
                            ),
                        },
                        "release_intelligence",
                    )
                    return

                try:
                    pr_intel = await post_pr_intelligence(
                        gh,
                        repo_full_name=run.repo_full_name,
                        commit_sha=run.commit_id,
                        artifacts=await _load_artifact_map(db, run.id),
                    )
                except Exception as exc:
                    self.logger.info("PR intelligence comment skipped for %s: %s", run.id, exc)
                    pr_intel = {
                        "posted": False,
                        "summary": f"PR intelligence skipped: {exc}",
                        "error": str(exc),
                    }
                db.add(
                    PipelineArtifact(
                        pipeline_run_id=run.id,
                        artifact_type="pr_intelligence",
                        content=pr_intel,
                    )
                )
                await db.commit()
                artifacts = await _load_artifact_map(db, run.id)
                dev_ux = await persist_developer_ux_intelligence(db, run, artifacts=artifacts)
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "developer_ux_intelligence",
                        "agent": "developer_ux",
                        "summary": dev_ux.get("summary", "Developer UX intelligence complete"),
                    },
                )
                artifacts = await _load_artifact_map(db, run.id)
                iam_intel = await persist_iam_intelligence(db, run, artifacts=artifacts)
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "iam_intelligence",
                        "agent": "enterprise_iam",
                        "summary": iam_intel.get("summary", "Enterprise IAM intelligence complete"),
                    },
                )
                if settings.iam_gate_enabled and iam_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_iam",
                        {
                            "summary": iam_intel.get("summary"),
                            "violations": (iam_intel.get("gates") or {}).get("violations", [])[:5],
                            "readiness_score": iam_intel.get("readiness_score"),
                        },
                        "enterprise_iam",
                    )
                    return

                artifacts = await _load_artifact_map(db, run.id)
                reliability_intel = await persist_reliability_intelligence(db, run, artifacts=artifacts)
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "reliability_intelligence",
                        "agent": "reliability",
                        "summary": reliability_intel.get("summary", "Reliability intelligence complete"),
                    },
                )
                if settings.reliability_gate_enabled and reliability_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_reliability",
                        {
                            "summary": reliability_intel.get("summary"),
                            "violations": (reliability_intel.get("gates") or {}).get("violations", [])[:5],
                            "resilience_score": reliability_intel.get("resilience_score"),
                        },
                        "reliability",
                    )
                    return

                artifacts = await _load_artifact_map(db, run.id)
                dr_intel = await persist_dr_intelligence(db, run, artifacts=artifacts)
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "dr_intelligence",
                        "agent": "disaster_recovery",
                        "summary": dr_intel.get("summary", "Disaster recovery intelligence complete"),
                    },
                )
                if settings.dr_gate_enabled and dr_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_dr",
                        {
                            "summary": dr_intel.get("summary"),
                            "violations": (dr_intel.get("gates") or {}).get("violations", [])[:5],
                            "readiness_score": dr_intel.get("readiness_score"),
                        },
                        "disaster_recovery",
                    )
                    return

                artifacts = await _load_artifact_map(db, run.id)
                kg_intel = await persist_knowledge_graph_intelligence(db, run, artifacts=artifacts)
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "knowledge_graph_intelligence",
                        "agent": "knowledge_graph",
                        "summary": kg_intel.get("summary", "Knowledge graph intelligence complete"),
                    },
                )
                if settings.knowledge_graph_gate_enabled and kg_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_knowledge",
                        {
                            "summary": kg_intel.get("summary"),
                            "violations": (kg_intel.get("gates") or {}).get("violations", [])[:5],
                            "coverage_percent": (kg_intel.get("coverage") or {}).get("coverage_percent"),
                        },
                        "knowledge_graph",
                    )
                    return

                artifacts = await _load_artifact_map(db, run.id)
                autopilot_intel = await persist_autopilot_intelligence(
                    db,
                    run,
                    artifacts=artifacts,
                    environment=settings.deploy_environment,
                )
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "autopilot_intelligence",
                        "agent": "autopilot",
                        "summary": autopilot_intel.get("summary", "Autopilot intelligence complete"),
                    },
                )
                if settings.autopilot_gate_enabled and autopilot_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_autopilot",
                        {
                            "summary": autopilot_intel.get("summary"),
                            "violations": (autopilot_intel.get("gates") or {}).get("violations", [])[:5],
                            "primary_action": (autopilot_intel.get("primary_action") or {}).get("id"),
                        },
                        "autopilot",
                    )
                    return

                artifacts = await _load_artifact_map(db, run.id)
                unified_risk_intel = await persist_unified_risk_intelligence(
                    db,
                    run,
                    artifacts=artifacts,
                    environment=settings.deploy_environment,
                    diff_text=diff_text,
                )
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "unified_risk_intelligence",
                        "agent": "unified_risk",
                        "summary": unified_risk_intel.get("summary", "Unified risk intelligence complete"),
                    },
                )
                if settings.unified_risk_gate_enabled and unified_risk_intel.get("gate_verdict") == "fail":
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        "blocked_unified_risk",
                        {
                            "summary": unified_risk_intel.get("summary"),
                            "unified_score": unified_risk_intel.get("unified_score"),
                            "risk_level": unified_risk_intel.get("risk_level"),
                            "violations": (unified_risk_intel.get("gates") or {}).get("violations", [])[:5],
                            "primary_driver": unified_risk_intel.get("primary_driver"),
                        },
                        "unified_risk",
                    )
                    return

                stage = "deploying"
                if deploy_mode == "skip":
                    await self._finish_without_deploy(db, run, gh)
                    return
                await self._set_status(db, run, "deploying")
                deployer = DeploymentAgent(run.id, db, client, repo_path, run.commit_id)
                if deploy_mode == "simulate":
                    deployment = await deployer.execute_simulated()
                else:
                    deployment = await deployer.execute()
                if not deployment.get("success"):
                    await db.refresh(run)
                    status = "rolled_back" if (deployment.get("rollback") or {}).get("rolled_back") else "failed"
                    await self._handle_block(
                        db,
                        run,
                        gh,
                        status,
                        {"summary": deployment.get("error") or "deployment health check failed", **deployment},
                        "deployment",
                    )
                    return

                await self._set_status(db, run, "deployed")
                artifacts = await _load_artifact_map(db, run.id)
                recent_runs = (
                    await db.execute(
                        select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(20)
                    )
                ).scalars().all()
                phase3_obs = await run_phase3_observability(
                    db,
                    run,
                    artifacts=artifacts,
                    recent_runs=recent_runs,
                    simulated=deploy_mode == "simulate",
                )
                artifacts = await _load_artifact_map(db, run.id)
                await persist_deployment_intelligence(db, run, artifacts=artifacts, skip_if_present=resume)
                cloud_intel = await persist_cloud_intelligence(
                    db,
                    run,
                    artifacts=artifacts,
                    repo_path=repo_path,
                    deploy_mode=deploy_mode,
                    skip_if_present=False,
                )
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "cloud_intelligence",
                        "agent": "cloud_intelligence",
                        "summary": cloud_intel.get("summary", "Cloud intelligence complete"),
                    },
                )
                artifacts = await _load_artifact_map(db, run.id)
                fleet_runs = (
                    await db.execute(select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(50))
                ).scalars().all()
                fleet_arts = await _load_artifacts_for_runs(db, [r.id for r in fleet_runs])
                catalog_intel = await persist_service_catalog_intelligence(
                    db,
                    run,
                    artifacts=artifacts,
                    repo_path=repo_path,
                    fleet_runs=fleet_runs,
                    fleet_artifacts=fleet_arts,
                    skip_if_present=resume,
                )
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "service_catalog_intelligence",
                        "agent": "service_catalog",
                        "summary": catalog_intel.get("summary", "Service catalog intelligence complete"),
                    },
                )
                prior = (
                    await db.execute(
                        select(PipelineRun)
                        .where(PipelineRun.repo_full_name == run.repo_full_name, PipelineRun.id != run.id)
                        .order_by(PipelineRun.created_at.desc())
                        .limit(15)
                    )
                ).scalars().all()
                hist_syn: list[dict[str, Any]] = []
                hist_stress: list[dict[str, Any]] = []
                for prior_run in prior:
                    rows = (
                        await db.execute(
                            select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == prior_run.id)
                        )
                    ).scalars().all()
                    arts = {a.artifact_type: a.content or {} for a in rows}
                    syn = arts.get("synthetic_monitoring_report")
                    if isinstance(syn, dict) and syn.get("journeys"):
                        hist_syn.append(syn)
                    stress = arts.get("stress_report")
                    if isinstance(stress, dict) and not stress.get("skipped"):
                        hist_stress.append(stress)
                obs_intel = await persist_observability_intelligence(
                    db,
                    run,
                    artifacts=artifacts,
                    historical_synthetic=hist_syn,
                    historical_stress=hist_stress,
                    skip_if_present=resume,
                )
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "observability_intelligence",
                        "agent": "observability_intelligence",
                        "summary": obs_intel.get("summary", "Observability intelligence complete"),
                    },
                )
                emit_ws(
                    run.id,
                    {
                        "kind": "artifact",
                        "artifact_type": "error_budget_report",
                        "agent": "error_budget",
                        "summary": (phase3_obs.get("error_budget_report") or {}).get("summary", "SRE observability complete"),
                    },
                )
                artifacts = await _load_artifact_map(db, run.id)
                if collect_multimodal_artifacts(artifacts):
                    mm_intel = await persist_multimodal_intelligence(
                        db,
                        run,
                        artifacts=artifacts,
                        skip_if_present=resume,
                    )
                    emit_ws(
                        run.id,
                        {
                            "kind": "artifact",
                            "artifact_type": "multimodal_intelligence",
                            "agent": "multimodal_intelligence",
                            "summary": mm_intel.get("summary", "Multimodal intelligence complete"),
                        },
                    )
                await gh.safe_commit_status(
                    run.repo_full_name, run.commit_id, "success", "Pipeline passed, deployed successfully"
                )
                await self.slack_service.send_pipeline_deployed(run.id, run.commit_id, settings.deploy_environment)
                self._start_monitoring(run.id)
            except (PipelineCancelled, asyncio.CancelledError) as exc:
                self.logger.warning("pipeline %s cancelled during %s", run_uuid, stage)
                await gh.safe_commit_status(run.repo_full_name, run.commit_id, "error", "Pipeline cancelled")
                emit_ws(run_uuid, {"kind": "stage-update", "stage": "cancelled", "status": "cancelled"})
                if isinstance(exc, asyncio.CancelledError):
                    raise
            except Exception as exc:
                self.logger.exception("pipeline %s failed during %s", run_uuid, stage)
                await db.rollback()
                # rollback expires loaded attributes; async sessions cannot lazy-load them implicitly
                await db.refresh(run)
                if run.status != "cancelled":
                    await self._set_status(db, run, "failed", error_message=f"Stage {stage} failed: {exc}")
                    await gh.safe_commit_status(
                        run.repo_full_name, run.commit_id, "error", f"Pipeline error in {stage}"
                    )
                    await self.slack_service.send_pipeline_blocked(
                        run.id, reason="failed", agent=stage, details={"error": str(exc)}
                    )
            finally:
                self.git_service.cleanup_repo(run_uuid)
                await gh.close()

    async def run_monitoring(self, pipeline_run_id: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            return await MonitoringAgent(uuid.UUID(str(pipeline_run_id)), db, self.anthropic_client).execute()


orchestrator = PipelineOrchestrator()

from __future__ import annotations

import logging
import shutil
import tempfile
import traceback
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.approval_agent import ApprovalAgent
from app.agents.code_analysis import CodeAnalysisAgent
from app.agents.deployment import DeploymentAgent
from app.agents.monitoring import MonitoringAgent
from app.agents.qa_agent import QAAgent
from app.agents.security import SecurityAgent
from app.agents.stress_agent import StressAgent
from celery import shared_task

from app.agents.base_agent import AgentInput, AgentOutput
from app.database_sync import SyncSessionLocal
from app.github_snapshot import fetch_repo_snapshot, fetch_zipball_to_temp
from app.models import AgentLog, PipelineRun, PipelineStatus, StageResult
from app.redis_publish import publish_pipeline_event
from app.config import get_settings
from app.services.integrations import (
    parse_repo_full_name,
    record_auto_pr_registry,
    set_commit_status,
    slack_notify,
)

logger = logging.getLogger(__name__)


def _stage_map(db: Session, pipeline_id: UUID) -> dict[str, StageResult]:
    rows = db.query(StageResult).filter(StageResult.pipeline_id == pipeline_id).all()
    return {row.stage: row for row in rows}


def _output_from_stage(row: StageResult) -> AgentOutput:
    payload = row.output_json or {}
    return AgentOutput(
        passed=row.passed,
        summary=str(payload.get("summary") or row.stage),
        artifacts=payload if isinstance(payload, dict) else {},
        next_context=payload if isinstance(payload, dict) else {},
    )


def _emit_status(db: Session, pipeline: PipelineRun, new_status: PipelineStatus) -> None:
    old = pipeline.status
    pipeline.status = new_status
    pipeline.updated_at = datetime.now(timezone.utc)
    db.commit()
    publish_pipeline_event(
        str(pipeline.id),
        {
            "type": "status_change",
            "pipeline_id": str(pipeline.id),
            "old_status": old.value if hasattr(old, "value") else str(old),
            "new_status": new_status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def _save_stage_result(
    db: Session, pipeline_id: UUID, stage: str, passed: bool, output: dict | None
) -> None:
    row = StageResult(
        pipeline_id=pipeline_id,
        stage=stage,
        passed=passed,
        output_json=output or {},
    )
    db.add(row)
    db.commit()


def _run_pipeline_impl(pipeline_id: str) -> None:
    pid = UUID(pipeline_id)
    db = SyncSessionLocal()
    temp_dir = tempfile.mkdtemp(prefix="pipeline_")
    try:
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        if not pipeline:
            logger.error("Pipeline %s not found", pipeline_id)
            return

        meta = dict(pipeline.metadata_json or {})
        resume = bool(meta.pop("resume", False))
        if resume:
            pipeline.metadata_json = meta
            db.commit()
        stage_cache = _stage_map(db, pid) if resume else {}

        repo_url = meta.get("repo_url") or pipeline.repo_url
        repo_full = parse_repo_full_name(repo_url)
        settings = get_settings()

        slack_notify(f":rocket: DevOps pipeline `{pipeline_id}` started for {repo_url}")
        set_commit_status(repo_full, pipeline.commit_sha or None, "pending", "ORION DevOps pipeline running")

        # 1) Fetch sources
        _emit_status(db, pipeline, PipelineStatus.DEV)
        if resume and meta.get("temp_dir") and meta.get("code_snapshot"):
            inner_path = meta["temp_dir"]
            snapshot = meta["code_snapshot"]
            commit_sha = pipeline.commit_sha or meta.get("commit_sha", "")
        else:
            try:
                commit_sha, inner_path = fetch_zipball_to_temp(repo_url, temp_dir)
                snapshot = fetch_repo_snapshot(repo_url)
                meta.update(
                    {
                        "repo_url": repo_url,
                        "commit_sha": commit_sha,
                        "temp_dir": inner_path,
                        "code_snapshot": snapshot,
                    }
                )
                pipeline.commit_sha = commit_sha
                pipeline.metadata_json = meta
                db.commit()
                set_commit_status(repo_full, commit_sha, "pending", "ORION DevOps pipeline running")
            except Exception as e:
                logger.exception("Repo fetch failed")
                _fail_pipeline(db, pipeline, f"Repo fetch failed: {e}")
                return

        ctx = {
            "metadata_json": meta,
            "code_snapshot": snapshot,
            "temp_dir": inner_path,
        }

        def _cancelled() -> bool:
            fresh = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
            extra = dict(fresh.metadata_json or {}) if fresh else {}
            return bool(extra.get("cancelled"))

        if _cancelled():
            _emit_status(db, pipeline, PipelineStatus.CANCELLED)
            return

        # 2) Code analysis
        if resume and "code_analysis" in stage_cache:
            out_ca = _output_from_stage(stage_cache["code_analysis"])
        else:
            ca = CodeAnalysisAgent(db)
            out_ca = ca.run(AgentInput(pipeline_id=pid, stage_name="DEV", context=ctx))
            _save_stage_result(db, pid, "code_analysis", out_ca.passed, out_ca.artifacts)
        if not out_ca.passed:
            _fail_pipeline(db, pipeline, "Code analysis failed")
            return

        # 3) Security
        if resume and "security" in stage_cache:
            out_sec = _output_from_stage(stage_cache["security"])
        else:
            sec = SecurityAgent(db)
            out_sec = sec.run(AgentInput(pipeline_id=pid, stage_name="DEV", context={**ctx, **out_ca.next_context}))
            _save_stage_result(db, pid, "security", out_sec.passed, out_sec.artifacts)
        if not out_sec.passed:
            pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
            if settings.auto_pr_enabled:
                pipeline.metadata_json = record_auto_pr_registry(
                    dict(pipeline.metadata_json or {}),
                    reason="Security gate failed",
                    stage="security",
                )
                db.commit()
            _emit_status(db, pipeline, PipelineStatus.BLOCKED)
            set_commit_status(repo_full, pipeline.commit_sha, "failure", "Blocked by security gate")
            slack_notify(f":no_entry: Pipeline `{pipeline_id}` blocked at security")
            publish_pipeline_event(
                str(pid),
                {"type": "log", "stage": "BLOCKED", "level": "BLOCKED", "message": "Security gate closed pipeline", "timestamp": datetime.now(timezone.utc).isoformat()},
            )
            return

        # 4) QA
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.QA)
        if resume and "qa" in stage_cache:
            out_qa = _output_from_stage(stage_cache["qa"])
        else:
            qa = QAAgent(db)
            out_qa = qa.run(AgentInput(pipeline_id=pid, stage_name="QA", context=ctx))
            _save_stage_result(db, pid, "qa", out_qa.passed, out_qa.artifacts)
        if not out_qa.passed:
            _fail_pipeline(db, pipeline, "QA stage failed")
            return

        # 5) Stress
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.STRESS)
        if resume and "stress" in stage_cache:
            out_st = _output_from_stage(stage_cache["stress"])
        else:
            st = StressAgent(db)
            out_st = st.run(AgentInput(pipeline_id=pid, stage_name="STRESS", context=ctx))
            _save_stage_result(db, pid, "stress", out_st.passed, out_st.artifacts)
        if not out_st.passed:
            _fail_pipeline(db, pipeline, "Stress stage failed")
            return

        stage_ctx = {
            "code_analysis": (out_ca.artifacts or {}).get("code_analysis", out_ca.artifacts),
            "security": (out_sec.artifacts or {}).get("security", out_sec.artifacts),
            "qa": (out_qa.artifacts or {}).get("qa", out_qa.artifacts),
            "stress": (out_st.artifacts or {}).get("stress", out_st.artifacts),
        }

        # 6) Approval (gate fusion + LLM)
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.APPROVAL)
        if resume and "approval" in stage_cache and stage_cache["approval"].passed:
            out_appr = _output_from_stage(stage_cache["approval"])
        else:
            appr = ApprovalAgent(db)
            out_appr = appr.run(AgentInput(pipeline_id=pid, stage_name="APPROVAL", context=stage_ctx))
            _save_stage_result(db, pid, "approval", out_appr.passed, out_appr.artifacts)
        if not out_appr.passed:
            pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
            if settings.auto_pr_enabled:
                pipeline.metadata_json = record_auto_pr_registry(
                    dict(pipeline.metadata_json or {}),
                    reason=out_appr.summary,
                    stage="approval",
                )
                db.commit()
            _emit_status(db, pipeline, PipelineStatus.BLOCKED)
            set_commit_status(repo_full, pipeline.commit_sha, "failure", "Approval rejected")
            slack_notify(f":no_entry: Pipeline `{pipeline_id}` blocked at approval")
            publish_pipeline_event(
                str(pid),
                {"type": "artifact", "stage": "approval", "data": out_appr.artifacts},
            )
            return

        # 7) Deployment
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.DEPLOYMENT)
        if resume and "deployment" in stage_cache and stage_cache["deployment"].passed:
            out_dep = _output_from_stage(stage_cache["deployment"])
        else:
            dep = DeploymentAgent(db)
            out_dep = dep.run(AgentInput(pipeline_id=pid, stage_name="DEPLOYMENT", context=ctx))
            _save_stage_result(db, pid, "deployment", out_dep.passed, out_dep.artifacts)
        if not out_dep.passed:
            _fail_pipeline(db, pipeline, "Deployment failed")
            return

        # 8) Monitoring — use recent pipeline logs instead of hardcoded sample text
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.MONITORING)
        mon = MonitoringAgent(db)
        recent = (
            db.query(AgentLog)
            .filter(AgentLog.pipeline_id == pid)
            .order_by(AgentLog.timestamp.desc())
            .limit(80)
            .all()
        )
        log_lines = [f"{row.level} [{row.stage}] {row.message}" for row in reversed(recent)]
        deployment = (out_dep.artifacts or {}).get("deployment") or {}
        if deployment.get("simulated"):
            log_lines.append("INFO simulated deployment completed successfully")
        elif deployment.get("skipped"):
            log_lines.append("INFO deployment skipped by policy")
        elif deployment.get("container_id"):
            log_lines.append(f"INFO container {deployment['container_id']} running")
        log_text = "\n".join(log_lines) if log_lines else "Application started\nHealth check OK\n"
        out_mon = mon.run(
            AgentInput(
                pipeline_id=pid,
                stage_name="MONITORING",
                context={**ctx, "log_text": log_text},
            )
        )
        _save_stage_result(db, pid, "monitoring", out_mon.passed, out_mon.artifacts)

        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.COMPLETED)
        set_commit_status(repo_full, pipeline.commit_sha, "success", "Pipeline completed")
        slack_notify(f":white_check_mark: Pipeline `{pipeline_id}` completed")

    except Exception as e:
        logger.exception("Pipeline crashed: %s", e)
        try:
            pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
            if pipeline:
                err = AgentLog(
                    pipeline_id=pid,
                    stage="SYSTEM",
                    level="ERROR",
                    message=f"{e}\n{traceback.format_exc()}",
                    timestamp=datetime.now(timezone.utc),
                )
                db.add(err)
                db.commit()
                _emit_status(db, pipeline, PipelineStatus.FAILED)
                publish_pipeline_event(
                    str(pid),
                    {
                        "type": "alert",
                        "message": str(e),
                        "severity": "critical",
                    },
                )
        except Exception:
            db.rollback()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        db.close()


def _fail_pipeline(db: Session, pipeline: PipelineRun, msg: str) -> None:
    meta = dict(pipeline.metadata_json or {})
    repo_url = meta.get("repo_url") or pipeline.repo_url
    repo_full = parse_repo_full_name(repo_url)
    log = AgentLog(
        pipeline_id=pipeline.id,
        stage=pipeline.status.value if pipeline.status else "SYSTEM",
        level="ERROR",
        message=msg,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
    set_commit_status(repo_full, pipeline.commit_sha, "failure", msg[:140])
    slack_notify(f":x: Pipeline `{pipeline.id}` failed: {msg[:200]}")
    _emit_status(db, pipeline, PipelineStatus.FAILED)


@shared_task(name="app.orchestrator.pipeline_runner.run_pipeline")
def run_pipeline(pipeline_id: str) -> None:
    _run_pipeline_impl(pipeline_id)

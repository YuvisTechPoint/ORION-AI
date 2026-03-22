from __future__ import annotations

import logging
import shutil
import tempfile
import traceback
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.code_analysis import CodeAnalysisAgent
from app.agents.deployment import DeploymentAgent
from app.agents.monitoring import MonitoringAgent
from app.agents.qa_agent import QAAgent
from app.agents.security import SecurityAgent
from app.agents.stress_agent import StressAgent
from celery import shared_task

from app.agents.base_agent import AgentInput
from app.database_sync import SyncSessionLocal
from app.github_snapshot import fetch_repo_snapshot, fetch_zipball_to_temp
from app.models import AgentLog, PipelineRun, PipelineStatus, StageResult
from app.redis_publish import publish_pipeline_event

logger = logging.getLogger(__name__)


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
        repo_url = meta.get("repo_url") or pipeline.repo_url

        # 1) Fetch sources
        _emit_status(db, pipeline, PipelineStatus.DEV)
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
        except Exception as e:
            logger.exception("Repo fetch failed")
            _fail_pipeline(db, pipeline, f"Repo fetch failed: {e}")
            return

        ctx = {
            "metadata_json": meta,
            "code_snapshot": snapshot,
            "temp_dir": inner_path,
        }

        # 2) Code analysis
        ca = CodeAnalysisAgent(db)
        out_ca = ca.run(AgentInput(pipeline_id=pid, stage_name="DEV", context=ctx))
        _save_stage_result(db, pid, "code_analysis", out_ca.passed, out_ca.artifacts)
        if not out_ca.passed:
            _fail_pipeline(db, pipeline, "Code analysis failed")
            return

        # 3) Security
        sec = SecurityAgent(db)
        out_sec = sec.run(AgentInput(pipeline_id=pid, stage_name="DEV", context={**ctx, **out_ca.next_context}))
        _save_stage_result(db, pid, "security", out_sec.passed, out_sec.artifacts)
        if not out_sec.passed:
            pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
            _emit_status(db, pipeline, PipelineStatus.BLOCKED)
            publish_pipeline_event(
                str(pid),
                {"type": "log", "stage": "BLOCKED", "level": "BLOCKED", "message": "Security gate closed pipeline", "timestamp": datetime.now(timezone.utc).isoformat()},
            )
            return

        # 4) QA
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.QA)
        qa = QAAgent(db)
        out_qa = qa.run(AgentInput(pipeline_id=pid, stage_name="QA", context=ctx))
        _save_stage_result(db, pid, "qa", out_qa.passed, out_qa.artifacts)
        if not out_qa.passed:
            _fail_pipeline(db, pipeline, "QA stage failed")
            return

        # 5) Stress
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.STRESS)
        st = StressAgent(db)
        out_st = st.run(AgentInput(pipeline_id=pid, stage_name="STRESS", context=ctx))
        _save_stage_result(db, pid, "stress", out_st.passed, out_st.artifacts)
        if not out_st.passed:
            _fail_pipeline(db, pipeline, "Stress stage failed")
            return

        # 6) Approval
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.APPROVAL)
        log = AgentLog(
            pipeline_id=pid,
            stage="APPROVAL",
            level="INFO",
            message="All prior stages passed — approval granted by policy",
            timestamp=datetime.now(timezone.utc),
        )
        db.add(log)
        db.commit()
        publish_pipeline_event(
            str(pid),
            {
                "type": "log",
                "stage": "APPROVAL",
                "level": "INFO",
                "message": log.message,
                "timestamp": log.timestamp.isoformat(),
            },
        )

        # 7) Deployment
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.DEPLOYMENT)
        dep = DeploymentAgent(db)
        out_dep = dep.run(AgentInput(pipeline_id=pid, stage_name="DEPLOYMENT", context=ctx))
        _save_stage_result(db, pid, "deployment", out_dep.passed, out_dep.artifacts)
        if not out_dep.passed:
            _fail_pipeline(db, pipeline, "Deployment failed")
            return

        # 8) Monitoring
        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.MONITORING)
        mon = MonitoringAgent(db)
        sample_logs = "Application started\nHealth check OK\n"
        out_mon = mon.run(
            AgentInput(
                pipeline_id=pid,
                stage_name="MONITORING",
                context={**ctx, "log_text": sample_logs},
            )
        )
        _save_stage_result(db, pid, "monitoring", out_mon.passed, out_mon.artifacts)

        pipeline = db.query(PipelineRun).filter(PipelineRun.id == pid).first()
        _emit_status(db, pipeline, PipelineStatus.COMPLETED)

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
    log = AgentLog(
        pipeline_id=pipeline.id,
        stage=pipeline.status.value if pipeline.status else "SYSTEM",
        level="ERROR",
        message=msg,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
    _emit_status(db, pipeline, PipelineStatus.FAILED)


@shared_task(name="app.orchestrator.pipeline_runner.run_pipeline")
def run_pipeline(pipeline_id: str) -> None:
    _run_pipeline_impl(pipeline_id)

"""Phase 3 SRE intelligence — observability + incident response artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.incident_enrichment import notify_incident_p0, persist_incident_intelligence
from app.utils.chaos_engineering import run_chaos_suite
from app.utils.reliability_registry import resolve_reliability_policy
from app.utils.error_budget import compute_error_budget
from app.utils.incident_commander import run_incident_commander
from app.utils.otel_context import build_otel_trace_context
from app.utils.synthetic_monitoring import run_synthetic_checks
from app.services.slo import compute_pipeline_slo


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def run_phase3_observability(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    recent_runs: list[Any],
    simulated: bool = False,
) -> dict[str, Any]:
    otel = build_otel_trace_context(
        run_id=str(run.id),
        commit=run.commit_id,
        repo=run.repo_full_name,
        environment=settings.deploy_environment,
        service_name=settings.app_name,
    )
    await _save(db, run.id, "otel_trace_context", otel)

    slo = compute_pipeline_slo(recent_runs or [run])
    error_budget = compute_error_budget(slo, target_availability=settings.slo_target_availability)
    await _save(db, run.id, "error_budget_report", error_budget)

    synthetic = await run_synthetic_checks(simulated=simulated or not settings.synthetic_monitoring_live)
    await _save(db, run.id, "synthetic_monitoring_report", synthetic)

    policy = resolve_reliability_policy(run.repo_full_name)
    chaos = run_chaos_suite(
        simulated=policy.get("simulated", True),
        experiment_names=policy.get("experiment_names"),
    )
    await _save(db, run.id, "chaos_report", chaos)

    await db.commit()
    return {
        "otel_trace_context": otel,
        "error_budget_report": error_budget,
        "synthetic_monitoring_report": synthetic,
        "chaos_report": chaos,
    }


async def run_phase3_incident_response(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    metrics: dict[str, Any] | None = None,
    log_excerpt: str = "",
) -> dict[str, Any]:
    commander = run_incident_commander(
        run_id=str(run.id),
        repo=run.repo_full_name,
        branch=run.branch,
        commit=run.commit_id,
        artifacts=artifacts,
        metrics=metrics,
        log_excerpt=log_excerpt,
    )

    await _save(db, run.id, "incident_commander_report", commander)
    await _save(db, run.id, "evidence_graph", commander["evidence_graph"])
    await _save(db, run.id, "rca_report", commander["rca"])
    await _save(db, run.id, "incident_timeline", commander["timeline"])
    await _save(db, run.id, "postmortem_report", commander["postmortem"])
    await _save(db, run.id, "runbook_execution", commander["runbooks"])

    slack_notified = await notify_incident_p0(commander, run)
    await persist_incident_intelligence(
        db,
        run,
        commander,
        slack_notified=slack_notified,
        existing_artifacts=artifacts,
    )
    await db.commit()
    return commander

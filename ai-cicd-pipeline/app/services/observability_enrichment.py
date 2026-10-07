"""Persist observability / AIOps intelligence after deploy observability stage."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.observability_intelligence import build_observability_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_observability_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    historical_synthetic: list[dict[str, Any]] | None = None,
    historical_stress: list[dict[str, Any]] | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("observability_intelligence"):
        return artifacts["observability_intelligence"]

    report = build_observability_intelligence_report(
        deployment_info=artifacts.get("deployment_info"),
        otel_trace_context=artifacts.get("otel_trace_context"),
        synthetic_monitoring_report=artifacts.get("synthetic_monitoring_report"),
        stress_report=artifacts.get("stress_report"),
        error_budget_report=artifacts.get("error_budget_report"),
        service_graph=artifacts.get("service_graph"),
        monitoring_summary=artifacts.get("monitoring_summary"),
        change_risk_report=artifacts.get("change_risk_report"),
        historical_synthetic=historical_synthetic,
        historical_stress=historical_stress,
    )
    report["summary"] = summarize_artifact("observability_intelligence", report)
    await _save(db, run.id, "observability_intelligence", report)
    await db.commit()
    return report

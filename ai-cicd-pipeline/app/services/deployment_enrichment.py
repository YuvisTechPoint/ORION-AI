"""Persist deployment intelligence after deploy stage."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.deployment_intelligence import build_deployment_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_deployment_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("deployment_intelligence"):
        return artifacts["deployment_intelligence"]

    report = build_deployment_intelligence_report(
        deployment_info=artifacts.get("deployment_info"),
        progressive_delivery=artifacts.get("progressive_delivery"),
        error_budget_report=artifacts.get("error_budget_report"),
        stress_report=artifacts.get("stress_report"),
        change_risk_report=artifacts.get("change_risk_report"),
        rollback_intelligence=artifacts.get("rollback_intelligence"),
    )
    report["summary"] = summarize_artifact("deployment_intelligence", report)
    await _save(db, run.id, "deployment_intelligence", report)
    await db.commit()
    return report

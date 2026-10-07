"""Persist multimodal intelligence when a run has on-demand multimodal artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.multimodal_intelligence import build_multimodal_intelligence_report, collect_multimodal_artifacts


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_multimodal_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    route_hint: dict[str, Any] | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("multimodal_intelligence"):
        return artifacts["multimodal_intelligence"]

    collected = collect_multimodal_artifacts(artifacts)
    if not collected and not route_hint:
        return {
            "gate_verdict": "warn",
            "summary": "No multimodal artifacts on this run.",
            "agents_present": 0,
        }

    report = build_multimodal_intelligence_report(artifacts=artifacts, route_hint=route_hint)
    report["summary"] = summarize_artifact("multimodal_intelligence", report)
    await _save(db, run.id, "multimodal_intelligence", report)
    await db.commit()
    return report

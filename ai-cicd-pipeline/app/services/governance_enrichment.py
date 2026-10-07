"""Persist AI governance intelligence artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.ai_governance_intelligence import build_ai_governance_intelligence_report
from app.utils.artifact_summaries import summarize_artifact


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_ai_governance_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    agent_names: list[str] | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("ai_governance_intelligence"):
        return artifacts["ai_governance_intelligence"]

    report = build_ai_governance_intelligence_report(
        artifacts=artifacts,
        run_id=str(run.id),
        agent_names=agent_names,
    )
    report["summary"] = summarize_artifact("ai_governance_intelligence", report)
    await _save(db, run.id, "ai_governance_intelligence", report)
    await db.commit()
    return report

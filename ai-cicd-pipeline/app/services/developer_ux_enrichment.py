"""Persist developer UX intelligence artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.developer_ux_intelligence import build_developer_ux_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_developer_ux_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("developer_ux_intelligence"):
        return artifacts["developer_ux_intelligence"]

    report = build_developer_ux_intelligence_report(
        run_id=str(run.id),
        repo=run.repo_full_name,
        artifacts=artifacts,
    )
    report["summary"] = summarize_artifact("developer_ux_intelligence", report)
    await _save(db, run.id, "developer_ux_intelligence", report)
    await db.commit()
    return report

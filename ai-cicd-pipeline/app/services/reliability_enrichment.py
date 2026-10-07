"""Persist reliability intelligence artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.slo import compute_pipeline_slo
from app.utils.artifact_summaries import summarize_artifact
from app.utils.reliability_intelligence import build_reliability_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def _load_recent_runs(db: AsyncSession, *, repo: str = "", limit: int = 20) -> list[PipelineRun]:
    query = select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit)
    if repo:
        query = query.where(PipelineRun.repo_full_name == repo)
    return list((await db.execute(query)).scalars().all())


async def persist_reliability_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("reliability_intelligence"):
        return artifacts["reliability_intelligence"]

    recent = await _load_recent_runs(db, repo=run.repo_full_name)
    slo = compute_pipeline_slo(recent or [run])

    report = await build_reliability_intelligence_report(
        run_id=str(run.id),
        repo=run.repo_full_name,
        artifacts=artifacts,
        slo=slo,
    )
    report["summary"] = summarize_artifact("reliability_intelligence", report)
    await _save(db, run.id, "reliability_intelligence", report)
    await db.commit()
    return report

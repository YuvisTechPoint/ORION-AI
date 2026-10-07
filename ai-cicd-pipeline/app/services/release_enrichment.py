"""Persist release intelligence artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.release_intelligence import build_release_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def _load_fleet_runs(db: AsyncSession, *, repo: str = "", limit: int = 30) -> list[PipelineRun]:
    query = select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit)
    if repo:
        query = query.where(PipelineRun.repo_full_name == repo)
    return list((await db.execute(query)).scalars().all())


async def persist_release_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    deploy_mode: str,
    environment: str,
    fleet_runs: list[PipelineRun] | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("release_intelligence"):
        return artifacts["release_intelligence"]

    if fleet_runs is None:
        fleet_runs = await _load_fleet_runs(db, repo=run.repo_full_name)

    report = build_release_intelligence_report(
        run_id=str(run.id),
        repo=run.repo_full_name,
        branch=run.branch,
        commit=run.commit_id,
        environment=environment,
        deploy_mode=deploy_mode,
        artifacts=artifacts,
        fleet_runs=fleet_runs,
    )
    report["summary"] = summarize_artifact("release_intelligence", report)
    await _save(db, run.id, "release_intelligence", report)
    await db.commit()
    return report

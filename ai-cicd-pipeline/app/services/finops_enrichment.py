"""Persist FinOps intelligence artifacts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.finops_intelligence import build_finops_intelligence_report


def _duration_seconds(run: PipelineRun) -> float | None:
    created = run.created_at
    completed = run.completed_at
    if created is None:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    end = completed or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0.0, (end - created).total_seconds())


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def _load_fleet_costs(db: AsyncSession, *, repo: str = "", limit: int = 30) -> list[dict[str, Any]]:
    query = select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit)
    if repo:
        query = query.where(PipelineRun.repo_full_name == repo)
    runs = (await db.execute(query)).scalars().all()
    if not runs:
        return []
    rows = (
        await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id.in_([r.id for r in runs])))
    ).scalars().all()
    by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        rid = str(row.pipeline_run_id)
        by_run.setdefault(rid, {})[row.artifact_type] = row.content or {}
    costs: list[dict[str, Any]] = []
    for run in runs:
        arts = by_run.get(str(run.id)) or {}
        finops = arts.get("finops_intelligence") or {}
        cost = finops.get("cost_report") or arts.get("cost_report")
        if cost:
            costs.append({**cost, "repository": run.repo_full_name, "run_id": str(run.id)})
    return costs


async def persist_finops_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    fleet_costs: list[dict[str, Any]] | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("finops_intelligence"):
        return artifacts["finops_intelligence"]

    if fleet_costs is None:
        fleet_costs = await _load_fleet_costs(db, repo=run.repo_full_name)

    report = build_finops_intelligence_report(
        run_id=str(run.id),
        repo=run.repo_full_name,
        duration_seconds=_duration_seconds(run),
        artifacts=artifacts,
        fleet_costs=fleet_costs,
    )
    report["summary"] = summarize_artifact("finops_intelligence", report)
    await _save(db, run.id, "finops_intelligence", report)
    await db.commit()
    return report

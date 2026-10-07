"""Persist agent mesh snapshot and intelligence artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.agent_mesh_intelligence import build_agent_mesh_intelligence_report
from app.utils.agent_mesh_registry import build_agent_mesh_registry
from app.utils.agent_mesh_topology import build_mesh_topology
from app.utils.artifact_summaries import summarize_artifact


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_agent_mesh_snapshot(
    db: AsyncSession,
    run: PipelineRun,
    *,
    skip_if_present: bool = False,
    existing: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    existing = existing or {}
    if skip_if_present and existing.get("agent_mesh_snapshot"):
        return existing["agent_mesh_snapshot"]

    registry = build_agent_mesh_registry()
    topology = build_mesh_topology()
    snapshot = {
        "registry": registry,
        "topology": topology,
        "run_id": str(run.id),
        "repository": run.repo_full_name,
        "summary": summarize_artifact("agent_mesh_snapshot", {"registry": registry}),
    }
    await _save(db, run.id, "agent_mesh_snapshot", snapshot)
    await db.commit()
    return snapshot


async def persist_agent_mesh_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    intent: str = "",
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("agent_mesh_intelligence"):
        return artifacts["agent_mesh_intelligence"]

    report = build_agent_mesh_intelligence_report(
        artifacts=artifacts,
        intent=intent,
        run_status=str(run.status or ""),
    )
    report["summary"] = summarize_artifact("agent_mesh_intelligence", report)
    await _save(db, run.id, "agent_mesh_intelligence", report)
    await db.commit()
    return report

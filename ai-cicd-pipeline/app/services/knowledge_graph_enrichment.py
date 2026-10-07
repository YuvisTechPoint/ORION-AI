"""Persist knowledge graph intelligence artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.knowledge_graph_intelligence import build_knowledge_graph_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_knowledge_graph_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("knowledge_graph_intelligence"):
        return artifacts["knowledge_graph_intelligence"]

    report = build_knowledge_graph_intelligence_report(
        run_id=str(run.id),
        repo=run.repo_full_name,
        commit=run.commit_id,
        branch=run.branch,
        artifacts=artifacts,
    )
    report["summary"] = summarize_artifact("knowledge_graph_intelligence", report)
    await _save(db, run.id, "knowledge_graph_intelligence", report)
    await db.commit()
    return report

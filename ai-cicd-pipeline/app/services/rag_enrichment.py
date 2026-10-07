"""Persist RAG intelligence artifacts and optional repo index metadata."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.hybrid_retriever import Retriever, index_repository
from app.services.memory_store import MemoryStore, build_memory_snapshot
from app.utils.artifact_summaries import summarize_artifact
from app.utils.devops_rag import build_rag_context
from app.utils.rag_intelligence import build_rag_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_rag_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    memory_store: MemoryStore | None = None,
    retriever: Retriever | None = None,
    repo_path: str | None = None,
    query: str = "",
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("rag_intelligence"):
        return artifacts["rag_intelligence"]

    index_meta = None
    if retriever is not None and repo_path and settings.rag_index_enabled:
        index_meta = index_repository(retriever, repo_path)

    report = build_rag_intelligence_report(
        query=query,
        artifacts=artifacts,
        memory_store=memory_store,
        retriever=retriever,
        scope_id=str(run.id),
    )
    if index_meta:
        report["index"] = {**(report.get("index") or {}), **index_meta}

    report["summary"] = summarize_artifact("rag_intelligence", report)
    await _save(db, run.id, "rag_intelligence", report)

    rag_ctx = build_rag_context(
        artifacts,
        max_chunks=settings.devops_rag_max_chunks,
        file_chunks=retriever.retrieve(query, top_k=settings.devops_rag_max_chunks) if retriever and query else None,
    )
    rag_ctx["summary"] = summarize_artifact("devops_rag_context", rag_ctx)
    await _save(db, run.id, "devops_rag_context", rag_ctx)

    if memory_store is not None and settings.agent_memory_enabled:
        snapshot = build_memory_snapshot(
            memory_store,
            scope_id=str(run.id),
            agents=["CodeAnalysisAgent", "SecurityAgent", "QAAgent", "ApprovalAgent"],
        )
        snapshot["summary"] = summarize_artifact("agent_memory_snapshot", snapshot)
        await _save(db, run.id, "agent_memory_snapshot", snapshot)

    await db.commit()
    return report

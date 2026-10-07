"""RAG intelligence — unified DevOps RAG + memory + file retrieval report."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.hybrid_retriever import Retriever, build_retriever
from app.services.memory_store import MemoryStore, build_memory_snapshot
from app.utils.devops_rag import build_rag_context, query_devops_rag


_PIPELINE_AGENTS = (
    "CodeAnalysisAgent",
    "SecurityAgent",
    "QAAgent",
    "StressTestAgent",
    "ApprovalAgent",
    "DeploymentAgent",
    "MonitoringAgent",
)


def build_rag_intelligence_report(
    *,
    query: str = "",
    artifacts: dict[str, dict[str, Any]],
    memory_store: MemoryStore | None = None,
    retriever: Retriever | None = None,
    scope_id: str = "",
    max_chunks: int | None = None,
) -> dict[str, Any]:
    max_chunks = max_chunks or settings.devops_rag_max_chunks
    file_chunks: list[dict[str, Any]] = []
    if retriever is not None and query.strip():
        file_chunks = retriever.retrieve(query, top_k=min(5, max_chunks))

    memory_context: list[dict[str, Any]] = []
    memory_snapshot: dict[str, Any] | None = None
    if memory_store is not None and scope_id:
        memory_snapshot = build_memory_snapshot(
            memory_store,
            scope_id=scope_id,
            agents=list(_PIPELINE_AGENTS),
            limit=settings.agent_memory_context_limit,
        )
        for entry in memory_snapshot.get("entries") or []:
            latest = entry.get("latest") or {}
            resp = latest.get("response_payload") or {}
            if isinstance(resp, dict) and resp:
                memory_context.append(
                    {
                        "agent_name": entry.get("agent_name"),
                        "excerpt": str(resp.get("summary") or resp)[:300],
                        "source": "agent_memory",
                    }
                )

    rag = query_devops_rag(
        query,
        artifacts,
        max_chunks=max_chunks,
        file_chunks=file_chunks,
        memory_context=memory_context,
    )

    index_stats = {
        "retriever_backend": settings.retriever_backend,
        "chunks_indexed": retriever.chunk_count() if retriever is not None else 0,
        "file_hits": len(file_chunks),
    }

    report: dict[str, Any] = {
        "query": query,
        "rag": rag,
        "answer": rag.get("answer"),
        "grounded": rag.get("grounded"),
        "chunk_count": rag.get("chunk_count", 0),
        "citations": [c.get("citation") for c in rag.get("chunks") or [] if c.get("citation")],
        "memory_snapshot": memory_snapshot,
        "index": index_stats,
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"RAG intel: {rag.get('chunk_count', 0)} evidence chunk(s), "
        f"{len(file_chunks)} file hit(s), memory={'on' if memory_snapshot else 'off'}."
    )
    return report

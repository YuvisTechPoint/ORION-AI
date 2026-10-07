"""DevOps RAG — evidence-backed retrieval over pipeline artifacts and repo chunks."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

_CITABLE_ARTIFACTS = (
    "change_risk_report",
    "repository_intelligence",
    "service_catalog",
    "service_catalog_intelligence",
    "service_graph",
    "security_scan",
    "supply_chain_report",
    "qa_report",
    "test_intelligence",
    "stress_report",
    "approval",
    "deployment_info",
    "cloud_intelligence",
    "incident_commander_report",
    "rca_report",
    "postmortem_report",
    "policy_evaluation",
    "compliance_report",
    "runbook_execution",
    "monitoring_summary",
    "monitoring_alert",
    "multimodal_intelligence",
    "release_passport",
    "release_intelligence",
    "knowledge_graph_intelligence",
    "autopilot_intelligence",
    "unified_risk_intelligence",
    "fix_loop_report",
    "patch_confidence_report",
)


def _chunk_text(artifact_type: str, content: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("summary", "reasoning", "root_cause", "primary_hypothesis", "verdict", "decision", "answer"):
        val = content.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
        elif isinstance(val, dict):
            parts.append(str(val.get("cause") or val))
    if artifact_type == "rca_report":
        for h in content.get("hypotheses") or []:
            if isinstance(h, dict) and h.get("cause"):
                parts.append(str(h["cause"]))
    if artifact_type == "knowledge_graph_intelligence":
        graph = content.get("graph") or {}
        parts.append(f"nodes={graph.get('node_count')} edges={graph.get('edge_count')}")
        cov = content.get("coverage") or {}
        parts.append(f"coverage={cov.get('coverage_percent')}%")
    if artifact_type == "unified_risk_intelligence":
        parts.append(f"unified_score={content.get('unified_score')} level={content.get('risk_level')}")
        driver = content.get("primary_driver")
        if driver:
            parts.append(f"primary_driver={driver}")
    if artifact_type == "service_catalog":
        for svc in (content.get("services") or [])[:5]:
            if isinstance(svc, dict):
                parts.append(f"{svc.get('name')}: {svc.get('tier')} owner={svc.get('owner')}")
    return " ".join(parts)


def _score_text(query: str, text: str) -> float:
    query_lower = query.lower()
    text_lower = text.lower()
    tokens = [t for t in query_lower.split() if len(t) > 2]
    if not tokens and not query_lower.strip():
        return 1.0
    token_score = sum(2 for tok in tokens if tok in text_lower)
    fuzzy = SequenceMatcher(None, query_lower[:400], text_lower[:800]).ratio() * 5
    return token_score + fuzzy


def query_devops_rag(
    query: str,
    artifacts: dict[str, dict[str, Any]],
    *,
    max_chunks: int = 8,
    file_chunks: list[dict[str, Any]] | None = None,
    memory_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []

    for artifact_type in _CITABLE_ARTIFACTS:
        content = artifacts.get(artifact_type)
        if not isinstance(content, dict):
            continue
        excerpt = _chunk_text(artifact_type, content)
        if not excerpt:
            continue
        score = _score_text(query, excerpt)
        if score > 0 or not query.strip():
            hits.append(
                {
                    "artifact_type": artifact_type,
                    "score": round(score, 2) if query.strip() else 1.0,
                    "excerpt": excerpt[:400],
                    "citation": f"artifact:{artifact_type}",
                    "source": "artifact",
                }
            )

    for chunk in file_chunks or []:
        excerpt = chunk.get("content") or ""
        path = chunk.get("path") or "file"
        score = float(chunk.get("score") or _score_text(query, f"{path}\n{excerpt}"))
        if score > 0 or not query.strip():
            hits.append(
                {
                    "artifact_type": "repo_file",
                    "path": path,
                    "score": round(score, 2),
                    "excerpt": excerpt[:400],
                    "citation": f"file:{path}",
                    "source": "file",
                }
            )

    for mem in memory_context or []:
        excerpt = str(mem.get("excerpt") or "")
        agent = mem.get("agent_name") or "agent"
        score = _score_text(query, excerpt)
        if score > 0 or not query.strip():
            hits.append(
                {
                    "artifact_type": "agent_memory",
                    "agent_name": agent,
                    "score": round(score, 2) if query.strip() else 0.5,
                    "excerpt": excerpt[:400],
                    "citation": f"memory:{agent}",
                    "source": "memory",
                }
            )

    hits.sort(key=lambda h: h["score"], reverse=True)
    hits = hits[:max_chunks]

    answer = "No matching evidence in pipeline artifacts."
    if hits:
        top = hits[0]
        answer = f"Based on {top['citation']}: {top['excerpt'][:280]}"

    sources = sorted({h.get("source") for h in hits if h.get("source")})
    return {
        "query": query,
        "chunks": hits,
        "chunk_count": len(hits),
        "answer": answer,
        "grounded": len(hits) > 0,
        "sources": sources,
        "summary": f"DevOps RAG: {len(hits)} evidence chunk(s) from {', '.join(sources) or 'none'}.",
    }


def build_rag_context(
    artifacts: dict[str, dict[str, Any]],
    *,
    max_chunks: int = 8,
    file_chunks: list[dict[str, Any]] | None = None,
    memory_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return query_devops_rag("", artifacts, max_chunks=max_chunks, file_chunks=file_chunks, memory_context=memory_context)

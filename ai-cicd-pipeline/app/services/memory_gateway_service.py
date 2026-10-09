"""ORION Memory Gateway service — ORION-ARCH-001 §6."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import settings

from shared.memory_gateway.gateway import MemoryGateway, MemoryGatewayConfig
from shared.memory_gateway.models import MemoryLayer, MemoryReadRequest, MemoryWriteRequest, TrustLevel


@lru_cache
def get_memory_gateway() -> MemoryGateway:
    cfg = MemoryGatewayConfig(
        enabled=settings.memory_gateway_enabled,
        backend=settings.memory_backend,
        sqlite_path=settings.memory_sqlite_path,
        postgres_url=settings.memory_postgres_url,
        embedding_dims=settings.memory_embedding_dims,
        min_confidence=settings.memory_min_confidence,
        quarantine_enabled=settings.memory_quarantine_enabled,
        context_token_budget=settings.memory_context_token_budget,
        episodic_ttl_days=settings.memory_ttl_days_episodic,
    )
    return MemoryGateway(cfg, fallback_database_url=settings.sync_database_url)


def tenant_from_repo(repo_full_name: str) -> str:
    return (repo_full_name or "local/default").split("/")[0]


def namespace_for_repo(repo_full_name: str, layer: str, kind: str) -> str:
    parts = (repo_full_name or "local/default").split("/")
    org = parts[0] if parts else "local"
    repo = parts[1] if len(parts) > 1 else "default"
    layer_slug = (layer or "l2").lower()
    return f"{org}/platform/{repo}/{repo}/{layer_slug}/episodic/{kind}"


def namespace_prefix_for_repo(repo_full_name: str) -> str:
    parts = (repo_full_name or "local/default").split("/")
    org = parts[0] if parts else "local"
    repo = parts[1] if len(parts) > 1 else "default"
    return f"{org}/platform/{repo}/{repo}/"


async def extract_pipeline_episodic_memory(
    *,
    run_id: str,
    repo_full_name: str,
    status: str,
    artifacts: dict[str, dict[str, Any]],
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Write L2 episodic summary on terminal pipeline status."""
    gateway = get_memory_gateway()
    if not gateway.config.enabled:
        return {"written": False, "reason": "memory_disabled"}

    summary_parts = [f"Pipeline {run_id[:8]} terminal status={status}"]
    for key in ("change_risk_report", "security_scan", "approval", "deployment_info"):
        art = artifacts.get(key) or {}
        if art.get("summary"):
            summary_parts.append(f"{key}: {art['summary']}")

    body = "\n".join(summary_parts)
    req = MemoryWriteRequest(
        tenant_id=tenant_from_repo(repo_full_name),
        namespace=namespace_for_repo(repo_full_name, MemoryLayer.L2_EPISODIC.value, "pipeline"),
        layer=MemoryLayer.L2_EPISODIC.value,
        kind="pipeline_summary",
        title=f"Pipeline {status} — {repo_full_name}",
        body=body,
        structured={"run_id": run_id, "status": status, "repo": repo_full_name},
        source_refs=[{"artifact_type": k, "run_id": run_id} for k in artifacts.keys()],
        provenance={"agent": "MemoryExtractor", "version": "1.0", "source": "pipeline_terminal"},
        trust_level=TrustLevel.DERIVED.value,
        confidence=0.85,
        actor="memory_extractor",
        purpose="pipeline_terminal",
        correlation_id=correlation_id,
        trace_id=trace_id,
    )
    return gateway.write(req)


def read_memory_context(
    *,
    tenant_id: str,
    repo_full_name: str,
    query: str = "",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    gateway = get_memory_gateway()
    prefix = namespace_prefix_for_repo(repo_full_name)
    req = MemoryReadRequest(
        tenant_id=tenant_id,
        namespace_prefix=prefix,
        query=query,
        layers=[MemoryLayer.L2_EPISODIC.value, MemoryLayer.L3_SEMANTIC.value],
        correlation_id=correlation_id,
        actor="agent_runtime",
        purpose="context_injection",
    )
    return gateway.read(req)

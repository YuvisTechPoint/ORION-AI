"""Canonical pipeline episodic memory — ORION-ARCH-001 §6."""

from __future__ import annotations

import os
from typing import Any

from models.schemas import PipelineState
from services.memory_gateway_client import write_memory_record

from shared.memory_gateway.models import MemoryLayer, MemoryWriteRequest, TrustLevel


def _enabled() -> bool:
    return os.getenv("MEMORY_GATEWAY_ENABLED", "true").lower() in {"1", "true", "yes"}


def tenant_from_repo(repo_full_name: str) -> str:
    return (repo_full_name or "local/default").split("/")[0]


def namespace_for_repo(repo_full_name: str, kind: str = "pipeline") -> str:
    parts = (repo_full_name or "local/default").split("/")
    org = parts[0] if parts else "local"
    repo = parts[1] if len(parts) > 1 else "default"
    return f"{org}/platform/{repo}/{repo}/l2/episodic/{kind}"


def extract_canonical_episodic_memory(state: PipelineState) -> dict[str, Any]:
    """Write L2 episodic summary when canonical pipeline reaches a terminal status."""
    if not _enabled():
        return {"written": False, "reason": "memory_disabled"}

    artifacts = state.artifacts or {}
    submit = artifacts.get("submit_request") or {}
    repo_name = state.repo_name or submit.get("repo_name") or "local/default"
    repo_full = submit.get("repo_full_name") or repo_name
    if "/" not in repo_full:
        repo_full = f"local/{repo_full}"

    summary_parts = [f"Canonical pipeline {state.pipeline_id[:8]} terminal status={state.status}"]
    for key in ("code_analysis", "security", "qa", "stress", "approval"):
        art = artifacts.get(key) or {}
        if isinstance(art, dict):
            if art.get("summary"):
                summary_parts.append(f"{key}: {art['summary']}")
            elif art.get("verdict"):
                summary_parts.append(f"{key}: verdict={art['verdict']}")

    body = "\n".join(summary_parts)
    req = MemoryWriteRequest(
        tenant_id=tenant_from_repo(repo_full),
        namespace=namespace_for_repo(repo_full),
        layer=MemoryLayer.L2_EPISODIC.value,
        kind="pipeline_summary",
        title=f"Pipeline {state.status} — {repo_full}",
        body=body,
        structured={
            "pipeline_id": state.pipeline_id,
            "status": state.status,
            "repo": repo_full,
            "stage": state.current_stage,
        },
        source_refs=[{"artifact_type": k, "pipeline_id": state.pipeline_id} for k in artifacts.keys()],
        provenance={"agent": "CanonicalMemoryExtractor", "version": "1.0", "source": "pipeline_terminal"},
        trust_level=TrustLevel.DERIVED.value,
        confidence=0.85,
        actor="memory_extractor",
        purpose="pipeline_terminal",
        correlation_id=state.correlation_id,
        trace_id=state.trace_id,
    )
    return write_memory_record(req)

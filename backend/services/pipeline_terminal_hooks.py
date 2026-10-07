"""Terminal pipeline hooks — memory gateway + platform events (canonical)."""

from __future__ import annotations

import logging
from typing import Any

from models.schemas import PipelineState
from services.memory_extractor import extract_canonical_episodic_memory, tenant_from_repo
from services.platform_events import publish_platform_event

LOGGER = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset(
    {"completed", "blocked", "blocked_with_prs_sent", "failed", "cancelled"}
)


def _already_ran(state: PipelineState) -> bool:
    marker = state.artifacts.get("_terminal_hooks")
    return isinstance(marker, dict) and marker.get("completed") is True


def _mark_ran(state: PipelineState) -> None:
    state.artifacts["_terminal_hooks"] = {"completed": True}


def publish_pipeline_started(state: PipelineState, *, repo_full_name: str) -> None:
    cid = state.correlation_id or state.pipeline_id
    try:
        publish_platform_event(
            "pipeline.started",
            correlation_id=cid,
            tenant_id=tenant_from_repo(repo_full_name),
            trace_id=state.trace_id or cid,
            payload={
                "pipeline_id": state.pipeline_id,
                "repo": repo_full_name,
                "stack": "canonical",
            },
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("pipeline.started publish failed: %s", exc)


def run_terminal_hooks(state: PipelineState, *, repo_full_name: str | None = None) -> dict[str, Any]:
    """Idempotent terminal hook — episodic memory + pipeline.completed event."""
    if state.status not in TERMINAL_STATUSES or _already_ran(state):
        return {"skipped": True, "status": state.status}

    submit = state.artifacts.get("submit_request") or {}
    repo = repo_full_name or submit.get("repo_full_name") or state.repo_name or "local/default"
    if "/" not in repo:
        repo = f"local/{repo}"

    cid = state.correlation_id or state.pipeline_id
    results: dict[str, Any] = {"status": state.status}

    try:
        results["memory"] = extract_canonical_episodic_memory(state)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("canonical episodic memory failed: %s", exc)
        results["memory_error"] = str(exc)

    try:
        results["event_id"] = publish_platform_event(
            "pipeline.completed",
            correlation_id=cid,
            tenant_id=tenant_from_repo(repo),
            trace_id=state.trace_id or cid,
            payload={
                "pipeline_id": state.pipeline_id,
                "status": state.status,
                "repo": repo,
                "stack": "canonical",
            },
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("pipeline.completed publish failed: %s", exc)
        results["event_error"] = str(exc)

    _mark_ran(state)
    return results

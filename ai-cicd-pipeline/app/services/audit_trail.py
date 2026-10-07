"""Structured operator audit trail persisted as pipeline artifacts."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.pipeline_artifact import PipelineArtifact
from app.utils.artifact_summaries import summarize_artifact


def _actor_label(user: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not user:
        return "system", ["system"]
    if user.get("api_key_auth"):
        roles = user.get("roles") or ["api-key"]
        return str(user.get("username") or "api-key"), list(roles)
    username = str(user.get("username") or user.get("name") or "anonymous")
    roles = user.get("roles") or (["operator"] if username != "anonymous" else ["anonymous"])
    return username, list(roles)


async def append_audit_event(
    db: AsyncSession,
    run_id: UUID,
    *,
    action: str,
    user: dict[str, Any] | None,
    outcome: str,
    details: dict[str, Any] | None = None,
) -> None:
    actor, roles = _actor_label(user)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "actor": actor,
        "roles": roles,
        "outcome": outcome,
        "details": details or {},
    }
    row = (
        await db.execute(
            select(PipelineArtifact)
            .where(
                PipelineArtifact.pipeline_run_id == run_id,
                PipelineArtifact.artifact_type == "audit_trail",
            )
            .order_by(PipelineArtifact.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        content = {"events": [event]}
        content["summary"] = summarize_artifact("audit_trail", content)
        db.add(
            PipelineArtifact(
                pipeline_run_id=run_id,
                artifact_type="audit_trail",
                content=content,
            )
        )
    else:
        content = copy.deepcopy(row.content or {})
        events = content.get("events")
        if not isinstance(events, list):
            events = []
        events.append(event)
        content["events"] = events[-200:]
        content["summary"] = summarize_artifact("audit_trail", content)
        row.content = content
        flag_modified(row, "content")
    await db.commit()


async def list_audit_events(db: AsyncSession, run_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
    row = (
        await db.execute(
            select(PipelineArtifact)
            .where(
                PipelineArtifact.pipeline_run_id == run_id,
                PipelineArtifact.artifact_type == "audit_trail",
            )
            .order_by(PipelineArtifact.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return []
    events = (row.content or {}).get("events") or []
    if not isinstance(events, list):
        return []
    return [e for e in events if isinstance(e, dict)][-limit:]

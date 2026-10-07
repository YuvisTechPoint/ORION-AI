"""Operator audit trail stored on pipeline metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import PipelineRun


def _actor(user: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not user:
        return "system", ["system"]
    roles = user.get("roles") or ["operator"]
    name = str(user.get("username") or user.get("user_id") or "api-user")
    return name, list(roles)


def append_audit_sync(
    db: Session,
    pipeline: PipelineRun,
    *,
    action: str,
    user: dict[str, Any] | None,
    outcome: str,
    details: dict[str, Any] | None = None,
) -> None:
    actor, roles = _actor(user)
    meta = dict(pipeline.metadata_json or {})
    trail = meta.get("audit_trail")
    if not isinstance(trail, list):
        trail = []
    trail.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "actor": actor,
            "roles": roles,
            "outcome": outcome,
            "details": details or {},
        }
    )
    meta["audit_trail"] = trail[-200:]
    pipeline.metadata_json = meta
    db.commit()


async def append_audit_async(
    db: AsyncSession,
    pipeline_id: UUID,
    *,
    action: str,
    user: dict[str, Any] | None,
    outcome: str,
    details: dict[str, Any] | None = None,
) -> None:
    pipeline = await db.get(PipelineRun, pipeline_id)
    if pipeline is None:
        return
    actor, roles = _actor(user)
    meta = dict(pipeline.metadata_json or {})
    trail = meta.get("audit_trail")
    if not isinstance(trail, list):
        trail = []
    trail.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "actor": actor,
            "roles": roles,
            "outcome": outcome,
            "details": details or {},
        }
    )
    meta["audit_trail"] = trail[-200:]
    pipeline.metadata_json = meta
    await db.commit()


def list_audit_events(pipeline: PipelineRun, limit: int = 50) -> list[dict[str, Any]]:
    trail = (pipeline.metadata_json or {}).get("audit_trail") or []
    if not isinstance(trail, list):
        return []
    return [e for e in trail if isinstance(e, dict)][-limit:]

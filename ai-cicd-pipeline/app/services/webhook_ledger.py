"""GitHub webhook delivery idempotency."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook_delivery import WebhookDelivery


async def find_delivery(db: AsyncSession, delivery_id: str) -> WebhookDelivery | None:
    if not delivery_id:
        return None
    return (
        await db.execute(select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id))
    ).scalar_one_or_none()


async def record_delivery(
    db: AsyncSession,
    *,
    delivery_id: str,
    event_type: str,
    repo_full_name: str | None,
    commit_id: str | None,
    pipeline_run_id: UUID | None,
    status: str,
    response_body: dict[str, Any],
) -> WebhookDelivery:
    row = WebhookDelivery(
        delivery_id=delivery_id,
        event_type=event_type,
        repo_full_name=repo_full_name,
        commit_id=commit_id,
        pipeline_run_id=pipeline_run_id,
        status=status,
        response_body=response_body,
    )
    db.add(row)
    await db.commit()
    return row

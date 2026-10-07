"""GitHub webhook delivery idempotency (sync SQLAlchemy)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from models.db_models import WebhookDelivery


def find_delivery(db: Session, delivery_id: str) -> WebhookDelivery | None:
    if not delivery_id:
        return None
    return db.get(WebhookDelivery, delivery_id)


def record_delivery(
    db: Session,
    *,
    delivery_id: str,
    event_type: str,
    repo_full_name: str | None,
    pipeline_id: str | None,
    status: str,
    response_body: dict[str, Any],
) -> WebhookDelivery:
    row = WebhookDelivery(
        delivery_id=delivery_id,
        event_type=event_type,
        repo_full_name=repo_full_name,
        pipeline_id=pipeline_id,
        status=status,
        response_body=json.dumps(response_body),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

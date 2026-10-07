"""Platform event bus API — /api/v2/events."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.routes.auth import optional_auth
from app.services.platform_events import get_platform_event_bus

router = APIRouter(prefix="/events", tags=["events-v2"])


@router.get("/recent")
async def recent_platform_events(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = None,
    _auth: dict = Depends(optional_auth),
) -> dict[str, Any]:
    bus = get_platform_event_bus()
    items = bus.recent(limit=limit, event_type=event_type or None)
    return {"count": len(items), "events": items}

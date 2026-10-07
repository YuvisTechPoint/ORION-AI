"""Fetch recent platform events from ORION event backbone."""

from __future__ import annotations

from typing import Any

from hub.federation.catalog import stack_entries
from hub.federation.client import fetch_json


async def fetch_orion_platform_events(
    *,
    correlation_id: str | None = None,
    limit: int = 30,
    event_type: str | None = None,
) -> dict[str, Any]:
    orion = next((e for e in stack_entries() if e.get("id") == "orion"), None)
    if not orion:
        return {"available": False, "count": 0, "events": []}
    api = (orion.get("api") or "").rstrip("/")
    params: dict[str, Any] = {"limit": limit}
    if event_type:
        params["event_type"] = event_type
    code, body = await fetch_json(
        f"{api}/api/v2/events/recent",
        correlation_id=correlation_id,
        params=params,
    )
    if code != 200 or not isinstance(body, dict):
        return {"available": False, "count": 0, "events": [], "error": f"http_{code}"}
    events = body.get("events") or []
    return {
        "available": True,
        "count": len(events),
        "events": events,
        "source": "orion",
    }

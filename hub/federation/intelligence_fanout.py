"""Fan-out intelligence dashboards from all configured stacks."""

from __future__ import annotations

import asyncio
from typing import Any

from hub.federation.catalog import stack_entries
from hub.federation.client import fetch_json
from hub.federation.models import StackIntelligenceSnapshot


def _blockers_from_dashboard(body: dict[str, Any]) -> list[str]:
    pipelines = body.get("pipelines") or {}
    blockers = pipelines.get("top_blockers") or []
    return [str(b) for b in blockers if b]


def _alerts_from_dashboard(body: dict[str, Any], stack: str) -> list[dict[str, Any]]:
    alerts = body.get("alerts") or []
    out: list[dict[str, Any]] = []
    for alert in alerts:
        if isinstance(alert, dict):
            out.append({**alert, "stack": stack})
        elif alert:
            out.append({"code": str(alert), "stack": stack})
    return out


async def _fetch_stack_intelligence(
    entry: dict[str, Any],
    *,
    correlation_id: str | None,
) -> StackIntelligenceSnapshot:
    sid = str(entry.get("id") or "")
    title = str(entry.get("title") or sid)
    url = (entry.get("intelligence") or "").strip()
    if not url or sid == "hub":
        return StackIntelligenceSnapshot(stack=sid, title=title, available=False, error="no_intelligence_url")

    code, body = await fetch_json(url, correlation_id=correlation_id)
    if code != 200 or not isinstance(body, dict):
        return StackIntelligenceSnapshot(
            stack=sid,  # type: ignore[arg-type]
            title=title,
            available=False,
            error=f"http_{code}",
        )

    pipelines = body.get("pipelines") or {}
    slo = body.get("slo") or {}
    return StackIntelligenceSnapshot(
        stack=sid,  # type: ignore[arg-type]
        title=title,
        available=True,
        pass_rate=pipelines.get("pass_rate"),
        slo=slo if isinstance(slo, dict) else {},
        alerts=_alerts_from_dashboard(body, sid),
        top_blockers=_blockers_from_dashboard(body),
        finops=body.get("finops") if isinstance(body.get("finops"), dict) else {},
        capabilities=body.get("capabilities") if isinstance(body.get("capabilities"), dict) else {},
    )


async def fanout_intelligence(*, correlation_id: str | None = None) -> list[StackIntelligenceSnapshot]:
    entries = [e for e in stack_entries() if e.get("intelligence")]
    if not entries:
        return []
    results = await asyncio.gather(
        *[_fetch_stack_intelligence(entry, correlation_id=correlation_id) for entry in entries]
    )
    return list(results)


async def fetch_orion_fleet(*, correlation_id: str | None = None) -> dict[str, Any]:
    orion = next((e for e in stack_entries() if e.get("id") == "orion"), None)
    if not orion:
        return {}
    api = (orion.get("api") or "").rstrip("/")
    code, body = await fetch_json(f"{api}/api/v1/intelligence/fleet", correlation_id=correlation_id)
    if code == 200 and isinstance(body, dict):
        return body
    return {}


async def fetch_orion_incidents(
    *,
    correlation_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    orion = next((e for e in stack_entries() if e.get("id") == "orion"), None)
    if not orion:
        return []
    api = (orion.get("api") or "").rstrip("/")
    code, body = await fetch_json(
        f"{api}/api/v1/incidents",
        correlation_id=correlation_id,
        params={"limit": limit},
    )
    if code != 200:
        return []
    if isinstance(body, dict):
        items = body.get("incidents") or body.get("items") or []
    elif isinstance(body, list):
        items = body
    else:
        items = []
    return [i for i in items if isinstance(i, dict)]

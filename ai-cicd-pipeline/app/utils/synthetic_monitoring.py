"""Synthetic production monitoring — periodic user-journey health checks."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

_JOURNEYS = (
    {"name": "health", "path": "/health", "method": "GET"},
    {"name": "api_root", "path": "/", "method": "GET"},
)


async def run_synthetic_checks(base_url: str | None = None, *, simulated: bool = False) -> dict[str, Any]:
    base = (base_url or settings.staging_url).rstrip("/")
    results: list[dict[str, Any]] = []

    if simulated:
        for journey in _JOURNEYS:
            results.append(
                {
                    "journey": journey["name"],
                    "passed": True,
                    "status_code": 200,
                    "latency_ms": 12.0,
                    "simulated": True,
                }
            )
        return _summarize(results, simulated=True)

    async with httpx.AsyncClient(timeout=8.0) as client:
        for journey in _JOURNEYS:
            url = f"{base}{journey['path']}"
            started = time.perf_counter()
            try:
                r = await client.request(journey["method"], url)
                latency = round((time.perf_counter() - started) * 1000, 1)
                results.append(
                    {
                        "journey": journey["name"],
                        "passed": r.status_code < 400,
                        "status_code": r.status_code,
                        "latency_ms": latency,
                        "url": url,
                    }
                )
            except httpx.HTTPError as exc:
                results.append(
                    {
                        "journey": journey["name"],
                        "passed": False,
                        "error": str(exc)[:200],
                        "url": url,
                    }
                )

    return _summarize(results, simulated=False)


def _summarize(results: list[dict[str, Any]], *, simulated: bool) -> dict[str, Any]:
    passed = sum(1 for r in results if r.get("passed"))
    return {
        "journeys": results,
        "passed": passed,
        "total": len(results),
        "all_passed": passed == len(results) and len(results) > 0,
        "simulated": simulated,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "summary": f"Synthetic monitoring: {passed}/{len(results)} journeys passed.",
    }

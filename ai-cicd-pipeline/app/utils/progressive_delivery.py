"""Simulated progressive canary rollout with health gates between stages."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from app.config import settings


async def _poll_health(url: str, timeout_s: float = 10.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            return {"status_code": r.status_code, "latency_ms": latency_ms, "healthy": r.status_code == 200}
    except httpx.HTTPError:
        return {"status_code": 0, "latency_ms": 0.0, "healthy": False}


async def run_progressive_delivery(
    *,
    health_url: str,
    simulated: bool = False,
    stages: list[int] | None = None,
    observe_seconds: int = 2,
    strategy: str | None = None,
) -> dict[str, Any]:
    """Canary-style rollout — simulated traffic % with real or simulated health checks."""
    chosen = (strategy or settings.deployment_strategy or "canary").strip().lower()
    if chosen == "blue_green":
        return await run_blue_green_delivery(
            health_url=health_url,
            simulated=simulated,
            observe_seconds=observe_seconds,
        )

    stage_pcts = stages or [int(x) for x in settings.canary_stages.split(",") if x.strip().isdigit()]
    if not stage_pcts:
        stage_pcts = [5, 25, 50, 100]

    timeline: list[dict[str, Any]] = []
    passed = True

    for pct in stage_pcts:
        if simulated:
            metrics = {"status_code": 200, "latency_ms": 15.0, "healthy": True, "simulated": True}
            await asyncio.sleep(min(observe_seconds, 1))
        else:
            await asyncio.sleep(observe_seconds)
            metrics = await _poll_health(health_url)

        entry = {
            "traffic_percent": pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
        }
        timeline.append(entry)
        if not metrics.get("healthy"):
            passed = False
            break
        if metrics.get("latency_ms", 0) > settings.canary_max_p95_ms:
            passed = False
            entry["abort_reason"] = f"p95 proxy latency {metrics['latency_ms']}ms exceeds {settings.canary_max_p95_ms}ms"
            break

    return {
        "strategy": "canary",
        "simulated": simulated,
        "stages_completed": len(timeline),
        "final_traffic_percent": timeline[-1]["traffic_percent"] if timeline else 0,
        "passed": passed,
        "timeline": timeline,
        "summary": (
            f"Progressive delivery {'PASS' if passed else 'ABORTED'} at {timeline[-1]['traffic_percent']}% traffic."
            if timeline
            else "No canary stages executed."
        ),
    }


async def run_blue_green_delivery(
    *,
    health_url: str,
    simulated: bool = False,
    observe_seconds: int = 2,
) -> dict[str, Any]:
    """Blue/green cutover with health gate on the green slot before traffic switch."""
    timeline: list[dict[str, Any]] = []
    passed = True

    phases = [
        ("deploy_green", "green", 0),
        ("warm_green", "green", 0),
        ("cutover", "green", 100),
        ("drain_blue", "blue", 0),
    ]
    for phase, slot, traffic in phases:
        if simulated:
            metrics = {"status_code": 200, "latency_ms": 12.0, "healthy": True, "simulated": True}
            await asyncio.sleep(min(observe_seconds, 1))
        else:
            await asyncio.sleep(observe_seconds)
            metrics = await _poll_health(health_url) if phase in {"warm_green", "cutover"} else {"status_code": 200, "latency_ms": 0, "healthy": True}

        entry = {
            "phase": phase,
            "slot": slot,
            "traffic_percent": traffic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
        }
        timeline.append(entry)
        if phase in {"warm_green", "cutover"} and not metrics.get("healthy"):
            passed = False
            entry["abort_reason"] = "green slot failed health check"
            break
        if phase == "cutover" and metrics.get("latency_ms", 0) > settings.canary_max_p95_ms:
            passed = False
            entry["abort_reason"] = f"latency {metrics['latency_ms']}ms exceeds threshold"
            break

    return {
        "strategy": "blue_green",
        "simulated": simulated,
        "active_slot_before": "blue",
        "active_slot_after": "green" if passed else "blue",
        "stages_completed": len(timeline),
        "final_traffic_percent": 100 if passed else 0,
        "passed": passed,
        "timeline": timeline,
        "summary": (
            f"Blue/green {'PASS — cutover to green' if passed else 'ABORTED — kept blue'}."
        ),
    }


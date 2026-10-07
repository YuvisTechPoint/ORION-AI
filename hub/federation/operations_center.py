"""ORION Operations Center — federated fleet, SLO, incidents, and release overlay."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hub.federation.adapters import TERMINAL_STATUSES, federated_list_pipelines, health_matrix
from hub.federation.intelligence_fanout import (
    fanout_intelligence,
    fetch_orion_fleet,
    fetch_orion_incidents,
)
from hub.federation.models import OperationsCenterReport, StackIntelligenceSnapshot


SUCCESS_STATUSES = frozenset(
    {"deployed", "approved", "monitoring", "completed", "COMPLETED"}
)
BLOCKED_PREFIX = "blocked"


def _is_blocked(status: str) -> bool:
    s = (status or "").lower()
    return s.startswith(BLOCKED_PREFIX) or s in {"blocked", "BLOCKED", "rejected"}


def _aggregate_slo(snapshots: list[StackIntelligenceSnapshot]) -> dict[str, Any]:
    rates: list[float] = []
    for snap in snapshots:
        if snap.pass_rate is not None:
            rates.append(float(snap.pass_rate))
        elif snap.slo.get("success_rate") is not None:
            rates.append(float(snap.slo["success_rate"]))
    if not rates:
        return {"avg_pass_rate": None, "stacks_reporting": 0}
    return {
        "avg_pass_rate": round(sum(rates) / len(rates), 3),
        "stacks_reporting": len(rates),
        "min_pass_rate": round(min(rates), 3),
        "max_pass_rate": round(max(rates), 3),
    }


def _merge_blockers(snapshots: list[StackIntelligenceSnapshot], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for snap in snapshots:
        for blocker in snap.top_blockers:
            key = f"{snap.stack}:{blocker}"
            if key not in seen:
                seen.add(key)
                merged.append(f"[{snap.stack}] {blocker}")
    return merged[:limit]


def _merge_alerts(snapshots: list[StackIntelligenceSnapshot], limit: int = 12) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for snap in snapshots:
        alerts.extend(snap.alerts)
    return alerts[:limit]


def _service_grid(
    health_stacks: list[Any],
    snapshots: list[StackIntelligenceSnapshot],
) -> list[dict[str, Any]]:
    intel_by_stack = {s.stack: s for s in snapshots}
    grid: list[dict[str, Any]] = []
    for row in health_stacks:
        sid = getattr(row, "stack", None) or row.get("stack")
        intel = intel_by_stack.get(sid)
        grid.append(
            {
                "stack": sid,
                "title": getattr(row, "title", None) or row.get("title"),
                "health": getattr(row, "health", None) or row.get("health"),
                "ready": getattr(row, "ready", None) or row.get("ready"),
                "latency_ms": getattr(row, "latency_ms", None) or row.get("latency_ms"),
                "pass_rate": intel.pass_rate if intel else None,
                "alert_count": len(intel.alerts) if intel else 0,
                "intelligence_available": bool(intel and intel.available),
            }
        )
    return grid


async def build_operations_center(*, correlation_id: str | None = None) -> OperationsCenterReport:
    health = await health_matrix(correlation_id=correlation_id)
    pipelines = await federated_list_pipelines(limit=80, correlation_id=correlation_id)
    snapshots = await fanout_intelligence(correlation_id=correlation_id)
    fleet = await fetch_orion_fleet(correlation_id=correlation_id)
    incidents = await fetch_orion_incidents(correlation_id=correlation_id)

    items = pipelines.items
    active = sum(1 for row in items if row.status not in TERMINAL_STATUSES)
    blocked = sum(1 for row in items if _is_blocked(row.status))
    deployed = sum(1 for row in items if row.status in SUCCESS_STATUSES)

    open_incidents = [
        i for i in incidents if str(i.get("status", "")).lower() not in {"resolved", "closed"}
    ]
    canary_active = sum(
        1
        for row in items
        if row.status in {"deploying", "monitoring", "running", "DEPLOYMENT", "MONITORING"}
    )

    slo_summary = _aggregate_slo(snapshots)
    top_blockers = _merge_blockers(snapshots)
    alerts = _merge_alerts(snapshots)
    service_grid = _service_grid(health.stacks, snapshots)

    summary = (
        f"Operations Center: {active} active pipeline(s), {blocked} blocked, "
        f"{len(open_incidents)} open incident(s), "
        f"fleet risk repo={fleet.get('highest_risk_repo') or '—'}."
    )

    return OperationsCenterReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        correlation_id=correlation_id,
        active_pipelines=active,
        blocked_pipelines=blocked,
        deployed_recent=deployed,
        incidents_open=len(open_incidents),
        canary_active=canary_active,
        alerts=alerts,
        top_blockers=top_blockers,
        slo_summary=slo_summary,
        fleet=fleet,
        stack_intelligence=snapshots,
        service_grid=service_grid,
        summary=summary,
    )

"""Incident timeline generation from pipeline artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_incident_timeline(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    meta = artifacts.get("metadata") or {}
    if meta.get("commit"):
        events.append({"ts": "", "event": "Commit ingested", "detail": meta.get("commit", "")[:8]})

    deployment = artifacts.get("deployment_info") or {}
    if deployment.get("deployed_at"):
        events.append({"ts": deployment["deployed_at"], "event": "Deployment completed", "detail": deployment.get("image_tag", "")})

    progressive = artifacts.get("progressive_delivery") or {}
    for stage in progressive.get("timeline") or []:
        events.append(
            {
                "ts": stage.get("timestamp", ""),
                "event": f"Canary {stage.get('traffic_percent')}%",
                "detail": str(stage.get("metrics", {})),
            }
        )

    for alert in _collect_alerts(artifacts):
        events.append(
            {
                "ts": "",
                "event": "Monitoring alert",
                "detail": str((alert.get("assessment") or {}).get("summary", "degraded")),
            }
        )

    rollback = artifacts.get("rollback_intelligence") or {}
    if rollback.get("recommend_rollback"):
        events.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "Rollback recommended",
                "detail": rollback.get("summary", ""),
            }
        )

    return {
        "event_count": len(events),
        "timeline": events,
        "summary": f"Generated timeline with {len(events)} event(s).",
    }


def _collect_alerts(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    alert = artifacts.get("monitoring_alert")
    if isinstance(alert, dict):
        return [alert]
    return []

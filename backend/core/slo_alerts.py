"""SLO breach evaluation for intelligence dashboards and ops alerts."""

from __future__ import annotations

from typing import Any


def evaluate_slo_alerts(
    slo: dict[str, Any],
    *,
    min_success_rate: float = 0.7,
    max_failure_rate: float = 0.25,
    min_runs: int = 3,
) -> list[dict[str, Any]]:
    window = int(slo.get("window_runs") or 0)
    if window < min_runs:
        return []

    alerts: list[dict[str, Any]] = []
    success = float(slo.get("success_rate") or 0)
    failure = float(slo.get("failure_rate") or 0)
    blocked = float(slo.get("blocked_rate") or 0)

    if success < min_success_rate:
        alerts.append(
            {
                "severity": "warning",
                "code": "slo_success_low",
                "message": f"Pipeline success rate {success:.1%} is below target {min_success_rate:.0%}",
            }
        )
    if failure > max_failure_rate:
        alerts.append(
            {
                "severity": "critical",
                "code": "slo_failure_high",
                "message": f"Pipeline failure rate {failure:.1%} exceeds limit {max_failure_rate:.0%}",
            }
        )
    if blocked > 0.4:
        alerts.append(
            {
                "severity": "warning",
                "code": "slo_blocked_high",
                "message": f"Blocked run rate {blocked:.1%} — review gate fusion blockers",
            }
        )
    return alerts

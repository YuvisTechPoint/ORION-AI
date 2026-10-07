"""SLO error budget engine."""

from __future__ import annotations

from typing import Any


def compute_error_budget(
    slo: dict[str, Any],
    *,
    target_availability: float = 0.999,
    window_label: str = "rolling_20_runs",
) -> dict[str, Any]:
    """Translate pipeline SLO success rate into error budget remaining."""
    window = int(slo.get("window_runs") or 0)
    if window == 0:
        return {
            "target_slo": target_availability,
            "current_availability": None,
            "error_budget_remaining_percent": 100.0,
            "budget_exhausted_percent": 0.0,
            "freeze_risky_releases": False,
            "window": window_label,
            "summary": "Insufficient runs to compute error budget.",
        }

    success_rate = float(slo.get("success_rate") or 0)
    # Map pipeline success rate to availability proxy
    current = min(1.0, max(0.0, success_rate))
    allowed_failures = 1.0 - target_availability
    actual_failures = 1.0 - current
    if allowed_failures <= 0:
        remaining = 100.0
    else:
        consumed = min(1.0, actual_failures / allowed_failures)
        remaining = max(0.0, round((1.0 - consumed) * 100, 1))

    exhausted = round(100.0 - remaining, 1)
    freeze = remaining < 20.0

    return {
        "target_slo": target_availability,
        "current_availability": round(current, 4),
        "error_budget_remaining_percent": remaining,
        "budget_exhausted_percent": exhausted,
        "freeze_risky_releases": freeze,
        "window": window_label,
        "pipeline_success_rate": success_rate,
        "summary": (
            f"Error budget {remaining}% remaining — {'freeze risky releases' if freeze else 'releases allowed'}."
        ),
    }

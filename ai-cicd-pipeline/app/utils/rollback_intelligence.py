"""Enhanced rollback decision with baseline comparison and root-cause confidence."""

from __future__ import annotations

from typing import Any


def assess_rollback(
    *,
    metrics: dict[str, Any],
    deployment_info: dict[str, Any] | None = None,
    change_risk: dict[str, Any] | None = None,
    baseline_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deployment_info = deployment_info or {}
    change_risk = change_risk or {}
    baseline = baseline_metrics or {"error_rate": 0.008, "p95_ms": 380}

    error_rate = min(1.0, (metrics.get("error_count", 0) or 0) / max(metrics.get("sample_size", 100), 1))
    p95 = float(metrics.get("response_time_ms") or metrics.get("p95_ms") or 0)
    health_ok = metrics.get("health_status_code") == 200

    baseline_error = float(baseline.get("error_rate", 0.01))
    baseline_p95 = float(baseline.get("p95_ms", 400))

    error_spike = error_rate > max(0.05, baseline_error * 3)
    latency_spike = p95 > max(2000, baseline_p95 * 2)
    confidence = 0.5
    if not health_ok:
        confidence = 0.96
    elif error_spike and latency_spike:
        confidence = 0.92
    elif error_spike or latency_spike:
        confidence = 0.78

    if change_risk.get("final_risk", 0) >= 60:
        confidence = min(0.99, confidence + 0.05)

    recommend = confidence >= 0.75 and (not health_ok or error_spike or latency_spike)

    return {
        "recommend_rollback": recommend,
        "rollback_confidence": round(confidence, 2),
        "metrics": {
            "error_rate": round(error_rate, 4),
            "p95_ms": p95,
            "health_ok": health_ok,
        },
        "baseline": baseline,
        "likely_commit": deployment_info.get("commit") or deployment_info.get("image_tag"),
        "summary": (
            f"Rollback confidence {round(confidence * 100)}% — {'ROLLBACK' if recommend else 'MONITOR'}."
        ),
    }

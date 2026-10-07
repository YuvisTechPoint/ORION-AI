"""Performance intelligence — baseline comparison, profiles, and regression gates."""

from __future__ import annotations

import statistics
from typing import Any

from app.config import settings

STRESS_PROFILES: dict[str, dict[str, Any]] = {
    "smoke": {
        "label": "Smoke",
        "users": 25,
        "spawn_rate": 5,
        "duration_seconds": 20,
        "description": "Quick health validation under light load.",
    },
    "standard": {
        "label": "Standard",
        "users": None,
        "spawn_rate": None,
        "duration_seconds": None,
        "description": "Default pipeline load (STRESS_TEST_* settings).",
    },
    "spike": {
        "label": "Spike",
        "users": 2500,
        "spawn_rate": 250,
        "duration_seconds": 45,
        "description": "Burst traffic to expose saturation and autoscaling gaps.",
    },
    "soak": {
        "label": "Soak",
        "users": 150,
        "spawn_rate": 5,
        "duration_seconds": 300,
        "description": "Sustained moderate load to surface memory leaks and connection pool exhaustion.",
    },
}


def resolve_stress_profile(profile: str | None = None) -> dict[str, Any]:
    name = (profile or settings.stress_test_profile or "standard").strip().lower()
    base = dict(STRESS_PROFILES.get(name, STRESS_PROFILES["standard"]))
    base["name"] = name
    if name == "standard" or base.get("users") is None:
        base["users"] = settings.stress_test_users
        base["spawn_rate"] = settings.stress_test_spawn_rate
        base["duration_seconds"] = settings.stress_test_duration
    return base


def _metric_values(reports: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for report in reports:
        val = report.get(key)
        if val is None and isinstance(report.get("overall"), dict):
            mapping = {"p95_ms": "p95_ms", "error_rate_pct": "failure_rate_pct", "avg_ms": "avg_response_ms"}
            val = report["overall"].get(mapping.get(key, key))
        if val is not None:
            try:
                out.append(float(val))
            except (TypeError, ValueError):
                continue
    return out


def compare_to_baseline(
    current: dict[str, Any],
    historical: list[dict[str, Any]],
    *,
    stored_baseline: dict[str, Any] | None = None,
    max_p95_regression_pct: float | None = None,
    max_p95_regression_ms: float | None = None,
    max_error_rate_delta: float | None = None,
) -> dict[str, Any]:
    max_p95_regression_pct = (
        settings.performance_p95_regression_percent if max_p95_regression_pct is None else max_p95_regression_pct
    )
    max_p95_regression_ms = (
        settings.performance_p95_regression_ms if max_p95_regression_ms is None else max_p95_regression_ms
    )
    max_error_rate_delta = (
        settings.performance_error_rate_delta_percent if max_error_rate_delta is None else max_error_rate_delta
    )

    vals = _metric_values([current], "p95_ms")
    current_p95 = float(current.get("p95_ms") if current.get("p95_ms") is not None else (vals[0] if vals else 0))
    current_err = float(current.get("error_rate_pct") if current.get("error_rate_pct") is not None else (_metric_values([current], "error_rate_pct")[0] if _metric_values([current], "error_rate_pct") else 0))
    hist_p95 = _metric_values(historical, "p95_ms")
    hist_err = _metric_values(historical, "error_rate_pct")
    if stored_baseline and stored_baseline.get("p95_ms") is not None:
        hist_p95.append(float(stored_baseline["p95_ms"]))
    if stored_baseline and stored_baseline.get("error_rate_pct") is not None:
        hist_err.append(float(stored_baseline["error_rate_pct"]))

    baseline_p95 = round(statistics.median(hist_p95), 2) if hist_p95 else None
    baseline_err = round(statistics.median(hist_err), 3) if hist_err else None
    baseline_source = "persistent_store" if stored_baseline else "historical_stress_reports"

    p95_delta_ms = round(current_p95 - baseline_p95, 2) if baseline_p95 is not None else None
    p95_delta_pct = (
        round((p95_delta_ms / baseline_p95) * 100, 2) if baseline_p95 and p95_delta_ms is not None and baseline_p95 > 0 else None
    )
    err_delta = round(current_err - baseline_err, 3) if baseline_err is not None else None

    violations: list[str] = []
    if p95_delta_pct is not None and p95_delta_pct > max_p95_regression_pct:
        violations.append(f"p95 regressed {p95_delta_pct}% vs baseline {baseline_p95}ms")
    if p95_delta_ms is not None and p95_delta_ms > max_p95_regression_ms:
        violations.append(f"p95 increased {p95_delta_ms}ms vs baseline")
    if err_delta is not None and err_delta > max_error_rate_delta:
        violations.append(f"error rate increased {err_delta}pp vs baseline")

    verdict = "fail" if violations and settings.performance_baseline_gate_enabled else "pass"
    if not hist_p95 and not hist_err:
        verdict = "warn"

    return {
        "baseline_sample_size": len(hist_p95),
        "baseline_source": baseline_source,
        "baseline_p95_ms": baseline_p95,
        "baseline_error_rate_pct": baseline_err,
        "current_p95_ms": current_p95,
        "current_error_rate_pct": current_err,
        "p95_delta_ms": p95_delta_ms,
        "p95_delta_percent": p95_delta_pct,
        "error_rate_delta_pp": err_delta,
        "violations": violations,
        "verdict": verdict,
        "summary": (
            f"p95 {current_p95}ms vs baseline {baseline_p95}ms ({p95_delta_pct}%); "
            f"errors {current_err}% vs {baseline_err}%."
            if baseline_p95 is not None
            else "No performance baseline history for this repository."
        ),
    }


def recommend_profiles(current: dict[str, Any], baseline: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    p95 = float(current.get("p95_ms") or 0)
    err = float(current.get("error_rate_pct") or 0)
    if p95 > 800 or err > 0.5:
        recs.append({**STRESS_PROFILES["spike"], "name": "spike", "reason": "High latency or errors — validate burst capacity."})
    if p95 < 400 and err < 0.2:
        recs.append({**STRESS_PROFILES["soak"], "name": "soak", "reason": "Stable under standard load — run soak for leak detection."})
    if not recs:
        recs.append({**STRESS_PROFILES["smoke"], "name": "smoke", "reason": "Default follow-up profile for quick regression checks."})
    return recs


def evaluate_performance_gates(
    stress_report: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    perf = str(stress_report.get("performance_verdict") or "").lower()
    if perf == "fail":
        violations.append("stress test failed absolute thresholds")

    if settings.performance_baseline_gate_enabled and baseline.get("verdict") == "fail":
        violations.extend(baseline.get("violations") or [])

    if violations and (perf == "fail" or (settings.performance_baseline_gate_enabled and baseline.get("verdict") == "fail")):
        gate = "fail"
    elif violations or perf == "warn" or baseline.get("verdict") == "warn":
        gate = "warn"
    else:
        gate = "pass"

    return {"gate_verdict": gate, "violations": violations}


def build_performance_intelligence_report(
    stress_report: dict[str, Any],
    *,
    historical_stress: list[dict[str, Any]] | None = None,
    stored_baseline: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hist = [h for h in (historical_stress or []) if isinstance(h, dict)]
    baseline = compare_to_baseline(stress_report, hist, stored_baseline=stored_baseline)
    prof = profile or resolve_stress_profile(stress_report.get("stress_profile"))
    recommendations = recommend_profiles(stress_report, baseline)
    report: dict[str, Any] = {
        "stress_profile": prof,
        "available_profiles": list(STRESS_PROFILES.keys()),
        "current": {
            "performance_verdict": stress_report.get("performance_verdict"),
            "p95_ms": stress_report.get("p95_ms"),
            "error_rate_pct": stress_report.get("error_rate_pct"),
            "requests_per_second": stress_report.get("requests_per_second"),
            "skipped": stress_report.get("skipped", False),
        },
        "baseline_comparison": baseline,
        "recommended_profiles": recommendations,
        "analysis_mode": "heuristic",
    }
    report["gates"] = evaluate_performance_gates(stress_report, baseline)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = (
        f"Performance {report['gate_verdict']}: profile={prof.get('name')}, "
        f"p95={stress_report.get('p95_ms')}ms, baseline={baseline.get('verdict')}."
    )
    return report

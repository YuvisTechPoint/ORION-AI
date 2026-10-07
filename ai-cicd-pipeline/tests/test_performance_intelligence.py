"""Tests for Phase 7 performance intelligence."""

from __future__ import annotations

from app.utils.performance_intelligence import (
    build_performance_intelligence_report,
    compare_to_baseline,
    evaluate_performance_gates,
    resolve_stress_profile,
    STRESS_PROFILES,
)


def test_resolve_stress_profile_spike():
    prof = resolve_stress_profile("spike")
    assert prof["name"] == "spike"
    assert prof["users"] == STRESS_PROFILES["spike"]["users"]


def test_compare_to_baseline_detects_regression():
    current = {"p95_ms": 1500.0, "error_rate_pct": 0.5}
    historical = [{"p95_ms": 400.0, "error_rate_pct": 0.1}, {"p95_ms": 420.0, "error_rate_pct": 0.2}]
    result = compare_to_baseline(current, historical, max_p95_regression_pct=10.0, max_p95_regression_ms=100.0)
    assert result["baseline_p95_ms"] == 410.0
    assert result["p95_delta_percent"] > 10
    assert result["violations"]


def test_build_performance_report_gate(monkeypatch):
    monkeypatch.setattr("app.utils.performance_intelligence.settings.performance_baseline_gate_enabled", False)
    stress = {"performance_verdict": "pass", "p95_ms": 300, "error_rate_pct": 0.0}
    report = build_performance_intelligence_report(stress, historical_stress=[{"p95_ms": 280, "error_rate_pct": 0.0}])
    assert report["gate_verdict"] in {"pass", "warn"}
    assert report["stress_profile"]["name"] == "standard"
    assert report["recommended_profiles"]


def test_evaluate_performance_gates_absolute_fail():
    stress = {"performance_verdict": "fail", "p95_ms": 3000, "error_rate_pct": 8.0}
    baseline = {"verdict": "pass", "violations": []}
    gates = evaluate_performance_gates(stress, baseline)
    assert gates["gate_verdict"] == "fail"

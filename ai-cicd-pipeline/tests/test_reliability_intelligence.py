"""Tests for Phase 25 reliability and chaos intelligence."""

from __future__ import annotations

import json

import pytest

from app.utils.chaos_engineering import run_chaos_experiment, run_chaos_suite
from app.utils.reliability_intelligence import (
    build_reliability_intelligence_report,
    compute_resilience_score,
    evaluate_reliability_gates,
)
from app.utils.reliability_registry import list_chaos_experiments, resolve_reliability_policy


def test_list_chaos_experiments_default():
    experiments = list_chaos_experiments()
    assert len(experiments) >= 3
    names = {e["name"] for e in experiments}
    assert "container_kill" in names


def test_resolve_reliability_policy_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.reliability_registry.settings.chaos_policy_json",
        json.dumps({"acme": {"min_resilience_score": 90, "experiments": ["container_kill"]}}),
    )
    policy = resolve_reliability_policy("acme/app")
    assert policy["min_resilience_score"] == 90.0
    assert policy["experiment_names"] == ["container_kill"]


def test_chaos_suite_simulated_resilience():
    suite = run_chaos_suite(simulated=True)
    assert suite["all_recovered"] is True
    assert suite["avg_resilience_score"] > 0
    assert suite["total"] >= 3


def test_chaos_live_disabled_by_default():
    report = run_chaos_experiment(simulated=False)
    assert report["status"] == "skipped"


def test_compute_resilience_score():
    score = compute_resilience_score(
        chaos={"avg_resilience_score": 90, "all_recovered": True},
        synthetic={"all_passed": True, "passed": 2, "total": 2},
        error_budget={"error_budget_remaining_percent": 50},
    )
    assert 50 <= score <= 100


def test_evaluate_reliability_gates_fail_low_score(monkeypatch):
    monkeypatch.setattr("app.utils.reliability_intelligence.settings.reliability_gate_enabled", True)
    gates = evaluate_reliability_gates(
        policy={"min_resilience_score": 80, "require_synthetic_pass": False},
        resilience_score=40,
        chaos={"all_recovered": True},
        synthetic={"all_passed": True},
        error_budget={},
    )
    assert gates["gate_verdict"] == "fail"


@pytest.mark.asyncio
async def test_build_reliability_intelligence_report():
    report = await build_reliability_intelligence_report(
        run_id="run-rel-1",
        repo="org/api",
        artifacts={},
        slo={"window_runs": 10, "success_rate": 0.9},
    )
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert report["resilience_score"] >= 0
    assert report["chaos_report"]["total"] >= 1
    assert report["synthetic_monitoring"]["total"] >= 1

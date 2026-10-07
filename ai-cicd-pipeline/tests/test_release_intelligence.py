"""Tests for Phase 21 release intelligence."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.utils.release_intelligence import (
    build_release_intelligence_report,
    compute_dora_metrics,
    evaluate_release_gates,
    predict_release_failure,
)
from app.utils.release_intelligence_registry import resolve_release_policy


class _Run:
    def __init__(self, status: str, repo: str = "org/app", hours: float = 1.0) -> None:
        self.status = status
        self.repo_full_name = repo
        end = datetime.now(timezone.utc)
        self.created_at = end
        self.completed_at = end


def _sample_artifacts(**overrides) -> dict:
    base = {
        "code_analysis": {"severity": "pass"},
        "security_scan": {"passed": True, "highest_severity": "low", "vulnerabilities": []},
        "qa_report": {"verdict": "pass", "test_summary": {"passed": 5, "total": 5}},
        "stress_report": {"performance_verdict": "pass"},
        "approval": {"decision": "approved", "confidence": 0.9},
        "change_risk_report": {"final_risk": 20, "risk_level": "low"},
        "sbom": {"components": [{"name": "flask"}], "stats": {"component_count": 1}},
    }
    base.update(overrides)
    return base


def test_resolve_release_policy_defaults():
    policy = resolve_release_policy("acme/api")
    assert policy["max_risk_score"] == 60.0
    assert policy["require_passport_pass"] is True
    assert "staging" in policy["promotion_path"]


def test_policy_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.release_intelligence_registry.settings.release_policy_json",
        json.dumps({"acme/api": {"max_risk_score": 45, "prediction_block_threshold": 80}}),
    )
    policy = resolve_release_policy("acme/api")
    assert policy["max_risk_score"] == 45.0
    assert policy["prediction_block_threshold"] == 80.0


def test_compute_dora_metrics():
    runs = [_Run("deployed"), _Run("deployed"), _Run("failed"), _Run("blocked_code")]
    dora = compute_dora_metrics(runs, window_days=7)
    assert dora["window_runs"] == 4
    assert dora["deploy_frequency_per_day"] > 0
    assert dora["change_failure_rate"] == 0.25
    assert "bands" in dora


def test_predict_release_failure_high_risk():
    policy = resolve_release_policy("org/app")
    prediction = predict_release_failure(
        artifacts=_sample_artifacts(change_risk_report={"final_risk": 85, "risk_level": "high"}),
        policy=policy,
    )
    assert prediction["failure_probability_percent"] >= 40
    assert prediction["recommendation"] in {"block", "canary_only", "proceed"}


def test_build_release_intelligence_report():
    report = build_release_intelligence_report(
        run_id="00000000-0000-0000-0000-000000000099",
        repo="org/app",
        branch="main",
        commit="abc123",
        artifacts=_sample_artifacts(),
        fleet_runs=[_Run("deployed"), _Run("approved")],
    )
    assert report["release_passport"]["all_checks_passed"] is True
    assert report["dora"]["window_runs"] == 2
    assert report["release_prediction"]["failure_probability_percent"] >= 0
    assert report["promotion"]["promotion_path"]
    assert report["gate_verdict"] in {"pass", "warn", "fail"}


def test_release_gate_fail_high_risk(monkeypatch):
    monkeypatch.setattr("app.utils.release_intelligence.settings.release_intelligence_gate_enabled", True)
    policy = resolve_release_policy("org/app")
    policy["max_risk_score"] = 30
    prediction = predict_release_failure(
        artifacts=_sample_artifacts(change_risk_report={"final_risk": 75}),
        policy=policy,
    )
    passport = {"all_checks_passed": True, "risk": {"final_score": 75}}
    gates = evaluate_release_gates(passport=passport, policy=policy, prediction=prediction)
    assert gates["gate_verdict"] == "fail"


def test_release_gate_warn_when_disabled(monkeypatch):
    monkeypatch.setattr("app.utils.release_intelligence.settings.release_intelligence_gate_enabled", False)
    policy = resolve_release_policy("org/app")
    policy["max_risk_score"] = 10
    prediction = {"recommendation": "block", "failure_probability_percent": 90, "threshold_percent": 70}
    passport = {"all_checks_passed": False, "risk": {"final_score": 80}}
    gates = evaluate_release_gates(passport=passport, policy=policy, prediction=prediction)
    assert gates["gate_verdict"] == "warn"

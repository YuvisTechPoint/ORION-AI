"""Tests for Phase 29 ORION Unified Risk Engine."""

from __future__ import annotations

from app.utils.unified_risk_engine import compute_unified_risk
from app.utils.unified_risk_intelligence import build_unified_risk_intelligence_report, evaluate_unified_risk_gates
from app.utils.unified_risk_registry import resolve_unified_risk_policy


def test_resolve_unified_risk_policy():
    policy = resolve_unified_risk_policy("acme/api", "staging")
    assert policy["organization"] == "acme"
    assert policy["dimension_weights"]["change_risk"] > 0
    assert abs(sum(policy["dimension_weights"].values()) - 1.0) < 0.02


def test_compute_unified_risk_low():
    risk = compute_unified_risk(
        repo="acme/api",
        environment="staging",
        artifacts={
            "code_analysis": {"severity": "pass"},
            "security_scan": {"highest_severity": "low"},
            "qa_report": {"verdict": "pass"},
            "stress_report": {"performance_verdict": "pass"},
            "change_risk_report": {"final_risk": 12, "risk_level": "low"},
        },
    )
    assert risk["unified_score"] < 40
    assert risk["risk_level"] in {"low", "medium"}
    assert risk["dimensions"]["change_risk"] == 12


def test_compute_unified_risk_high_security():
    risk = compute_unified_risk(
        artifacts={
            "code_analysis": {"severity": "fail"},
            "security_scan": {"highest_severity": "critical", "passed": False},
            "qa_report": {"verdict": "fail"},
            "stress_report": {"performance_verdict": "fail"},
            "secrets_scan": {"blocked": True, "critical_count": 2},
        },
    )
    assert risk["unified_score"] >= 50
    assert risk["risk_level"] in {"high", "critical", "medium"}
    assert risk["dimensions"]["supply_chain"] >= 70


def test_evaluate_unified_risk_gates_fail(monkeypatch):
    monkeypatch.setattr("app.utils.unified_risk_intelligence.settings.unified_risk_gate_enabled", True)
    gates = evaluate_unified_risk_gates(
        policy={"enabled": True, "max_unified_score": 50, "block_on_high": True, "block_on_critical": True},
        risk={
            "unified_score": 72,
            "risk_level": "high",
            "gate_fusion": {"verdict": "fail"},
            "release_prediction": {"recommendation": "block", "failure_probability_percent": 80},
        },
    )
    assert gates["gate_verdict"] == "fail"
    assert gates["violations"]


def test_build_unified_risk_report():
    report = build_unified_risk_intelligence_report(
        run_id="run-ur-1",
        repo="org/service",
        run_status="awaiting_approval",
        environment="staging",
        artifacts={
            "code_analysis": {"severity": "pass"},
            "security_scan": {"highest_severity": "low"},
            "qa_report": {"verdict": "pass"},
            "stress_report": {"performance_verdict": "pass"},
            "release_intelligence": {"gate_verdict": "pass", "readiness_score": 85},
            "iam_intelligence": {"gate_verdict": "pass", "readiness_score": 90},
        },
    )
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert report["unified_score"] is not None
    assert report["top_contributors"]
    assert "Unified risk" in report["summary"]

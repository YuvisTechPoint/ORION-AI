"""Tests for Phase 28 ORION Autopilot intelligence."""

from __future__ import annotations

import json

from app.utils.autopilot_intelligence import build_autopilot_intelligence_report, evaluate_autopilot_gates
from app.utils.autopilot_planner import plan_autopilot_actions, summarize_plan
from app.utils.autopilot_registry import resolve_autopilot_policy


def test_resolve_autopilot_policy():
    policy = resolve_autopilot_policy("acme/api", "staging")
    assert policy["organization"] == "acme"
    assert policy["max_autonomy_level"].startswith("L")


def test_plan_blocked_run_actions():
    actions = plan_autopilot_actions(
        repo="acme/api",
        environment="staging",
        run_status="blocked_tests",
        artifacts={
            "code_analysis": {"severity": "pass"},
            "security_scan": {"highest_severity": "low"},
            "qa_report": {"verdict": "fail"},
            "stress_report": {"performance_verdict": "pass"},
        },
    )
    ids = {a["id"] for a in actions}
    assert "explain_blocker" in ids


def test_plan_predeploy_actions(monkeypatch):
    monkeypatch.setattr("app.utils.autopilot_planner.settings.progressive_delivery_enabled", True)
    actions = plan_autopilot_actions(
        repo="acme/api",
        environment="staging",
        run_status="awaiting_approval",
        artifacts={
            "code_analysis": {"severity": "pass"},
            "security_scan": {"highest_severity": "low"},
            "qa_report": {"verdict": "pass"},
            "stress_report": {"performance_verdict": "pass"},
            "change_risk_report": {"final_risk": 25},
        },
    )
    ids = {a["id"] for a in actions}
    assert "proceed_deploy" in ids
    assert "post_deploy_monitor" in ids


def test_evaluate_autopilot_gates_fail(monkeypatch):
    monkeypatch.setattr("app.utils.autopilot_intelligence.settings.autopilot_gate_enabled", True)
    gates = evaluate_autopilot_gates(
        policy={"enabled": True},
        actions=[{"id": "proceed_deploy", "allowed": True, "level": "L6"}],
        autonomy_policy={"passed": False, "violations": [{"detail": "auto-PR denied"}]},
        fusion={"verdict": "pass"},
    )
    assert gates["gate_verdict"] == "fail"


def test_build_autopilot_report():
    report = build_autopilot_intelligence_report(
        run_id="run-ap-1",
        repo="org/service",
        run_status="awaiting_approval",
        environment="staging",
        artifacts={
            "code_analysis": {"severity": "pass"},
            "security_scan": {"highest_severity": "low"},
            "qa_report": {"verdict": "pass"},
            "stress_report": {"performance_verdict": "pass"},
        },
    )
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert report["planned_actions"]
    assert report["simulate_only"] is True


def test_summarize_plan():
    text = summarize_plan([{"allowed": True}, {"allowed": False}])
    assert "2 action" in text


def test_policy_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.autopilot_registry.settings.autopilot_policy_json",
        json.dumps({"acme": {"max_autonomy_level": "L2", "retry_allowed": True}}),
    )
    policy = resolve_autopilot_policy("acme/checkout", "production")
    assert policy["max_autonomy_level"] == "L2"
    assert policy["retry_allowed"] is True

"""Tests for Phase 19 AI governance intelligence."""

from __future__ import annotations

import json

from app.utils.ai_governance_intelligence import (
    build_ai_governance_intelligence_report,
    build_escalation_queue,
    evaluate_governance_gates,
)
from app.utils.ai_governance_registry import build_governance_policy_catalog


def test_governance_policy_catalog():
    catalog = build_governance_policy_catalog()
    assert len(catalog["controls"]) >= 5
    assert catalog["min_confidence"] >= 0.5
    assert catalog["escalation_rules"]


def test_escalation_queue_low_approval_confidence():
    queue = build_escalation_queue(
        {
            "approval": {"decision": "approved", "confidence": 0.55},
            "agent_eval_report": {"aggregate_score": 0.9, "human_review_required": False},
        }
    )
    codes = {e["code"] for e in queue}
    assert "approval_low_confidence" in codes


def test_escalation_queue_agent_eval():
    queue = build_escalation_queue(
        {
            "agent_eval_report": {
                "human_review_required": True,
                "low_scoring_artifacts": ["security_scan"],
                "summary": "review required",
            }
        }
    )
    assert any(e["code"] == "agent_eval_low" for e in queue)


def test_escalation_high_risk(monkeypatch):
    monkeypatch.setattr("app.utils.ai_governance_intelligence.settings.approval_high_risk_threshold", 70)
    queue = build_escalation_queue({"change_risk_report": {"final_risk": 85}})
    assert any(e["code"] == "high_change_risk" for e in queue)


def test_build_governance_report():
    report = build_ai_governance_intelligence_report(
        artifacts={
            "code_analysis": {"severity": "pass", "analysis_mode": "heuristic", "summary": "ok"},
            "security_scan": {"passed": True, "analysis_mode": "llm", "summary": "clean"},
            "approval": {"decision": "approved", "confidence": 0.92},
            "agent_eval_report": {"aggregate_score": 0.82, "human_review_required": False},
            "model_routing_plan": {"complexity": "low", "routes": []},
            "decision_ledger": {"decision_count": 2},
        },
        run_id="run-1234",
    )
    assert report["governance_score"] > 0
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert report["decision_ledger"]["decision_count"] >= 1
    assert report["token_rollup"]["total_tokens"] >= 0


def test_governance_gate_fail(monkeypatch):
    monkeypatch.setattr("app.utils.ai_governance_intelligence.settings.ai_governance_gate_enabled", True)
    monkeypatch.setattr("app.utils.ai_governance_intelligence.settings.ai_governance_min_score", 0.9)
    gates = evaluate_governance_gates(
        escalations=[{"severity": "high", "reason": "test", "code": "x"}],
        governance_score=0.5,
    )
    assert gates["gate_verdict"] == "fail"


def test_policy_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.ai_governance_registry.settings.ai_governance_policy_json",
        json.dumps({"min_confidence": 0.85, "escalation_rules": [{"id": "custom", "action": "block"}]}),
    )
    catalog = build_governance_policy_catalog()
    assert catalog["min_confidence"] == 0.85
    assert catalog["escalation_rules"][0]["id"] == "custom"

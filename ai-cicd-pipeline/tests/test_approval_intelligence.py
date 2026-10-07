"""Tests for Phase 13 enterprise approval intelligence."""

from __future__ import annotations

import json

from app.utils.approval_intelligence import build_approval_intelligence_report
from app.utils.approval_workflow import resolve_approval_workflow
from app.utils.enterprise_approval import (
    evaluate_enterprise_approval,
    initialize_enterprise_approval,
    record_signoff,
    sign_approval_token,
    verify_approval_token,
)


def test_resolve_approval_workflow_defaults():
    workflow = resolve_approval_workflow(org="acme", repo="acme/api", environment="staging")
    assert workflow["required_approvals"] >= 1
    assert "release_manager" in workflow["roles"]


def test_production_requires_two_approvers():
    workflow = resolve_approval_workflow(org="acme", repo="acme/api", environment="production")
    assert workflow["required_approvals"] >= 2
    assert workflow["four_eyes"] is True


def test_high_risk_increases_required_approvals(monkeypatch):
    monkeypatch.setattr("app.utils.approval_workflow.settings.approval_high_risk_threshold", 60)
    monkeypatch.setattr("app.utils.approval_workflow.settings.approval_high_risk_required_count", 3)
    workflow = resolve_approval_workflow(
        org="acme",
        repo="acme/api",
        environment="staging",
        change_risk_score=75,
    )
    assert workflow["required_approvals"] >= 3
    assert workflow["four_eyes"] is True


def test_four_eyes_blocks_committer_signoff():
    workflow = {"required_approvals": 1, "four_eyes": True, "signed_approvals": False, "roles": ["release_manager"]}
    record = initialize_enterprise_approval(
        run_id="run-1",
        repo="acme/api",
        commit="abc123",
        committer="dev@acme.com",
        automated_approval={"decision": "approved"},
        workflow=workflow,
    )
    updated = record_signoff(record, approver="dev@acme.com", role="release_manager", comment="self approve")
    status = evaluate_enterprise_approval(updated)
    assert status["ready_for_deploy"] is False
    assert any("four-eyes" in v for v in status["violations"])


def test_multi_person_approval_ready():
    workflow = {"required_approvals": 2, "four_eyes": True, "signed_approvals": False, "roles": ["release_manager"]}
    record = initialize_enterprise_approval(
        run_id="run-2",
        repo="acme/api",
        commit="abc123",
        committer="dev@acme.com",
        automated_approval={"decision": "approved"},
        workflow=workflow,
    )
    record = record_signoff(record, approver="lead@acme.com", role="release_manager")
    record = record_signoff(record, approver="mgr@acme.com", role="release_manager")
    status = evaluate_enterprise_approval(record)
    assert status["ready_for_deploy"] is True
    assert status["status"] == "approved"


def test_signed_approval_token_roundtrip():
    ts = "2026-10-06T00:00:00+00:00"
    token = sign_approval_token(run_id="run-3", approver="lead@acme.com", role="release_manager", timestamp=ts)
    assert verify_approval_token(
        run_id="run-3",
        approver="lead@acme.com",
        role="release_manager",
        timestamp=ts,
        token=token,
    )


def test_build_approval_intelligence_report_warn_without_enforcement(monkeypatch):
    monkeypatch.setattr("app.utils.approval_intelligence.settings.enterprise_approval_enforcement_enabled", False)
    report = build_approval_intelligence_report(
        org="acme",
        repo="acme/api",
        environment="production",
        commit="abc",
        committer="dev@acme.com",
        automated_approval={"decision": "approved"},
        change_risk_score=10,
    )
    assert report["gate_verdict"] in {"pass", "warn"}
    assert report["enterprise_approval"]["required_approvals"] >= 2


def test_repo_workflow_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.approval_workflow.settings.approval_repo_workflow_json",
        json.dumps({"acme/api": {"required_approvals": 4, "roles": ["security", "release_manager"]}}),
    )
    workflow = resolve_approval_workflow(org="acme", repo="acme/api", environment="staging")
    assert workflow["required_approvals"] == 4
    assert "security" in workflow["roles"]

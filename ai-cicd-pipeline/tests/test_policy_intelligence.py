"""Tests for Phase 12 policy-as-code intelligence."""

from __future__ import annotations

import json

from app.utils.ai_autonomy_policy import evaluate_ai_autonomy_policies
from app.utils.policy_engine import evaluate_policies
from app.utils.policy_intelligence import build_policy_intelligence_report
from app.utils.policy_registry import build_policy_registry_report, resolve_effective_policies


def test_resolve_effective_policies_defaults():
    policies = resolve_effective_policies(org="acme", repo="acme/api", environment="staging")
    names = {p["name"] for p in policies}
    assert "production-security" in names
    assert "high-risk-gate" in names


def test_org_repo_env_policy_merge(monkeypatch):
    monkeypatch.setattr(
        "app.utils.policy_registry.settings.policy_org_rules_json",
        json.dumps({"acme": {"policies": [{"name": "acme-base", "deny_if": {}, "require": {}}]}}),
    )
    monkeypatch.setattr(
        "app.utils.policy_registry.settings.policy_repo_rules_json",
        json.dumps({"acme/api": {"policies": [{"name": "api-strict", "deny_if": {"secrets_detected": ">0"}, "require": {}}]}}),
    )
    policies = resolve_effective_policies(org="acme", repo="acme/api", environment="staging")
    names = {p["name"] for p in policies}
    assert "acme-base" in names
    assert "api-strict" in names


def test_ai_autonomy_policy_blocks_auto_pr(monkeypatch):
    monkeypatch.setattr(
        "app.utils.policy_registry.settings.policy_repo_rules_json",
        json.dumps({"acme/api": {"ai_autonomy": {"max_level": "L2", "auto_pr_allowed": False}}}),
    )
    result = evaluate_ai_autonomy_policies(
        org="acme",
        repo="acme/api",
        environment="staging",
        artifacts={
            "patch_confidence_report": {"patch_confidence": 92, "action": "auto_pr"},
            "remediation_intelligence": {"autonomy": {"achieved_level": "L4"}},
        },
    )
    assert result["passed"] is False
    assert any(v["rule"] == "auto_pr_denied" for v in result["violations"])


def test_build_policy_intelligence_report_pass():
    artifacts = {
        "security_scan": {"vulnerabilities": []},
        "secrets_scan": {"critical_count": 0},
        "qa_report": {"verdict": "pass"},
        "sbom": {"components": [{"name": "pkg"}]},
        "approval": {"decision": "approved"},
    }
    report = build_policy_intelligence_report(
        org="acme",
        repo="acme/api",
        environment="staging",
        artifacts=artifacts,
    )
    assert report["policy_evaluation"]["passed"] is True
    assert report["gate_verdict"] in {"pass", "warn"}


def test_policy_engine_blocks_secrets():
    result = evaluate_policies(
        {"secrets_scan": {"critical_count": 2}, "qa_report": {"verdict": "pass"}},
    )
    assert result["passed"] is False
    assert result["violation_count"] >= 1


def test_policy_registry_report():
    report = build_policy_registry_report(org="acme", repo="acme/api", environment="production")
    assert report["policy_count"] >= 2
    assert report["ai_autonomy"]["max_level"]

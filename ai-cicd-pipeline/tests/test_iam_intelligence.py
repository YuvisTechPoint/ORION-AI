"""Tests for Phase 24 enterprise IAM intelligence."""

from __future__ import annotations

import json

from app.utils.enterprise_sso import assess_sso_readiness
from app.utils.iam_intelligence import (
    assess_api_key_hygiene,
    assess_mfa_readiness,
    assess_session_hardening,
    build_iam_intelligence_report,
    evaluate_iam_gates,
)
from app.utils.iam_registry import resolve_iam_policy


def test_resolve_iam_policy_defaults():
    policy = resolve_iam_policy("acme/checkout")
    assert policy["organization"] == "acme"
    assert "require_sso" in policy
    assert policy["min_readiness_score"] >= 0


def test_resolve_iam_policy_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.iam_registry.settings.iam_policy_json",
        json.dumps({"acme": {"require_mfa": True, "min_readiness_score": 85}}),
    )
    policy = resolve_iam_policy("acme/app")
    assert policy["require_mfa"] is True
    assert policy["min_readiness_score"] == 85.0


def test_session_hardening_detects_weak_secret():
    report = assess_session_hardening()
    assert "hardening_score" in report
    assert "api_require_auth" in report


def test_api_key_hygiene_empty():
    report = assess_api_key_hygiene()
    assert "key_count" in report
    assert "hygiene_score" in report


def test_mfa_readiness():
    report = assess_mfa_readiness()
    assert report["status"] in {"ready", "gap"}
    assert "summary" in report


def test_sso_readiness_includes_providers():
    report = assess_sso_readiness()
    providers = {p["provider"] for p in report["providers"]}
    assert "github_oauth" in providers
    assert "saml" in providers
    assert "oidc" in providers


def test_evaluate_iam_gates_warn_without_sso(monkeypatch):
    monkeypatch.setattr("app.utils.iam_intelligence.settings.iam_gate_enabled", False)
    policy = {"require_sso": True, "require_mfa": False, "require_api_auth": False, "min_readiness_score": 70}
    sso = {"active_providers": ["github_oauth"], "enterprise_ready": False}
    session = {"api_require_auth": False, "issues": []}
    mfa = {"status": "ready"}
    gates = evaluate_iam_gates(
        policy=policy,
        readiness_score=50,
        sso=sso,
        session=session,
        mfa=mfa,
    )
    assert gates["gate_verdict"] in {"warn", "fail"}
    assert gates["violations"]


def test_build_iam_intelligence_report():
    report = build_iam_intelligence_report(
        run_id="run-iam-1",
        repo="org/service",
        artifacts={"sso_readiness": assess_sso_readiness()},
    )
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert report["readiness_score"] >= 0
    assert report["sso_readiness"]["providers"]
    assert report["policy"]["organization"] == "org"

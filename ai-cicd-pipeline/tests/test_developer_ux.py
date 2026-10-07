"""Tests for Phase 22 developer UX and GitHub App."""

from __future__ import annotations

import json

from app.services.github_app_service import handle_github_app_event
from app.utils.developer_ux_intelligence import (
    assess_developer_ux_readiness,
    build_developer_ux_intelligence_report,
)
from app.utils.developer_ux_registry import build_developer_catalog, build_vscode_extension_manifest
from app.utils.github_app_registry import build_github_app_manifest, resolve_github_app_config


def test_vscode_extension_manifest():
    manifest = build_vscode_extension_manifest()
    assert manifest["name"] == "orion-devops"
    assert len(manifest["commands"]) >= 4
    assert "orion.apiUrl" in manifest["configuration"]


def test_developer_catalog():
    catalog = build_developer_catalog()
    assert catalog["cli_entrypoint"] == "orion"
    assert len(catalog["cli_groups"]) >= 3
    assert catalog["vscode"]["extension_id"]


def test_github_app_manifest():
    manifest = build_github_app_manifest()
    assert "hook_attributes" in manifest
    assert "/webhook/github/app" in manifest["hook_attributes"]["url"]
    assert "pull_request" in manifest["default_events"]


def test_github_app_config_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.github_app_registry.settings.github_app_config_json",
        json.dumps({"events": ["push", "installation"], "permissions": {"issues": "read"}}),
    )
    config = resolve_github_app_config()
    assert config["events"] == ["push", "installation"]
    assert config["permissions"]["issues"] == "read"


def test_developer_ux_readiness():
    readiness = assess_developer_ux_readiness()
    assert "readiness_score" in readiness
    assert readiness["cli_ready"] is True


def test_build_developer_ux_report():
    report = build_developer_ux_intelligence_report(
        run_id="run-1",
        repo="org/app",
        artifacts={"pr_intelligence": {"posted": True}},
    )
    assert report["surfaces"]["cli"]["status"] == "ready"
    assert report["gate_verdict"] in {"pass", "warn", "fail"}


def test_github_app_installation_event(monkeypatch):
    monkeypatch.setattr("app.services.github_app_service.settings.github_app_enabled", True)
    result = handle_github_app_event(
        "installation",
        {"action": "created", "installation": {"id": 42, "account": {"login": "acme"}}},
    )
    assert result["status"] == "ok"
    assert result["installation_id"] == 42


def test_github_app_disabled():
    result = handle_github_app_event("ping", {"zen": "test"})
    assert result["status"] == "ignored"

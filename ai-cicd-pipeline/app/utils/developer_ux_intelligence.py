"""Developer UX intelligence — readiness for CLI, VS Code, and GitHub App."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.developer_ux_registry import build_developer_catalog, build_vscode_extension_manifest
from app.utils.github_app_registry import resolve_github_app_config


def assess_developer_ux_readiness() -> dict[str, Any]:
    vscode = build_vscode_extension_manifest()
    github_app = resolve_github_app_config()
    issues: list[str] = []
    score = 100

    if not settings.github_enabled and not github_app.get("enabled"):
        issues.append("GitHub PAT not configured — PR comments and triggers limited")
        score -= 15
    if settings.api_require_auth and not settings.orion_api_key:
        issues.append("API auth enabled but ORION_API_KEY unset for CLI/IDE")
        score -= 10
    if github_app.get("enabled") and not settings.github_app_id:
        issues.append("GITHUB_APP_ENABLED but GITHUB_APP_ID missing")
        score -= 20
    if github_app.get("enabled") and not settings.github_app_webhook_secret:
        issues.append("GitHub App webhook secret not configured")
        score -= 15

    cli_ready = True
    ide_ready = bool(vscode.get("commands"))
    app_ready = bool(github_app.get("enabled") and settings.github_app_id)

    return {
        "cli_ready": cli_ready,
        "vscode_ready": ide_ready,
        "github_app_ready": app_ready,
        "readiness_score": max(0, score),
        "issues": issues,
        "summary": (
            f"Developer UX readiness {max(0, score)}%: "
            f"CLI={'ok' if cli_ready else 'warn'}, "
            f"VS Code={'ok' if ide_ready else 'warn'}, "
            f"GitHub App={'ok' if app_ready else 'pending'}."
        ),
    }


def build_developer_ux_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    catalog = build_developer_catalog()
    readiness = assess_developer_ux_readiness()
    github_app = resolve_github_app_config()
    pr_intel = artifacts.get("pr_intelligence") or {}

    surfaces = {
        "cli": {"status": "ready", "entrypoint": "orion"},
        "vscode": {
            "status": "ready" if readiness["vscode_ready"] else "partial",
            "extension_id": catalog["vscode"]["extension_id"],
            "package_path": catalog["vscode"]["package_path"],
        },
        "github_app": {
            "status": "ready" if readiness["github_app_ready"] else "manifest_only",
            "webhook_url": github_app.get("webhook_url"),
            "events": github_app.get("events"),
        },
        "dashboard": {"url": catalog["dashboard_url"], "status": "ready"},
    }

    report: dict[str, Any] = {
        "run_id": run_id or None,
        "repository": repo or None,
        "catalog": catalog,
        "readiness": readiness,
        "surfaces": surfaces,
        "github_app": github_app,
        "pr_intelligence_posted": pr_intel.get("posted"),
        "gate_verdict": "pass" if readiness["readiness_score"] >= 70 else "warn",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "heuristic",
    }
    report["summary"] = readiness["summary"]
    return report

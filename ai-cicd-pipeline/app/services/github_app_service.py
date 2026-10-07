"""GitHub App event routing — installation lifecycle and PR/check integrations."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.pr_intelligence import build_pr_review_comment
from app.utils.github_app_registry import resolve_github_app_config


def github_app_configured() -> bool:
    return bool(settings.github_app_enabled and settings.github_app_id)


def handle_github_app_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Route GitHub App webhook events (heuristic handlers; REST calls via existing GitHubService)."""
    if not settings.github_app_enabled:
        return {"status": "ignored", "reason": "github_app_disabled"}

    if event == "ping":
        return {"status": "ok", "event": "ping", "zen": payload.get("zen")}

    if event == "installation":
        action = payload.get("action", "")
        installation = payload.get("installation") or {}
        return {
            "status": "ok",
            "event": event,
            "action": action,
            "installation_id": installation.get("id"),
            "account": (installation.get("account") or {}).get("login"),
            "summary": f"GitHub App installation {action} for {(installation.get('account') or {}).get('login', 'unknown')}.",
        }

    if event == "installation_repositories":
        action = payload.get("action", "")
        repos_added = payload.get("repositories_added") or []
        return {
            "status": "ok",
            "event": event,
            "action": action,
            "repositories_added": [r.get("full_name") for r in repos_added],
            "summary": f"GitHub App repos {action}: {len(repos_added)} repository(ies).",
        }

    if event == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request") or {}
        repo = (payload.get("repository") or {}).get("full_name")
        if action in {"opened", "synchronize", "reopened"}:
            preview = build_pr_review_comment(
                {
                    "change_risk_report": {"final_risk": "—", "risk_level": "unknown"},
                    "security_scan": {},
                    "qa_report": {},
                    "release_passport": {},
                }
            )
            return {
                "status": "accepted",
                "event": event,
                "action": action,
                "pr_number": pr.get("number"),
                "repository": repo,
                "review_preview": preview[:280],
                "summary": f"GitHub App PR #{pr.get('number')} {action} — ORION review queued.",
            }
        return {"status": "ignored", "event": event, "action": action}

    if event in {"check_run", "check_suite"}:
        return {
            "status": "accepted",
            "event": event,
            "action": payload.get("action"),
            "summary": f"GitHub App {event} received — correlate with ORION pipeline checks.",
        }

    if event == "push":
        return {
            "status": "delegated",
            "event": event,
            "reason": "use /webhook/github for push pipeline dispatch",
            "summary": "Push events should use the primary ORION webhook endpoint.",
        }

    return {"status": "ignored", "event": event, "reason": "unsupported_event"}


def github_app_status() -> dict[str, Any]:
    config = resolve_github_app_config()
    configured = github_app_configured()
    return {
        **config,
        "configured": configured,
        "private_key_set": bool(settings.github_app_private_key),
        "webhook_secret_set": bool(settings.github_app_webhook_secret),
    }

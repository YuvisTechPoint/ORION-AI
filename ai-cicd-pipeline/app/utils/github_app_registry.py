"""GitHub App registry — manifest, permissions, and subscribed events."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

DEFAULT_PERMISSIONS: dict[str, str] = {
    "contents": "read",
    "metadata": "read",
    "pull_requests": "write",
    "issues": "write",
    "checks": "write",
    "statuses": "write",
    "actions": "read",
}

DEFAULT_EVENTS = [
    "push",
    "pull_request",
    "pull_request_review",
    "check_run",
    "check_suite",
    "installation",
    "installation_repositories",
]


def build_github_app_manifest() -> dict[str, Any]:
    hook_url = f"{settings.orion_api_url.rstrip('/')}/api/v1/webhook/github/app"
    return {
        "name": settings.github_app_name,
        "description": settings.github_app_description,
        "url": settings.orion_ui_url,
        "hook_attributes": {"url": hook_url, "active": True},
        "redirect_url": settings.github_redirect_uri,
        "public": False,
        "default_permissions": DEFAULT_PERMISSIONS,
        "default_events": DEFAULT_EVENTS,
        "request_oauth_on_install": True,
    }


def resolve_github_app_config() -> dict[str, Any]:
    custom = _parse_json(settings.github_app_config_json)
    manifest = build_github_app_manifest()
    if custom.get("permissions"):
        manifest["default_permissions"] = {**DEFAULT_PERMISSIONS, **custom["permissions"]}
    if custom.get("events"):
        manifest["default_events"] = list(custom["events"])
    return {
        "enabled": settings.github_app_enabled,
        "app_id": settings.github_app_id or None,
        "client_id": settings.github_app_client_id or settings.github_client_id or None,
        "webhook_url": manifest["hook_attributes"]["url"],
        "installation_mode": settings.github_app_installation_mode,
        "manifest": manifest,
        "permissions": manifest["default_permissions"],
        "events": manifest["default_events"],
        "summary": (
            f"GitHub App '{settings.github_app_name}': "
            f"{'enabled' if settings.github_app_enabled else 'disabled'}, "
            f"{len(manifest['default_events'])} event(s)."
        ),
    }


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}

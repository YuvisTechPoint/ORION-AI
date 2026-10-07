"""Per-operator preferences stored in the server session after GitHub login."""

from __future__ import annotations

from typing import Any

DEFAULT_PREFERENCES: dict[str, Any] = {
    "default_branch": "main",
    "default_repo_url": "",
    "default_repo_name": "",
    "auto_pr_enabled": True,
    "notify_on_block": True,
    "open_github_profile": True,
}

_PREFERENCE_KEYS = frozenset(DEFAULT_PREFERENCES.keys())


def get_user_preferences(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get("user_preferences")
    if not isinstance(raw, dict):
        raw = {}
    merged = {**DEFAULT_PREFERENCES, **raw}
    merged["auto_pr_enabled"] = bool(merged.get("auto_pr_enabled", True))
    merged["notify_on_block"] = bool(merged.get("notify_on_block", True))
    merged["open_github_profile"] = bool(merged.get("open_github_profile", True))
    return merged


def update_user_preferences(session: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    current = get_user_preferences(session)
    for key, value in updates.items():
        if key not in _PREFERENCE_KEYS or value is None:
            continue
        if key in {"auto_pr_enabled", "notify_on_block", "open_github_profile"}:
            current[key] = bool(value)
        elif key == "default_branch":
            branch = str(value).strip()
            current[key] = branch[:120] if branch else DEFAULT_PREFERENCES["default_branch"]
        else:
            current[key] = str(value).strip()[:500]
    session["user_preferences"] = current
    return current

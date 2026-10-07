"""Enterprise IAM registry — SSO/MFA requirements and org-scoped policy defaults."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["read", "trigger", "approve", "deploy", "config", "audit"],
    "operator": ["read", "trigger", "deploy", "audit"],
    "approver": ["read", "approve", "audit"],
    "viewer": ["read"],
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


def resolve_iam_policy(repo: str = "") -> dict[str, Any]:
    custom = _parse_json(settings.iam_policy_json)
    org = repo.split("/", 1)[0] if "/" in repo else repo
    org_block = custom.get(org) if isinstance(custom.get(org), dict) else {}
    repo_block = custom.get(repo) if isinstance(custom.get(repo), dict) else {}

    def _bool(key: str, default: bool) -> bool:
        if key in repo_block:
            return bool(repo_block[key])
        if key in org_block:
            return bool(org_block[key])
        return default

    def _float(key: str, default: float) -> float:
        raw = repo_block.get(key) if key in repo_block else org_block.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    require_sso = _bool("require_sso", settings.iam_require_sso_in_production and settings.is_production)
    require_mfa = _bool("require_mfa", settings.iam_mfa_required)
    require_api_auth = _bool("require_api_auth", settings.is_production)
    min_score = _float("min_readiness_score", settings.iam_min_readiness_score)

    return {
        "repository": repo or None,
        "organization": org or None,
        "require_sso": require_sso,
        "require_mfa": require_mfa,
        "require_api_auth": require_api_auth,
        "min_readiness_score": min_score,
        "tenant_isolation_mode": settings.tenant_isolation_mode,
        "role_permissions": DEFAULT_ROLE_PERMISSIONS,
        "summary": (
            f"IAM policy: SSO required={require_sso}, MFA required={require_mfa}, "
            f"API auth required={require_api_auth}, min readiness {min_score:.0f}%."
        ),
    }

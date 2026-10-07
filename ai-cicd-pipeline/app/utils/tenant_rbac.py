"""Multi-tenant RBAC context derived from repository namespace."""

from __future__ import annotations

from typing import Any

from app.config import settings


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"read", "trigger", "approve", "deploy", "config", "audit"},
    "operator": {"read", "trigger", "deploy", "audit"},
    "approver": {"read", "approve", "audit"},
    "viewer": {"read"},
}


def resolve_tenant_context(
    repo_full_name: str,
    *,
    user_roles: list[str] | None = None,
) -> dict[str, Any]:
    parts = (repo_full_name or "unknown/unknown").split("/", 1)
    org = parts[0] if parts else "unknown"
    repo = parts[1] if len(parts) > 1 else parts[0]

    roles = user_roles or ["operator"]
    permissions: set[str] = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, set()))

    return {
        "tenant_id": org,
        "namespace": org,
        "repository": repo_full_name,
        "isolation_mode": getattr(settings, "tenant_isolation_mode", "org"),
        "roles": roles,
        "permissions": sorted(permissions),
        "rbac_enforced": settings.api_require_auth,
        "cross_tenant_access": False,
        "summary": f"Tenant {org} — roles {', '.join(roles)} ({len(permissions)} permission(s)).",
    }


def tenant_allows_action(tenant: dict[str, Any], action: str) -> bool:
    if not tenant.get("rbac_enforced"):
        return True
    return action in set(tenant.get("permissions") or [])

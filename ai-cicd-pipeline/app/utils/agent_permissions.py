"""Agent permission model — least-privilege capability matrix."""

from __future__ import annotations

from typing import Any

AGENT_PERMISSIONS: dict[str, dict[str, Any]] = {
    "CodeAnalysisAgent": {
        "read": ["repository", "diff"],
        "write": ["artifacts"],
        "execute": ["pylint", "ast_scan"],
        "external": [],
    },
    "SecurityAgent": {
        "read": ["repository", "dependencies"],
        "write": ["artifacts"],
        "execute": ["bandit", "pip_audit", "semgrep"],
        "external": ["gitleaks", "trivy", "checkov"],
    },
    "QAAgent": {
        "read": ["repository", "tests"],
        "write": ["artifacts"],
        "execute": ["pytest"],
        "external": [],
    },
    "DeploymentAgent": {
        "read": ["repository", "deployment_config"],
        "write": ["deployment", "artifacts"],
        "execute": ["docker"],
        "external": ["container_registry"],
        "approval": {"required": True},
    },
    "SoftwareEngineerAgent": {
        "read": ["repository", "diff"],
        "write": ["artifacts", "sandbox_workspace"],
        "execute": ["pytest", "sandbox"],
        "external": ["github_pr"],
        "approval": {"required": True, "threshold": "patch_confidence"},
    },
    "MonitoringAgent": {
        "read": ["logs", "metrics", "deployment"],
        "write": ["artifacts", "alerts"],
        "execute": ["health_check", "rollback"],
        "external": ["slack"],
    },
}


def build_permissions_report(*, agents_used: list[str] | None = None) -> dict[str, Any]:
    used = agents_used or list(AGENT_PERMISSIONS.keys())
    rows = []
    for name in used:
        perms = AGENT_PERMISSIONS.get(name)
        if not perms:
            rows.append({"agent": name, "status": "unknown", "permissions": {}})
            continue
        rows.append({"agent": name, "status": "defined", "permissions": perms})
    undefined = [a for a in used if a not in AGENT_PERMISSIONS]
    return {
        "agents": rows,
        "defined_count": len(rows) - len(undefined),
        "undefined_agents": undefined,
        "enforcement_mode": "documented",
        "summary": f"Permission model: {len(rows)} agent(s) evaluated.",
    }


def agent_may_execute(agent_name: str, capability: str) -> bool:
    perms = AGENT_PERMISSIONS.get(agent_name) or {}
    allowed = set(perms.get("execute") or [])
    return capability in allowed

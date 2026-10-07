"""Agent sandbox policy limits (aligned with AgentSandbox)."""

from __future__ import annotations

from typing import Any


DEFAULT_SANDBOX_POLICY: dict[str, Any] = {
    "filesystem": {"scope": "ephemeral_copy", "write_allowed": True, "production_paths": False},
    "network": {"egress": "pytest_only", "external_calls": False},
    "shell": {"allowed_commands": ["pytest"], "timeout_seconds": 120},
    "credentials": {"production_secrets": False, "inherited_env": "repo_env_only"},
    "resources": {"cpu_limit": "2 cores", "memory_limit": "2Gi", "timeout_seconds": 120},
}


def build_sandbox_policy_report(*, fix_loop: dict[str, Any] | None = None) -> dict[str, Any]:
    fix_loop = fix_loop or {}
    sandbox_runs = int(fix_loop.get("attempts") or 0)
    return {
        "policy": DEFAULT_SANDBOX_POLICY,
        "mandatory_for": ["SoftwareEngineerAgent", "AutoPRService"],
        "sandbox_runs_this_pipeline": sandbox_runs,
        "isolation_verified": fix_loop.get("sandbox_passed") if fix_loop else None,
        "summary": "Sandbox policy active for autonomous patch verification.",
    }

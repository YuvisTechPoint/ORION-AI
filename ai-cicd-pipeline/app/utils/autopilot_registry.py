"""ORION Autopilot registry — autonomy caps and allowed action catalog."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.utils.remediation_levels import REMEDIATION_LEVELS, level_rank

ACTION_CATALOG: list[dict[str, Any]] = [
    {"id": "explain_blocker", "level": "L0", "risk": "low", "description": "Summarize blockers and evidence for operators"},
    {"id": "recommend_fix", "level": "L1", "risk": "low", "description": "Recommend remediation steps and runbooks"},
    {"id": "generate_patch", "level": "L2", "risk": "medium", "description": "Generate AI patch bundles"},
    {"id": "sandbox_verify", "level": "L3", "risk": "medium", "description": "Verify patches in agent sandbox"},
    {"id": "open_auto_pr", "level": "L4", "risk": "medium", "description": "Open fix PRs on GitHub"},
    {"id": "pipeline_retry", "level": "L5", "risk": "high", "description": "Retry pipeline after fix merge"},
    {"id": "resume_checkpoint", "level": "L5", "risk": "medium", "description": "Resume from checkpoint artifacts"},
    {"id": "proceed_deploy", "level": "L6", "risk": "high", "description": "Continue to deployment stage"},
    {"id": "progressive_canary", "level": "L6", "risk": "high", "description": "Progressive canary rollout"},
    {"id": "post_deploy_monitor", "level": "L1", "risk": "low", "description": "Enable monitoring window after deploy"},
    {"id": "incident_rollback", "level": "L6", "risk": "critical", "description": "Rollback on monitoring failure"},
    {"id": "operator_escalation", "level": "L0", "risk": "low", "description": "Escalate to human approver"},
]


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def resolve_autopilot_policy(repo: str = "", environment: str = "") -> dict[str, Any]:
    custom = _parse_json(settings.autopilot_policy_json)
    org = repo.split("/", 1)[0] if "/" in repo else repo
    org_block = custom.get(org) if isinstance(custom.get(org), dict) else {}
    repo_block = custom.get(repo) if isinstance(custom.get(repo), dict) else {}
    env_block = custom.get(environment) if isinstance(custom.get(environment), dict) else {}

    def _bool(key: str, default: bool) -> bool:
        for block in (env_block, repo_block, org_block):
            if key in block:
                return bool(block[key])
        return default

    def _float(key: str, default: float) -> float:
        for block in (env_block, repo_block, org_block):
            if key in block:
                try:
                    return float(block[key])
                except (TypeError, ValueError):
                    pass
        return default

    def _str(key: str, default: str) -> str:
        for block in (env_block, repo_block, org_block):
            if key in block and block[key]:
                return str(block[key])
        return default

    max_level = _str("max_autonomy_level", settings.autopilot_max_autonomy_level)
    return {
        "repository": repo or None,
        "organization": org or None,
        "environment": environment or None,
        "enabled": _bool("enabled", settings.autopilot_enabled),
        "max_autonomy_level": max_level,
        "max_autonomy_rank": level_rank(max_level),
        "auto_pr_allowed": _bool("auto_pr_allowed", settings.autopilot_auto_pr_allowed),
        "retry_allowed": _bool("retry_allowed", settings.autopilot_retry_allowed),
        "deploy_allowed": _bool("deploy_allowed", settings.autopilot_deploy_allowed),
        "require_approval_above_risk": _float(
            "require_approval_above_risk", settings.autopilot_require_approval_above_risk
        ),
        "simulate_only": _bool("simulate_only", settings.autopilot_simulate_only),
        "action_catalog": ACTION_CATALOG,
        "levels": REMEDIATION_LEVELS,
        "summary": (
            f"Autopilot policy: max {max_level}, simulate_only={_bool('simulate_only', settings.autopilot_simulate_only)}, "
            f"approval above risk {_float('require_approval_above_risk', settings.autopilot_require_approval_above_risk):.0f}."
        ),
    }

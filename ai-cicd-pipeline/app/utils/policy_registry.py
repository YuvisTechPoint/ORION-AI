"""Org / repo / environment policy registry for Policy-as-code."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.utils.policy_engine import DEFAULT_POLICIES


def _parse_rules_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _scope_block(rules: dict[str, Any], key: str) -> dict[str, Any]:
    block = rules.get(key) or {}
    return block if isinstance(block, dict) else {}


def resolve_effective_policies(
    *,
    org: str,
    repo: str,
    environment: str,
) -> list[dict[str, Any]]:
    """Merge default, org, repo, and environment policies (later scopes override same name)."""
    org_rules = _parse_rules_json(settings.policy_org_rules_json)
    repo_rules = _parse_rules_json(settings.policy_repo_rules_json)
    env_rules = _parse_rules_json(settings.policy_env_rules_json)

    merged: dict[str, dict[str, Any]] = {}
    for policy in DEFAULT_POLICIES:
        merged[str(policy.get("name") or "unnamed")] = dict(policy)

    for source in (
        _scope_block(org_rules, org),
        _scope_block(repo_rules, repo),
        _scope_block(env_rules, environment),
    ):
        for policy in source.get("policies") or []:
            if isinstance(policy, dict) and policy.get("name"):
                merged[str(policy["name"])] = policy

    return list(merged.values())


def resolve_ai_autonomy_caps(
    *,
    org: str,
    repo: str,
    environment: str,
) -> dict[str, Any]:
    """Most restrictive AI autonomy caps across org, repo, and environment scopes."""
    org_rules = _parse_rules_json(settings.policy_org_rules_json)
    repo_rules = _parse_rules_json(settings.policy_repo_rules_json)
    env_rules = _parse_rules_json(settings.policy_env_rules_json)

    caps: dict[str, Any] = {
        "max_level": settings.policy_ai_autonomy_max_level or settings.remediation_autonomy_max_level or "L4",
        "auto_pr_allowed": True,
        "l5_retry_allowed": settings.remediation_l5_auto_retry_enabled,
        "l6_deploy_allowed": settings.remediation_l6_auto_deploy_enabled,
        "min_patch_confidence": 70,
    }

    for block in (
        _scope_block(org_rules, org).get("ai_autonomy") or {},
        _scope_block(repo_rules, repo).get("ai_autonomy") or {},
        _scope_block(env_rules, environment).get("ai_autonomy") or {},
    ):
        if not isinstance(block, dict):
            continue
        if block.get("max_level"):
            caps["max_level"] = str(block["max_level"]).upper()
        if "auto_pr_allowed" in block:
            caps["auto_pr_allowed"] = bool(block["auto_pr_allowed"])
        if "l5_retry_allowed" in block:
            caps["l5_retry_allowed"] = bool(block["l5_retry_allowed"])
        if "l6_deploy_allowed" in block:
            caps["l6_deploy_allowed"] = bool(block["l6_deploy_allowed"])
        if block.get("min_patch_confidence") is not None:
            caps["min_patch_confidence"] = int(block["min_patch_confidence"])

    if environment == "production" and not _scope_block(env_rules, environment).get("ai_autonomy"):
        caps["max_level"] = min_level(caps["max_level"], "L3")
        caps["l6_deploy_allowed"] = False

    return caps


def min_level(a: str, b: str) -> str:
    from app.utils.remediation_levels import level_rank

    return a if level_rank(a) <= level_rank(b) else b


def build_policy_registry_report(
    *,
    org: str,
    repo: str,
    environment: str,
) -> dict[str, Any]:
    policies = resolve_effective_policies(org=org, repo=repo, environment=environment)
    autonomy = resolve_ai_autonomy_caps(org=org, repo=repo, environment=environment)
    return {
        "org": org,
        "repo": repo,
        "environment": environment,
        "policy_count": len(policies),
        "policies": [{"name": p.get("name"), "deny_if": p.get("deny_if"), "require": p.get("require")} for p in policies],
        "ai_autonomy": autonomy,
        "sources": {
            "org_rules_configured": bool(_parse_rules_json(settings.policy_org_rules_json)),
            "repo_rules_configured": bool(_parse_rules_json(settings.policy_repo_rules_json)),
            "env_rules_configured": bool(_parse_rules_json(settings.policy_env_rules_json)),
        },
        "summary": f"{len(policies)} effective policy/policies for {repo}@{environment}; AI max {autonomy['max_level']}.",
    }

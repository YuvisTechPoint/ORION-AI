"""Enterprise approval workflow resolution (org / repo / environment)."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _block(rules: dict[str, Any], key: str) -> dict[str, Any]:
    block = rules.get(key) or {}
    return block if isinstance(block, dict) else {}


def resolve_approval_workflow(
    *,
    org: str,
    repo: str,
    environment: str,
    change_risk_score: int | None = None,
) -> dict[str, Any]:
    org_rules = _parse_json(settings.approval_org_workflow_json)
    repo_rules = _parse_json(settings.approval_repo_workflow_json)
    env_rules = _parse_json(settings.approval_env_workflow_json)

    workflow: dict[str, Any] = {
        "required_approvals": max(1, int(settings.approval_required_count or 1)),
        "four_eyes": settings.approval_four_eyes_enabled,
        "signed_approvals": settings.approval_signed_required,
        "roles": ["release_manager"],
        "separation_from_committer": settings.approval_four_eyes_enabled,
        "environment": environment,
    }

    for block in (
        _block(org_rules, org),
        _block(repo_rules, repo),
        _block(env_rules, environment),
    ):
        if block.get("required_approvals") is not None:
            workflow["required_approvals"] = max(1, int(block["required_approvals"]))
        if "four_eyes" in block:
            workflow["four_eyes"] = bool(block["four_eyes"])
        if "signed_approvals" in block:
            workflow["signed_approvals"] = bool(block["signed_approvals"])
        if block.get("roles"):
            workflow["roles"] = list(block["roles"])

    risk = int(change_risk_score or 0)
    if risk >= int(settings.approval_high_risk_threshold):
        workflow["required_approvals"] = max(
            int(workflow["required_approvals"]),
            int(settings.approval_high_risk_required_count),
        )
        workflow["four_eyes"] = True

    if environment == "production" and not _block(env_rules, environment):
        workflow["required_approvals"] = max(int(workflow["required_approvals"]), 2)
        workflow["four_eyes"] = True

    workflow["summary"] = (
        f"{workflow['required_approvals']} approval(s), four-eyes={workflow['four_eyes']}, "
        f"signed={workflow['signed_approvals']}."
    )
    return workflow

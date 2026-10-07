"""AI autonomy policy evaluation — caps auto-PR, retry, and deploy autonomy."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.policy_registry import resolve_ai_autonomy_caps
from app.utils.remediation_levels import level_rank


def evaluate_ai_autonomy_policies(
    *,
    org: str,
    repo: str,
    environment: str,
    artifacts: dict[str, dict[str, Any]],
    remediation_intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    caps = resolve_ai_autonomy_caps(org=org, repo=repo, environment=environment)
    remediation = remediation_intelligence or artifacts.get("remediation_intelligence") or {}
    autonomy = remediation.get("autonomy") or {}
    achieved = str(autonomy.get("achieved_level") or "L0").upper()
    patch = remediation.get("patch") or {}
    confidence = patch.get("aggregate_confidence") or artifacts.get("patch_confidence_report") or {}
    action = str(confidence.get("action") or "")
    score = int(confidence.get("patch_confidence") or 0)

    violations: list[dict[str, Any]] = []

    if level_rank(achieved) > level_rank(str(caps.get("max_level") or "L4")):
        violations.append(
            {
                "rule": "max_autonomy_level",
                "detail": f"achieved {achieved} exceeds policy cap {caps['max_level']}",
            }
        )

    if action == "auto_pr" and not caps.get("auto_pr_allowed", True):
        violations.append({"rule": "auto_pr_denied", "detail": "auto-PR action blocked by AI autonomy policy"})

    if score and score < int(caps.get("min_patch_confidence") or 0):
        violations.append(
            {
                "rule": "min_patch_confidence",
                "detail": f"patch confidence {score}% below minimum {caps['min_patch_confidence']}%",
            }
        )

    if settings.remediation_l5_auto_retry_enabled and not caps.get("l5_retry_allowed"):
        violations.append({"rule": "l5_retry_denied", "detail": "L5 auto-retry enabled globally but denied by policy"})

    if settings.remediation_l6_auto_deploy_enabled and not caps.get("l6_deploy_allowed"):
        violations.append({"rule": "l6_deploy_denied", "detail": "L6 auto-deploy enabled globally but denied by policy"})

    agent_eval = artifacts.get("agent_eval_report") or {}
    if settings.agent_eval_gate_enabled and agent_eval.get("passed") is False:
        violations.append(
            {
                "rule": "agent_eval_gate",
                "detail": f"agent eval score {agent_eval.get('score')} below minimum",
            }
        )

    passed = len(violations) == 0
    return {
        "passed": passed,
        "caps": caps,
        "achieved_level": achieved,
        "patch_action": action or None,
        "patch_confidence": score or None,
        "violations": violations,
        "violation_count": len(violations),
        "summary": (
            f"AI autonomy policy passed (cap {caps['max_level']})."
            if passed
            else f"AI autonomy policy: {len(violations)} violation(s)."
        ),
    }

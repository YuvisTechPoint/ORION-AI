"""Autonomous remediation autonomy levels L0–L6."""

from __future__ import annotations

from typing import Any

REMEDIATION_LEVELS: dict[str, dict[str, Any]] = {
    "L0": {
        "label": "Explain",
        "description": "Diagnostics, evidence, and gate summaries for operators.",
        "capabilities": ["run_diagnostics", "devops_rag", "artifact_review"],
    },
    "L1": {
        "label": "Recommend",
        "description": "Actionable remediation steps and runbook matches.",
        "capabilities": ["remediation_steps", "runbook_automation", "operator_playbook"],
    },
    "L2": {
        "label": "Patch proposal",
        "description": "AI-generated patches without sandbox verification.",
        "capabilities": ["ai_patch_generation"],
    },
    "L3": {
        "label": "Patch + verify",
        "description": "Sandbox-applied patches with confidence scoring.",
        "capabilities": ["fix_loop", "agent_sandbox", "patch_confidence"],
    },
    "L4": {
        "label": "Auto-PR",
        "description": "High-confidence patches opened as fix PRs on GitHub.",
        "capabilities": ["auto_pr", "fix_branches"],
    },
    "L5": {
        "label": "Auto test + retry",
        "description": "Policy-gated pipeline retry after merge (deferred by default).",
        "capabilities": ["pipeline_retry"],
        "deferred": True,
    },
    "L6": {
        "label": "Auto deploy",
        "description": "Autonomous deploy after verified fix (deferred by default).",
        "capabilities": ["autonomous_deploy"],
        "deferred": True,
    },
}


def level_rank(level: str) -> int:
    key = (level or "L0").strip().upper()
    if not key.startswith("L"):
        key = f"L{key}"
    try:
        return int(key[1:])
    except ValueError:
        return 0


def resolve_max_level(max_level: str | None) -> str:
    key = (max_level or "L4").strip().upper()
    if key not in REMEDIATION_LEVELS:
        return "L4"
    return key


def list_remediation_levels() -> list[dict[str, Any]]:
    return [
        {"level": level, **meta}
        for level, meta in REMEDIATION_LEVELS.items()
    ]

"""AI governance registry — escalation policies, confidence thresholds, and control catalog."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

DEFAULT_ESCALATION_RULES: list[dict[str, Any]] = [
    {
        "id": "low_agent_eval",
        "condition": "agent_eval_aggregate_below_threshold",
        "severity": "high",
        "action": "human_review",
    },
    {
        "id": "low_approval_confidence",
        "condition": "approval_confidence_below_threshold",
        "severity": "high",
        "action": "human_review",
    },
    {
        "id": "llm_fallback",
        "condition": "llm_error_or_heuristic_fallback",
        "severity": "medium",
        "action": "monitor",
    },
    {
        "id": "high_risk_deploy",
        "condition": "change_risk_above_threshold",
        "severity": "high",
        "action": "approver_required",
    },
    {
        "id": "prompt_injection",
        "condition": "prompt_injection_blocked",
        "severity": "critical",
        "action": "block_pipeline",
    },
]

GOVERNANCE_CONTROLS: list[dict[str, str]] = [
    {"id": "model_router", "label": "Model routing plan", "artifact": "model_routing_plan"},
    {"id": "prompt_registry", "label": "Prompt versioning", "artifact": "prompt_registry_snapshot"},
    {"id": "agent_eval", "label": "AgentEval quality scoring", "artifact": "agent_eval_report"},
    {"id": "decision_ledger", "label": "Decision ledger", "artifact": "decision_ledger"},
    {"id": "cost_optimizer", "label": "AI cost optimization", "artifact": "ai_cost_optimization"},
    {"id": "sandbox_policy", "label": "Agent sandbox policy", "artifact": "sandbox_policy_report"},
    {"id": "permissions", "label": "Agent permissions", "artifact": "agent_permissions_report"},
]


def _parse_policy_json() -> dict[str, Any]:
    raw = (settings.ai_governance_policy_json or "").strip()
    if not raw or raw == "{}":
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def build_governance_policy_catalog() -> dict[str, Any]:
    custom = _parse_policy_json()
    rules = custom.get("escalation_rules") if isinstance(custom.get("escalation_rules"), list) else DEFAULT_ESCALATION_RULES
    return {
        "controls": GOVERNANCE_CONTROLS,
        "escalation_rules": rules,
        "min_confidence": float(custom.get("min_confidence", settings.ai_governance_min_confidence)),
        "escalation_threshold": float(
            custom.get("escalation_threshold", settings.ai_governance_escalation_threshold)
        ),
        "agent_eval_min_score": settings.agent_eval_min_score,
        "model_router_enabled": settings.model_router_enabled,
        "summary": f"AI governance policy: {len(rules)} escalation rule(s), {len(GOVERNANCE_CONTROLS)} control(s).",
    }

"""AI cost optimization recommendations from FinOps signals."""

from __future__ import annotations

from typing import Any

from app.config import settings


def optimize_ai_cost(
    *,
    cost_report: dict[str, Any] | None,
    model_plan: dict[str, Any] | None,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cost_report = cost_report or {}
    model_plan = model_plan or {}
    recommendations: list[dict[str, Any]] = []

    llm_usd = float((cost_report.get("breakdown") or {}).get("llm_usd") or 0)
    tokens = int(cost_report.get("llm_tokens") or 0)
    complexity = model_plan.get("complexity", "medium")

    if tokens > 8000 and complexity == "low":
        recommendations.append(
            {
                "action": "downgrade_model",
                "target": settings.small_model_slug,
                "savings_estimate_percent": 40,
                "reason": "High token usage on low-complexity change — route lint tasks to small model",
            }
        )

    for key in ("code_analysis", "security_scan"):
        block = artifacts.get(key) or {}
        if int(block.get("tokens_used") or 0) > 3000 and block.get("analysis_mode") == "llm":
            recommendations.append(
                {
                    "action": "prefer_heuristic",
                    "target": key,
                    "savings_estimate_percent": 100,
                    "reason": f"{key}: scanner/heuristic sufficient when gates are deterministic",
                }
            )

    if llm_usd < 0.01:
        recommendations.append(
            {
                "action": "no_change",
                "reason": "LLM spend negligible for this run",
            }
        )

    total_savings = sum(r.get("savings_estimate_percent", 0) for r in recommendations if r["action"] != "no_change")
    return {
        "recommendations": recommendations[:6],
        "current_llm_usd": llm_usd,
        "potential_savings_percent": min(80, total_savings),
        "summary": f"AI cost optimizer: {len(recommendations)} recommendation(s).",
    }

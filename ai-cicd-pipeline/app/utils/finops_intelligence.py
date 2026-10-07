"""FinOps intelligence — cost rollup, allocation, budget gates, and optimization overlay."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.ai_cost_optimizer import optimize_ai_cost
from app.utils.finops import compute_pipeline_cost
from app.utils.finops_registry import resolve_finops_budgets


def _token_breakdown(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, content in artifacts.items():
        if not isinstance(content, dict):
            continue
        tokens = int(content.get("tokens_used") or 0)
        if tokens:
            model = content.get("agent_model") or content.get("model") or "unknown"
            rows.append(
                {
                    "artifact": key,
                    "tokens": tokens,
                    "model": model,
                    "analysis_mode": content.get("analysis_mode"),
                    "estimated_usd": round(
                        tokens / 1000 * settings.finops_llm_cost_per_1k_tokens, 4
                    ),
                }
            )
    rows.sort(key=lambda r: r["tokens"], reverse=True)
    return rows


def build_fleet_cost_rollup(run_costs: list[dict[str, Any]]) -> dict[str, Any]:
    if not run_costs:
        return {
            "run_count": 0,
            "total_usd": 0.0,
            "avg_usd_per_run": 0.0,
            "by_repository": {},
            "summary": "Fleet FinOps: no runs in window.",
        }
    total = sum(float(r.get("total_usd_estimate") or 0) for r in run_costs)
    by_repo: dict[str, float] = {}
    for row in run_costs:
        repo = row.get("repository") or "unknown"
        by_repo[repo] = by_repo.get(repo, 0.0) + float(row.get("total_usd_estimate") or 0)
    top_repos = sorted(by_repo.items(), key=lambda x: x[1], reverse=True)[:8]
    return {
        "run_count": len(run_costs),
        "total_usd": round(total, 4),
        "avg_usd_per_run": round(total / len(run_costs), 4),
        "by_repository": {k: round(v, 4) for k, v in top_repos},
        "summary": f"Fleet FinOps: ${total:.4f} across {len(run_costs)} run(s).",
    }


def evaluate_finops_gates(
    *,
    run_cost_usd: float,
    fleet_month_usd: float,
    budgets: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    per_run = float(budgets.get("per_run_usd") or 0)
    monthly = float(budgets.get("monthly_usd") or 0)
    if per_run > 0 and run_cost_usd > per_run:
        violations.append(f"run cost ${run_cost_usd:.4f} exceeds per-run budget ${per_run:.2f}")
    if monthly > 0 and fleet_month_usd > monthly:
        violations.append(f"fleet month cost ${fleet_month_usd:.4f} exceeds monthly budget ${monthly:.2f}")

    if violations and settings.finops_gate_enabled:
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_finops_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    duration_seconds: float | None = None,
    artifacts: dict[str, dict[str, Any]] | None = None,
    fleet_costs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    budgets = resolve_finops_budgets(repo)

    cost = artifacts.get("cost_report")
    if not cost:
        cost = compute_pipeline_cost(
            run_id=run_id or "local",
            repo=repo,
            duration_seconds=duration_seconds,
            artifacts=artifacts,
            llm_cost_per_1k_tokens=settings.finops_llm_cost_per_1k_tokens,
            compute_cost_per_minute=settings.finops_compute_cost_per_minute,
        )

    token_rows = _token_breakdown(artifacts)
    model_plan = artifacts.get("model_routing_plan") or {}
    cost_opt = artifacts.get("ai_cost_optimization") or optimize_ai_cost(
        cost_report=cost,
        model_plan=model_plan,
        artifacts=artifacts,
    )

    fleet = build_fleet_cost_rollup(fleet_costs or [])
    fleet_month = fleet["total_usd"] if fleet_costs else float(cost.get("total_usd_estimate") or 0)
    run_usd = float(cost.get("total_usd_estimate") or 0)
    gates = evaluate_finops_gates(
        run_cost_usd=run_usd,
        fleet_month_usd=fleet_month,
        budgets=budgets,
    )

    utilization = {
        "per_run_budget_used_percent": round(100 * run_usd / budgets["per_run_usd"], 1)
        if budgets["per_run_usd"] > 0
        else None,
        "monthly_budget_used_percent": round(100 * fleet_month / budgets["monthly_usd"], 1)
        if budgets["monthly_usd"] > 0
        else None,
    }

    report: dict[str, Any] = {
        "run_id": run_id,
        "repository": repo,
        "cost_report": cost,
        "token_breakdown": token_rows,
        "token_total": sum(r["tokens"] for r in token_rows),
        "budgets": budgets,
        "utilization": utilization,
        "fleet_rollup": fleet if fleet_costs else None,
        "cost_optimization": cost_opt,
        "potential_savings_percent": cost_opt.get("potential_savings_percent", 0),
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"FinOps {gates['gate_verdict']}: run ${run_usd:.4f}, "
        f"{report['token_total']} tokens, savings potential {cost_opt.get('potential_savings_percent', 0)}%."
    )
    return report

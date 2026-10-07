"""Reliability intelligence — chaos, synthetic monitoring, error budget, and SLO fusion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.chaos_engineering import run_chaos_suite
from app.utils.error_budget import compute_error_budget
from app.utils.reliability_registry import resolve_reliability_policy
from app.utils.synthetic_monitoring import run_synthetic_checks


def compute_resilience_score(
    *,
    chaos: dict[str, Any],
    synthetic: dict[str, Any],
    error_budget: dict[str, Any],
) -> int:
    chaos_pts = int(chaos.get("avg_resilience_score") or 0) * 0.45
    syn_pts = 25 if synthetic.get("all_passed") else (10 if synthetic.get("passed", 0) > 0 else 0)
    budget_pts = 0
    remaining = error_budget.get("error_budget_remaining_percent")
    if remaining is not None:
        budget_pts = min(30, int(float(remaining) * 0.3))
    return min(100, int(chaos_pts + syn_pts + budget_pts))


def evaluate_reliability_gates(
    *,
    policy: dict[str, Any],
    resilience_score: int,
    chaos: dict[str, Any],
    synthetic: dict[str, Any],
    error_budget: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []

    min_score = float(policy.get("min_resilience_score") or 0)
    if resilience_score < min_score:
        violations.append(f"Resilience score {resilience_score}% below minimum {min_score:.0f}%")

    if not chaos.get("all_recovered", True):
        violations.append("Chaos suite: not all experiments recovered")

    if policy.get("require_synthetic_pass") and not synthetic.get("all_passed"):
        violations.append("Synthetic monitoring journeys did not all pass")

    if error_budget.get("freeze_risky_releases"):
        warnings.append("Error budget low — freeze risky releases recommended")

    if chaos.get("simulated") and not policy.get("simulated", True):
        warnings.append("Chaos ran in simulated mode; live experiments not executed")

    if violations and settings.reliability_gate_enabled:
        gate = "fail"
    elif violations or warnings:
        gate = "warn"
    else:
        gate = "pass"

    return {"gate_verdict": gate, "violations": violations, "warnings": warnings}


async def build_reliability_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    artifacts: dict[str, dict[str, Any]] | None = None,
    slo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    policy = resolve_reliability_policy(repo)

    chaos = artifacts.get("chaos_report")
    if not chaos:
        chaos = run_chaos_suite(
            simulated=policy.get("simulated", True),
            experiment_names=policy.get("experiment_names"),
        )

    synthetic = artifacts.get("synthetic_monitoring_report")
    if not synthetic:
        live = settings.synthetic_monitoring_live and not policy.get("simulated", True)
        synthetic = await run_synthetic_checks(simulated=not live)

    error_budget = artifacts.get("error_budget_report")
    if not error_budget and slo:
        error_budget = compute_error_budget(slo, target_availability=settings.slo_target_availability)
    elif not error_budget:
        error_budget = compute_error_budget(
            {"window_runs": 0, "success_rate": 1.0},
            target_availability=settings.slo_target_availability,
        )

    resilience_score = compute_resilience_score(
        chaos=chaos,
        synthetic=synthetic,
        error_budget=error_budget,
    )
    gates = evaluate_reliability_gates(
        policy=policy,
        resilience_score=resilience_score,
        chaos=chaos,
        synthetic=synthetic,
        error_budget=error_budget,
    )

    report: dict[str, Any] = {
        "run_id": run_id or None,
        "repository": repo or None,
        "policy": policy,
        "chaos_report": chaos,
        "synthetic_monitoring": synthetic,
        "error_budget": error_budget,
        "slo_snapshot": slo,
        "resilience_score": resilience_score,
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "heuristic" if chaos.get("simulated") else "live",
    }
    report["summary"] = (
        f"Reliability {gates['gate_verdict']}: score {resilience_score}%, "
        f"chaos {chaos.get('recovered', 0)}/{chaos.get('total', 0)} recovered, "
        f"synthetic {'pass' if synthetic.get('all_passed') else 'warn'}."
    )
    return report

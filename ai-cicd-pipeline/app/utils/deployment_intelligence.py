"""Deployment intelligence — environments, strategies, and SLO-driven rollback signals."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.environment_registry import build_environment_registry
from app.utils.rollback_intelligence import assess_rollback


def evaluate_slo_rollback_signals(
    *,
    deployment_info: dict[str, Any] | None,
    progressive_delivery: dict[str, Any] | None,
    error_budget_report: dict[str, Any] | None,
    stress_report: dict[str, Any] | None,
    change_risk_report: dict[str, Any] | None,
) -> dict[str, Any]:
    deployment_info = deployment_info or {}
    progressive_delivery = progressive_delivery or {}
    error_budget = error_budget_report or {}
    stress = stress_report or {}
    change_risk = change_risk_report or {}

    signals: list[str] = []
    if error_budget.get("freeze_risky_releases"):
        signals.append("error budget exhausted — freeze risky releases")
    if progressive_delivery and not progressive_delivery.get("passed", True):
        signals.append(f"{progressive_delivery.get('strategy', 'progressive')} rollout aborted")
    if str(stress.get("performance_verdict", "")).lower() == "fail":
        signals.append("stress test failed before deploy")
    if deployment_info.get("rollback"):
        signals.append("deployment rollback already executed")

    rollback = assess_rollback(
        metrics={
            "health_status_code": 200 if deployment_info.get("health_check_passed") else 503,
            "response_time_ms": float((stress or {}).get("p95_ms") or 0),
            "error_count": 0 if deployment_info.get("health_check_passed") else 5,
            "sample_size": 100,
        },
        deployment_info=deployment_info,
        change_risk=change_risk,
        baseline_metrics={
            "error_rate": 0.01,
            "p95_ms": float(stress.get("p95_ms") or 400),
        },
    )

    recommend = rollback.get("recommend_rollback") or bool(signals)
    verdict = "fail" if recommend and settings.deployment_slo_gate_enabled else "pass"
    if signals and not recommend:
        verdict = "warn"

    return {
        "signals": signals,
        "rollback_assessment": rollback,
        "error_budget_remaining_percent": error_budget.get("error_budget_remaining_percent"),
        "verdict": verdict,
        "summary": (
            f"SLO rollback {'recommended' if recommend else 'not required'}; "
            f"{len(signals)} signal(s)."
        ),
    }


def plan_deployment_strategy(
    *,
    deployment_info: dict[str, Any] | None,
    progressive_delivery: dict[str, Any] | None,
) -> dict[str, Any]:
    progressive = progressive_delivery or (deployment_info or {}).get("progressive_delivery") or {}
    strategy = progressive.get("strategy") or settings.deployment_strategy or "canary"
    if not settings.progressive_delivery_enabled:
        strategy = "direct"
    return {
        "selected": strategy,
        "progressive_delivery_enabled": settings.progressive_delivery_enabled,
        "canary_stages": [int(x) for x in settings.canary_stages.split(",") if x.strip().isdigit()],
        "blue_green": strategy == "blue_green",
        "direct": strategy == "direct",
        "final_traffic_percent": progressive.get("final_traffic_percent"),
        "passed": progressive.get("passed", True),
    }


def evaluate_deployment_gates(report: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    deploy = report.get("deployment") or {}
    if deploy.get("success") is False:
        violations.append("deployment failed")
    prog = report.get("progressive_delivery") or {}
    if prog and prog.get("passed") is False:
        violations.append(f"{prog.get('strategy', 'progressive')} delivery aborted")
    slo = report.get("slo_rollback") or {}
    if settings.deployment_slo_gate_enabled and slo.get("verdict") == "fail":
        violations.extend(slo.get("signals") or [])

    if violations and (deploy.get("success") is False or (settings.deployment_slo_gate_enabled and slo.get("verdict") == "fail")):
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_deployment_intelligence_report(
    *,
    deployment_info: dict[str, Any] | None = None,
    progressive_delivery: dict[str, Any] | None = None,
    error_budget_report: dict[str, Any] | None = None,
    stress_report: dict[str, Any] | None = None,
    change_risk_report: dict[str, Any] | None = None,
    rollback_intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deployment_info = deployment_info or {}
    progressive_delivery = progressive_delivery or deployment_info.get("progressive_delivery") or {}
    registry = build_environment_registry()
    strategy = plan_deployment_strategy(
        deployment_info=deployment_info,
        progressive_delivery=progressive_delivery,
    )
    slo = evaluate_slo_rollback_signals(
        deployment_info=deployment_info,
        progressive_delivery=progressive_delivery,
        error_budget_report=error_budget_report,
        stress_report=stress_report,
        change_risk_report=change_risk_report,
    )

    report: dict[str, Any] = {
        "environment_registry": registry,
        "deployment": {
            "success": deployment_info.get("success"),
            "simulated": deployment_info.get("simulated", False),
            "environment": deployment_info.get("environment"),
            "image_tag": deployment_info.get("image_tag"),
            "health_check_passed": deployment_info.get("health_check_passed"),
            "rollback": deployment_info.get("rollback"),
        },
        "progressive_delivery": progressive_delivery,
        "strategy": strategy,
        "slo_rollback": slo,
        "rollback_intelligence": rollback_intelligence or slo.get("rollback_assessment"),
        "analysis_mode": "heuristic",
    }
    report["gates"] = evaluate_deployment_gates(report)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = (
        f"Deploy {report['gate_verdict']}: env={deployment_info.get('environment')}, "
        f"strategy={strategy.get('selected')}, slo={slo.get('verdict')}."
    )
    return report

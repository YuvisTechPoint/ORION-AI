"""Unified policy intelligence — scoped policies, evaluation, and AI autonomy."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.ai_autonomy_policy import evaluate_ai_autonomy_policies
from app.utils.policy_engine import evaluate_policies
from app.utils.policy_registry import build_policy_registry_report, resolve_effective_policies


def evaluate_policy_gates(
    policy_evaluation: dict[str, Any],
    ai_autonomy: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    if not policy_evaluation.get("passed", True):
        violations.extend(
            v.get("detail", str(v)) if isinstance(v, dict) else str(v)
            for v in policy_evaluation.get("violations") or []
        )
    if not ai_autonomy.get("passed", True):
        violations.extend(
            v.get("detail", str(v)) if isinstance(v, dict) else str(v)
            for v in ai_autonomy.get("violations") or []
        )

    if violations and (
        (not policy_evaluation.get("passed", True) and settings.policy_enforcement_enabled)
        or not ai_autonomy.get("passed", True)
    ):
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_policy_intelligence_report(
    *,
    org: str,
    repo: str,
    environment: str,
    artifacts: dict[str, dict[str, Any]],
    policy_evaluation: dict[str, Any] | None = None,
    unsigned_image: bool = False,
) -> dict[str, Any]:
    registry = build_policy_registry_report(org=org, repo=repo, environment=environment)
    policies = resolve_effective_policies(org=org, repo=repo, environment=environment)

    evaluation = policy_evaluation or evaluate_policies(
        artifacts,
        policies=policies,
        unsigned_image=unsigned_image,
        strict_requirements=settings.policy_strict_requirements,
    )

    ai_autonomy = evaluate_ai_autonomy_policies(
        org=org,
        repo=repo,
        environment=environment,
        artifacts=artifacts,
    )

    compliance = artifacts.get("compliance_report") or {}

    report: dict[str, Any] = {
        "registry": registry,
        "policy_evaluation": evaluation,
        "ai_autonomy_policy": ai_autonomy,
        "compliance_snapshot": {
            "overall_score_percent": compliance.get("overall_score_percent"),
            "packs": compliance.get("packs_evaluated") or settings.compliance_pack_list,
        },
        "defaults_included": len(resolve_effective_policies(org=org, repo=repo, environment=environment)),
        "analysis_mode": "heuristic",
    }
    report["gates"] = evaluate_policy_gates(evaluation, ai_autonomy)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = (
        f"Policy {report['gate_verdict']}: {evaluation.get('violation_count', 0)} policy + "
        f"{ai_autonomy.get('violation_count', 0)} AI autonomy violation(s); "
        f"{registry['policy_count']} scoped rule(s)."
    )
    return report

"""ORION Autopilot intelligence — unified policy-gated delivery plan."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.ai_autonomy_policy import evaluate_ai_autonomy_policies
from app.utils.autopilot_planner import plan_autopilot_actions, summarize_plan
from app.utils.autopilot_registry import resolve_autopilot_policy
from app.utils.gate_fusion import fuse_stage_results


def evaluate_autopilot_gates(
    *,
    policy: dict[str, Any],
    actions: list[dict[str, Any]],
    autonomy_policy: dict[str, Any],
    fusion: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []

    if not policy.get("enabled"):
        warnings.append("Autopilot disabled — plan is advisory only")

    if not autonomy_policy.get("passed"):
        for v in autonomy_policy.get("violations") or []:
            violations.append(v.get("detail") or str(v))

    denied_high = [
        a for a in actions if not a.get("allowed") and a.get("level") in {"L5", "L6"} and a.get("id") != "operator_escalation"
    ]
    if denied_high:
        warnings.append(f"{len(denied_high)} high-autonomy action(s) denied by policy")

    if fusion.get("verdict") == "fail" and any(a.get("allowed") and a.get("id") == "proceed_deploy" for a in actions):
        violations.append("Deploy action planned while gate fusion verdict is fail")

    if violations and settings.autopilot_gate_enabled:
        gate = "fail"
    elif violations or warnings:
        gate = "warn"
    else:
        gate = "pass"

    return {"gate_verdict": gate, "violations": violations, "warnings": warnings}


def build_autopilot_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    branch: str = "",
    commit: str = "",
    run_status: str = "",
    environment: str = "",
    artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    org = repo.split("/", 1)[0] if "/" in repo else ""
    policy = resolve_autopilot_policy(repo, environment or settings.deploy_environment)

    fusion = fuse_stage_results(
        code=artifacts.get("code_analysis"),
        security=artifacts.get("security_scan"),
        qa=artifacts.get("qa_report"),
        stress=artifacts.get("stress_report"),
    )
    autonomy_policy = evaluate_ai_autonomy_policies(
        org=org,
        repo=repo,
        environment=environment or settings.deploy_environment,
        artifacts=artifacts,
        remediation_intelligence=artifacts.get("remediation_intelligence"),
    )

    actions = plan_autopilot_actions(
        repo=repo,
        environment=environment or settings.deploy_environment,
        run_status=run_status,
        artifacts=artifacts,
    )
    gates = evaluate_autopilot_gates(
        policy=policy,
        actions=actions,
        autonomy_policy=autonomy_policy,
        fusion=fusion,
    )

    eligible = [a for a in actions if a.get("allowed")]
    primary = eligible[0] if eligible else (actions[0] if actions else None)

    report: dict[str, Any] = {
        "run_id": run_id or None,
        "repository": repo or None,
        "branch": branch or None,
        "commit": commit or None,
        "run_status": run_status or None,
        "policy": policy,
        "gate_fusion": fusion,
        "ai_autonomy_policy": autonomy_policy,
        "planned_actions": actions,
        "eligible_actions": eligible,
        "primary_action": primary,
        "simulate_only": policy.get("simulate_only", True),
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "heuristic",
    }
    report["summary"] = f"{summarize_plan(actions)} Gate {gates['gate_verdict']}."
    return report

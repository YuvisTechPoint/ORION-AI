"""ORION Autopilot action planner — policy-gated delivery and remediation plans."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.autopilot_registry import resolve_autopilot_policy
from app.utils.gate_fusion import fuse_stage_results
from app.utils.remediation_levels import level_rank


def _action(
    action_id: str,
    *,
    level: str,
    allowed: bool,
    reason: str,
    execute_mode: str,
    priority: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "level": level,
        "allowed": allowed,
        "execute_mode": execute_mode,
        "priority": priority,
        "reason": reason,
        "metadata": metadata or {},
    }


def _level_allowed(policy: dict[str, Any], level: str) -> bool:
    return level_rank(level) <= int(policy.get("max_autonomy_rank") or 4)


def plan_autopilot_actions(
    *,
    repo: str,
    environment: str,
    run_status: str,
    artifacts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    policy = resolve_autopilot_policy(repo, environment)
    if not policy.get("enabled"):
        return [
            _action(
                "autopilot_disabled",
                level="L0",
                allowed=False,
                reason="Autopilot disabled by policy",
                execute_mode="skipped",
                priority=0,
            )
        ]

    simulate = bool(policy.get("simulate_only"))
    actions: list[dict[str, Any]] = []

    fusion = fuse_stage_results(
        code=artifacts.get("code_analysis"),
        security=artifacts.get("security_scan"),
        qa=artifacts.get("qa_report"),
        stress=artifacts.get("stress_report"),
    )
    change_risk = artifacts.get("change_risk_report") or {}
    risk_score = float(change_risk.get("final_risk") or fusion.get("risk_score") or 0)
    release_intel = artifacts.get("release_intelligence") or {}
    remediation = artifacts.get("remediation_intelligence") or {}
    patch = remediation.get("patch") or artifacts.get("patch_confidence_report") or {}
    autonomy = remediation.get("autonomy") or {}
    achieved = str(autonomy.get("achieved_level") or "L0")

    approval_required = risk_score >= float(policy.get("require_approval_above_risk") or 60)

    if run_status.startswith("blocked_") or fusion.get("verdict") == "fail":
        actions.append(
            _action(
                "explain_blocker",
                level="L0",
                allowed=True,
                reason="Always allowed — explain gate blockers and evidence",
                execute_mode="simulated" if simulate else "eligible",
                priority=1,
                metadata={"status": run_status, "violations": fusion.get("violations", [])[:5]},
            )
        )
        if patch.get("bundles") or patch.get("patch_confidence"):
            allowed = _level_allowed(policy, "L4") and policy.get("auto_pr_allowed", True)
            actions.append(
                _action(
                    "open_auto_pr",
                    level="L4",
                    allowed=allowed,
                    reason="Patch confidence path available" if allowed else "Auto-PR denied by autopilot policy",
                    execute_mode="simulated" if simulate or not allowed else "eligible",
                    priority=2,
                    metadata={"patch_action": patch.get("action"), "confidence": patch.get("patch_confidence")},
                )
            )
        retry_ok = _level_allowed(policy, "L5") and policy.get("retry_allowed", False)
        actions.append(
            _action(
                "pipeline_retry",
                level="L5",
                allowed=retry_ok,
                reason="Retry after remediation" if retry_ok else "L5 retry not allowed by policy",
                execute_mode="simulated" if simulate or not retry_ok else "eligible",
                priority=3,
            )
        )
        if artifacts.get("full_scan_combined") or artifacts.get("stress_report"):
            resume_ok = _level_allowed(policy, "L5")
            actions.append(
                _action(
                    "resume_checkpoint",
                    level="L5",
                    allowed=resume_ok,
                    reason="Checkpoint artifacts present" if resume_ok else "Resume exceeds autonomy cap",
                    execute_mode="simulated" if simulate or not resume_ok else "eligible",
                    priority=4,
                )
            )
        return sorted(actions, key=lambda a: a["priority"])

    # Success / pre-deploy path
    if approval_required or release_intel.get("gate_verdict") in {"warn", "fail"}:
        actions.append(
            _action(
                "operator_escalation",
                level="L0",
                allowed=True,
                reason=f"Risk {risk_score:.0f} or release gate requires approver",
                execute_mode="simulated" if simulate else "eligible",
                priority=1,
                metadata={"risk_score": risk_score, "release_gate": release_intel.get("gate_verdict")},
            )
        )

    deploy_ok = _level_allowed(policy, "L6") and policy.get("deploy_allowed", True)
    actions.append(
        _action(
            "proceed_deploy",
            level="L6",
            allowed=deploy_ok and not approval_required,
            reason="Gates passed — proceed to deploy" if deploy_ok else "Deploy denied by autopilot policy",
            execute_mode="simulated" if simulate or not deploy_ok or approval_required else "eligible",
            priority=2,
            metadata={"achieved_autonomy": achieved},
        )
    )

    if settings.progressive_delivery_enabled:
        actions.append(
            _action(
                "progressive_canary",
                level="L6",
                allowed=deploy_ok and _level_allowed(policy, "L6"),
                reason="Progressive delivery enabled",
                execute_mode="simulated" if simulate else "eligible",
                priority=3,
            )
        )

    actions.append(
        _action(
            "post_deploy_monitor",
            level="L1",
            allowed=True,
            reason="Standard post-deploy monitoring window",
            execute_mode="simulated" if simulate else "eligible",
            priority=4,
        )
    )

    monitoring = artifacts.get("monitoring_summary") or {}
    if monitoring.get("final_status") in {"degraded", "critical"}:
        actions.append(
            _action(
                "incident_rollback",
                level="L6",
                allowed=_level_allowed(policy, "L6") and policy.get("deploy_allowed", True),
                reason="Monitoring degradation detected",
                execute_mode="simulated" if simulate else "eligible",
                priority=0,
            )
        )

    return sorted(actions, key=lambda a: a["priority"])


def summarize_plan(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "Autopilot: no actions planned."
    allowed = sum(1 for a in actions if a.get("allowed"))
    return f"Autopilot plan: {len(actions)} action(s), {allowed} policy-eligible."

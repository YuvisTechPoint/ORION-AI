"""Unified enterprise approval intelligence report."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.approval_workflow import resolve_approval_workflow
from app.utils.enterprise_approval import evaluate_enterprise_approval


def evaluate_approval_gates(
    automated_approval: dict[str, Any],
    enterprise_approval: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    if str(automated_approval.get("decision", "")).lower() != "approved":
        violations.append("automated approval rejected")
    violations.extend(enterprise_approval.get("violations") or [])

    if violations and not enterprise_approval.get("ready_for_deploy"):
        gate = "fail" if settings.enterprise_approval_enforcement_enabled else "warn"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_approval_intelligence_report(
    *,
    org: str,
    repo: str,
    environment: str,
    commit: str,
    committer: str,
    automated_approval: dict[str, Any],
    enterprise_approval: dict[str, Any] | None = None,
    change_risk_score: int | None = None,
) -> dict[str, Any]:
    workflow = resolve_approval_workflow(
        org=org,
        repo=repo,
        environment=environment,
        change_risk_score=change_risk_score,
    )
    enterprise = enterprise_approval or evaluate_enterprise_approval(
        {
            "run_id": "",
            "committer": committer,
            "workflow": workflow,
            "automated_approval": automated_approval,
            "signoffs": [],
        }
    )
    if enterprise_approval:
        enterprise = {**enterprise_approval, **evaluate_enterprise_approval(enterprise_approval)}

    report: dict[str, Any] = {
        "workflow": workflow,
        "automated_approval": automated_approval,
        "enterprise_approval": enterprise,
        "four_eyes_enabled": workflow.get("four_eyes"),
        "signed_approvals_required": workflow.get("signed_approvals"),
        "analysis_mode": "heuristic",
    }
    report["gates"] = evaluate_approval_gates(automated_approval, enterprise)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = (
        f"Approval {report['gate_verdict']}: auto={automated_approval.get('decision')}, "
        f"enterprise={enterprise.get('status')} "
        f"({enterprise.get('received_approvals', 0)}/{enterprise.get('required_approvals', 1)})."
    )
    return report

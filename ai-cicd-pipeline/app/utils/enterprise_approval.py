"""Enterprise approval — multi-person sign-offs, four-eyes, and signed tokens."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

from app.config import settings


def _signature_secret() -> str:
    return (settings.approval_signature_secret or settings.secret_key or "orion-approval").strip()


def sign_approval_token(*, run_id: str, approver: str, role: str, timestamp: str) -> str:
    payload = f"{run_id}|{approver}|{role}|{timestamp}"
    digest = hmac.new(_signature_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return digest


def verify_approval_token(*, run_id: str, approver: str, role: str, timestamp: str, token: str) -> bool:
    expected = sign_approval_token(run_id=run_id, approver=approver, role=role, timestamp=timestamp)
    return hmac.compare_digest(expected, token or "")


def initialize_enterprise_approval(
    *,
    run_id: str,
    repo: str,
    commit: str,
    committer: str,
    automated_approval: dict[str, Any],
    workflow: dict[str, Any],
    simulated_signoffs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "run_id": run_id,
        "repo": repo,
        "commit": commit,
        "committer": committer,
        "workflow": workflow,
        "automated_approval": {
            "decision": automated_approval.get("decision"),
            "confidence": automated_approval.get("confidence"),
            "risk_level": automated_approval.get("risk_level"),
        },
        "signoffs": list(simulated_signoffs or []),
        "created_at": now,
        "updated_at": now,
    }
    status = evaluate_enterprise_approval(record)
    record.update(status)
    return record


def record_signoff(
    record: dict[str, Any],
    *,
    approver: str,
    role: str,
    comment: str = "",
    token: str | None = None,
) -> dict[str, Any]:
    run_id = str(record.get("run_id") or "")
    workflow = record.get("workflow") or {}
    now = datetime.now(timezone.utc).isoformat()
    entry: dict[str, Any] = {
        "approver": approver,
        "role": role,
        "comment": comment[:500],
        "timestamp": now,
        "signed": bool(workflow.get("signed_approvals")),
    }
    if workflow.get("signed_approvals"):
        entry["signature"] = sign_approval_token(run_id=run_id, approver=approver, role=role, timestamp=now)

    signoffs = list(record.get("signoffs") or [])
    signoffs = [s for s in signoffs if s.get("approver") != approver]
    signoffs.append(entry)

    updated = dict(record)
    updated["signoffs"] = signoffs
    updated["updated_at"] = now
    status = evaluate_enterprise_approval(updated)
    updated.update(status)
    return updated


def evaluate_enterprise_approval(record: dict[str, Any]) -> dict[str, Any]:
    workflow = record.get("workflow") or {}
    automated = (record.get("automated_approval") or {}).get("decision")
    signoffs = list(record.get("signoffs") or [])
    required = max(1, int(workflow.get("required_approvals") or 1))
    committer = str(record.get("committer") or "")

    violations: list[str] = []
    if str(automated or "").lower() != "approved":
        violations.append("automated ApprovalAgent did not approve")

    unique_approvers = {s.get("approver") for s in signoffs if s.get("approver")}
    if len(unique_approvers) < required:
        violations.append(f"need {required - len(unique_approvers)} more approver(s)")

    if workflow.get("four_eyes") or workflow.get("separation_from_committer"):
        if committer and any(str(s.get("approver")) == committer for s in signoffs):
            violations.append("four-eyes violation: committer cannot approve their own change")

    roles_required = workflow.get("roles") or []
    if roles_required:
        covered = {str(s.get("role")) for s in signoffs}
        missing_roles = [r for r in roles_required if r not in covered]
        if missing_roles and len(unique_approvers) < required:
            violations.append(f"missing role sign-off: {', '.join(missing_roles[:3])}")

    ready = not violations and len(unique_approvers) >= required
    status = "approved" if ready else ("pending" if not violations or len(unique_approvers) < required else "rejected")

    return {
        "status": status,
        "ready_for_deploy": ready,
        "required_approvals": required,
        "received_approvals": len(unique_approvers),
        "violations": violations,
        "summary": (
            f"Enterprise approval {status}: {len(unique_approvers)}/{required} sign-off(s)."
            if not violations
            else f"Enterprise approval blocked: {'; '.join(violations[:3])}"
        ),
    }


def build_simulated_signoffs(workflow: dict[str, Any], *, committer: str) -> list[dict[str, Any]]:
    if not settings.enterprise_approval_simulated:
        return []
    now = datetime.now(timezone.utc).isoformat()
    roles = list(workflow.get("roles") or ["release_manager"])
    required = max(1, int(workflow.get("required_approvals") or 1))
    signoffs: list[dict[str, Any]] = []
    for idx in range(required):
        approver = f"simulated-approver-{idx + 1}@orion.local"
        if approver == committer:
            approver = f"simulated-reviewer-{idx + 1}@orion.local"
        role = roles[idx % len(roles)]
        token = sign_approval_token(run_id="sim", approver=approver, role=role, timestamp=now)
        signoffs.append(
            {
                "approver": approver,
                "role": role,
                "comment": "Simulated enterprise sign-off (dev mode)",
                "timestamp": now,
                "signed": bool(workflow.get("signed_approvals")),
                "signature": token if workflow.get("signed_approvals") else None,
                "simulated": True,
            }
        )
    return signoffs

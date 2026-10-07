"""Incident lifecycle states and transitions for the AI Incident Command Center."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VALID_INCIDENT_STATUSES = frozenset({"open", "investigating", "mitigated", "resolved", "closed"})

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"investigating", "closed"}),
    "investigating": frozenset({"mitigated", "resolved", "closed"}),
    "mitigated": frozenset({"resolved", "investigating", "closed"}),
    "resolved": frozenset({"closed", "investigating"}),
    "closed": frozenset({"investigating"}),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def initial_lifecycle(*, severity: str, source: str = "monitoring") -> dict[str, Any]:
    opened = _now_iso()
    status = "investigating" if severity in {"P1", "P2"} else "open"
    return {
        "status": status,
        "severity": severity,
        "source": source,
        "opened_at": opened,
        "updated_at": opened,
        "resolved_at": None,
        "closed_at": None,
        "history": [
            {
                "status": status,
                "at": opened,
                "note": f"Incident auto-opened from {source}",
            }
        ],
    }


def transition_lifecycle(
    lifecycle: dict[str, Any],
    new_status: str,
    *,
    note: str = "",
) -> dict[str, Any]:
    current = str(lifecycle.get("status") or "open")
    target = new_status.strip().lower()
    if target not in VALID_INCIDENT_STATUSES:
        raise ValueError(f"Invalid incident status: {target}")
    allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed and target != current:
        raise ValueError(f"Cannot transition from {current} to {target}")

    updated = dict(lifecycle)
    now = _now_iso()
    history = list(updated.get("history") or [])
    if target != current:
        history.append({"status": target, "at": now, "note": note or f"Status changed to {target}"})
        updated["status"] = target
        updated["updated_at"] = now
        if target == "resolved":
            updated["resolved_at"] = now
        if target == "closed":
            updated["closed_at"] = now

    updated["history"] = history[-30:]
    return updated


def incident_record_from_commander(
    commander: dict[str, Any],
    *,
    run_id: str,
    repo: str,
    branch: str,
    commit: str,
) -> dict[str, Any]:
    lifecycle = commander.get("lifecycle") or initial_lifecycle(
        severity=str(commander.get("severity") or "P3"),
        source="incident_commander",
    )
    return {
        "incident_id": commander.get("incident_id"),
        "run_id": run_id,
        "repo": repo,
        "branch": branch,
        "commit": commit,
        "severity": commander.get("severity"),
        "status": lifecycle.get("status"),
        "lifecycle": lifecycle,
        "summary": commander.get("summary"),
        "rca_summary": (commander.get("rca") or {}).get("summary"),
        "runbook_count": len((commander.get("runbooks") or {}).get("runbooks") or []),
        "postmortem_ready": bool((commander.get("postmortem") or {}).get("summary")),
    }

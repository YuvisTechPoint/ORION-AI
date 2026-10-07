"""Unified incident command center report — commander bundle + lifecycle + notifications."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.incident_lifecycle import incident_record_from_commander, initial_lifecycle


def evaluate_incident_gates(report: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    lifecycle = report.get("lifecycle") or {}
    severity = str(report.get("severity") or "P3").upper()
    status = lifecycle.get("status")

    if severity == "P1" and status in {"open", "investigating"}:
        violations.append("P1 incident requires active response")

    rca = report.get("rca") or {}
    confidence = (rca.get("primary_hypothesis") or {}).get("confidence") or 0
    if confidence < 0.5 and status not in {"resolved", "closed"}:
        violations.append("low RCA confidence — manual investigation recommended")

    runbooks = report.get("runbooks") or {}
    if severity in {"P1", "P2"} and not runbooks.get("runbooks"):
        violations.append("no matching runbooks for severity")

    if violations and severity == "P1" and status == "investigating":
        gate = "warn"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_incident_intelligence_report(
    commander: dict[str, Any],
    *,
    run_id: str,
    repo: str,
    branch: str,
    commit: str,
    slack_notified: bool = False,
) -> dict[str, Any]:
    if not commander.get("lifecycle"):
        commander = {
            **commander,
            "lifecycle": initial_lifecycle(
                severity=str(commander.get("severity") or "P3"),
                source="monitoring",
            ),
        }

    record = incident_record_from_commander(
        commander,
        run_id=run_id,
        repo=repo,
        branch=branch,
        commit=commit,
    )

    report: dict[str, Any] = {
        "incident_id": commander.get("incident_id"),
        "severity": commander.get("severity"),
        "lifecycle": commander.get("lifecycle"),
        "commander": {
            "status": commander.get("status"),
            "summary": commander.get("summary"),
            "analysis_mode": commander.get("analysis_mode"),
        },
        "rca": commander.get("rca"),
        "timeline": commander.get("timeline"),
        "postmortem": commander.get("postmortem"),
        "runbooks": commander.get("runbooks"),
        "evidence_graph": commander.get("evidence_graph"),
        "record": record,
        "notifications": {
            "slack_p0_sent": slack_notified,
            "slack_enabled": settings.slack_enabled,
            "p0_alerts_enabled": settings.incident_p0_slack_enabled,
        },
        "analysis_mode": commander.get("analysis_mode", "heuristic"),
    }
    report["gates"] = evaluate_incident_gates(report)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = (
        f"Incident {commander.get('incident_id')} {report['lifecycle'].get('status')}: "
        f"{commander.get('severity')} — {(commander.get('rca') or {}).get('summary', commander.get('summary', ''))}"
    )
    return report

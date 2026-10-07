"""Incident Commander — orchestrates RCA, timeline, evidence, runbooks, postmortem."""

from __future__ import annotations

from typing import Any

from app.utils.evidence_graph import build_evidence_graph
from app.utils.incident_lifecycle import initial_lifecycle
from app.utils.incident_timeline import build_incident_timeline
from app.utils.postmortem_generator import generate_postmortem
from app.utils.rca_engine import analyze_root_cause
from app.utils.runbook_automation import match_runbooks


def run_incident_commander(
    *,
    run_id: str,
    repo: str,
    branch: str,
    commit: str,
    artifacts: dict[str, dict[str, Any]],
    metrics: dict[str, Any] | None = None,
    log_excerpt: str = "",
) -> dict[str, Any]:
    graph = build_evidence_graph(
        run_id=run_id, repo=repo, commit=commit, branch=branch, artifacts=artifacts
    )
    rca = analyze_root_cause(metrics=metrics, artifacts=artifacts, log_excerpt=log_excerpt)
    timeline = build_incident_timeline(artifacts)
    runbooks = match_runbooks(log_excerpt, rca)
    postmortem = generate_postmortem(
        incident_id=graph["incident_id"],
        rca=rca,
        timeline=timeline,
        evidence_graph=graph,
        run_id=run_id,
    )

    severity = "P1" if metrics and metrics.get("health_status_code") not in (200, None) else "P2"
    if not metrics or metrics.get("error_count", 0) < 5:
        severity = "P3"

    lifecycle = initial_lifecycle(severity=severity, source="monitoring")

    return {
        "incident_id": graph["incident_id"],
        "severity": severity,
        "status": lifecycle["status"],
        "lifecycle": lifecycle,
        "evidence_graph": graph,
        "rca": rca,
        "timeline": timeline,
        "runbooks": runbooks,
        "postmortem": postmortem,
        "summary": rca.get("summary"),
        "analysis_mode": "heuristic",
    }

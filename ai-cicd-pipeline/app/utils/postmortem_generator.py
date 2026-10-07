"""Evidence-backed automated postmortem generation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def generate_postmortem(
    *,
    incident_id: str,
    rca: dict[str, Any],
    timeline: dict[str, Any],
    evidence_graph: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    primary = rca.get("primary_hypothesis") or {}
    return {
        "incident_id": incident_id,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": f"Incident {incident_id} linked to pipeline run {run_id[:8]}.",
        "impact": "Production/staging degradation detected by ORION monitoring.",
        "timeline_ref": timeline.get("timeline", [])[:20],
        "root_cause": primary.get("cause", "unknown"),
        "root_cause_confidence": primary.get("confidence"),
        "contributing_factors": [h.get("cause") for h in rca.get("hypotheses", [])[1:4]],
        "detection": "ORION MonitoringAgent alert during post-deploy window.",
        "response": "Automated rollback intelligence evaluated; operator may approve rollback.",
        "resolution": "See rollback_intelligence and deployment_info artifacts.",
        "evidence_nodes": evidence_graph.get("node_count", 0),
        "corrective_actions": [
            "Add regression test for affected component",
            "Tighten canary thresholds if progressive delivery aborted",
        ],
        "preventive_actions": [
            "Extend change-risk gate for high blast-radius paths",
            "Add synthetic check for affected user journey",
        ],
        "evidence_citations": rca.get("evidence", []),
        "analysis_mode": "heuristic",
    }

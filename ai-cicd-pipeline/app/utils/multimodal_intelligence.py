"""Unified multimodal intelligence — aggregate on-demand agent outputs on a run."""

from __future__ import annotations

from typing import Any

from app.utils.multimodal_registry import MULTIMODAL_ARTIFACT_TYPES, MULTIMODAL_AGENT_CATALOG, agent_entry
from app.utils.multimodal_router import route_multimodal_inputs

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0, "p1": 4, "p2": 3, "p3": 2, "p4": 1}


def _severity_value(content: dict[str, Any]) -> int:
    raw = str(content.get("severity") or content.get("incident_severity") or "").lower()
    if raw.startswith("p"):
        return _SEVERITY_RANK.get(raw, 2)
    return _SEVERITY_RANK.get(raw, 0)


def collect_multimodal_artifacts(artifacts: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {key: value for key, value in artifacts.items() if key in MULTIMODAL_ARTIFACT_TYPES and isinstance(value, dict)}


def evaluate_multimodal_gates(collected: dict[str, dict[str, Any]]) -> dict[str, Any]:
    violations: list[str] = []
    highest = 0
    for artifact_type, content in collected.items():
        sev = _severity_value(content)
        highest = max(highest, sev)
        if sev >= 3:
            violations.append(f"{artifact_type} severity {content.get('severity') or content.get('incident_severity')}")
        if artifact_type == "production_triage" and content.get("escalate_to_human"):
            violations.append("production triage requires human escalation")
        if artifact_type == "payment_analysis" and str(content.get("severity", "")).lower() == "critical":
            violations.append("critical payment reconciliation findings")

    if violations:
        gate = "fail" if highest >= 3 else "warn"
    else:
        gate = "pass" if collected else "warn"
    return {"gate_verdict": gate, "violations": violations, "highest_severity_rank": highest}


def build_multimodal_intelligence_report(
    *,
    artifacts: dict[str, dict[str, Any]],
    route_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    collected = collect_multimodal_artifacts(artifacts)
    agent_summaries: list[dict[str, Any]] = []
    for entry in MULTIMODAL_AGENT_CATALOG:
        content = collected.get(entry["artifact_type"])
        if not content:
            continue
        agent_summaries.append(
            {
                "agent_id": entry["id"],
                "artifact_type": entry["artifact_type"],
                "severity": content.get("severity") or content.get("incident_severity"),
                "summary": content.get("summary") or content.get("root_cause") or entry["name"],
                "escalate": bool(content.get("escalate_to_human")),
            }
        )

    routing = route_hint or {"summary": "No routing hint; artifacts only."}
    gates = evaluate_multimodal_gates(collected)
    primary = agent_summaries[0]["agent_id"] if len(agent_summaries) == 1 else None
    if not primary and routing.get("primary_agent"):
        primary = routing["primary_agent"]

    report: dict[str, Any] = {
        "agents_present": len(agent_summaries),
        "agent_summaries": agent_summaries,
        "artifacts": {key: {"summary": val.get("summary"), "severity": val.get("severity")} for key, val in collected.items()},
        "routing": routing,
        "primary_agent": primary,
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"Multimodal intel {gates['gate_verdict']}: {len(agent_summaries)} agent artifact(s)"
        + (f"; highest severity rank {gates['highest_severity_rank']}" if collected else "; no multimodal artifacts yet")
        + "."
    )
    if primary and agent_entry(primary):
        report["recommended_next_agent"] = primary
    return report


def build_route_report(*, artifacts: list[dict[str, Any]], text_input: str = "", preferred_agent: str | None = None) -> dict[str, Any]:
    return route_multimodal_inputs(artifacts=artifacts, text_input=text_input, preferred_agent=preferred_agent)

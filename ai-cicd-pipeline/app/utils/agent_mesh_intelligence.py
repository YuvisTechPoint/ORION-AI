"""Agent mesh intelligence — coverage, health, and orchestration overlay for a pipeline run."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.agent_mesh_registry import build_agent_mesh_registry
from app.utils.agent_mesh_router import route_mesh_intent
from app.utils.agent_mesh_topology import AGENT_DEPENDENCY_EDGES, build_mesh_topology


def _agents_observed(artifacts: dict[str, dict[str, Any]]) -> set[str]:
    registry = build_agent_mesh_registry()
    observed: set[str] = set()
    artifact_to_agent: dict[str, str] = {}
    for agent in registry["agents"]:
        for art in agent.get("output_artifacts") or []:
            artifact_to_agent[art] = agent["name"]
    for art_type in artifacts:
        if art_type in artifact_to_agent:
            observed.add(artifact_to_agent[art_type])
    if artifacts.get("full_scan_combined"):
        observed.update({"CodeAnalysisAgent", "SecurityAgent", "QAAgent"})
    if artifacts.get("agent_registry_snapshot"):
        observed.add("RagIntelligence")
    return observed


def evaluate_mesh_health(
    *,
    observed: set[str],
    blocked: bool = False,
    missing_critical: list[str] | None = None,
) -> dict[str, Any]:
    registry = build_agent_mesh_registry()
    pipeline_agents = {a["name"] for a in registry["agents"] if a.get("kind") == "pipeline"}
    coverage = len(observed & pipeline_agents) / max(len(pipeline_agents), 1)
    pct = round(coverage * 100, 1)
    violations: list[str] = []
    if missing_critical:
        violations.extend(missing_critical)
    if pct < settings.agent_mesh_min_coverage_percent:
        violations.append(f"mesh coverage {pct}% below {settings.agent_mesh_min_coverage_percent}%")
    if blocked:
        violations.append("pipeline blocked — mesh incomplete")
    if violations and settings.agent_mesh_gate_enabled:
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {
        "gate_verdict": gate,
        "coverage_percent": pct,
        "observed_count": len(observed),
        "pipeline_agent_count": len(pipeline_agents),
        "violations": violations,
    }


def build_agent_mesh_intelligence_report(
    *,
    artifacts: dict[str, dict[str, Any]] | None = None,
    intent: str = "",
    run_status: str = "",
) -> dict[str, Any]:
    artifacts = artifacts or {}
    registry = build_agent_mesh_registry()
    topology = build_mesh_topology()
    observed = _agents_observed(artifacts)
    blocked = str(run_status).startswith("blocked") or run_status in {"failed", "rejected", "rolled_back"}
    critical_pipeline = {"SecurityAgent", "ApprovalAgent", "DeploymentAgent"}
    missing_critical = [a for a in critical_pipeline if a not in observed and not blocked]
    health = evaluate_mesh_health(observed=observed, blocked=blocked, missing_critical=missing_critical)
    route = route_mesh_intent(intent) if intent.strip() else None

    active_edges = []
    for edge in AGENT_DEPENDENCY_EDGES:
        if edge["from"] in observed and edge["to"] in observed:
            active_edges.append({**edge, "active": True})
        elif edge["from"] in observed or edge["to"] in observed:
            active_edges.append({**edge, "active": False})

    return {
        "registry": {
            "total": registry["total"],
            "pipeline_count": registry["pipeline_count"],
            "multimodal_count": registry["multimodal_count"],
        },
        "topology": topology,
        "observed_agents": sorted(observed),
        "active_edges": active_edges,
        "route": route,
        "health": health,
        "gate_verdict": health["gate_verdict"],
        "analysis_mode": "heuristic",
        "summary": (
            f"Agent mesh {health['gate_verdict']}: {health['observed_count']}/{health['pipeline_agent_count']} "
            f"pipeline agents observed ({health['coverage_percent']}% coverage)."
        ),
    }

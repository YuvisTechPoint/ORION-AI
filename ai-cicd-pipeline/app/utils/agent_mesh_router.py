"""Agent mesh router — map intents and domain events to agent chains."""

from __future__ import annotations

import re
from typing import Any

from app.utils.agent_mesh_registry import build_agent_mesh_registry
from app.utils.agent_mesh_topology import DOMAIN_EVENTS

_INTENT_RULES: list[tuple[re.Pattern[str], list[str], str]] = [
    (re.compile(r"\b(security|vuln|cve|bandit|secret|sast|sca)\b", re.I), ["SecurityAgent", "RemediationIntelligenceAgent"], "security intent"),
    (re.compile(r"\b(test|qa|pytest|flaky|coverage)\b", re.I), ["QAAgent", "TestIntelligenceAgent", "SoftwareEngineerAgent"], "test intent"),
    (re.compile(r"\b(deploy|canary|rollback|docker|k8s|kubernetes)\b", re.I), ["DeploymentAgent", "CloudIntelligence", "DeploymentIntelligenceAgent"], "deploy intent"),
    (re.compile(r"\b(monitor|log|alert|slo|error budget|otel)\b", re.I), ["MonitoringAgent", "ObservabilityIntelligenceAgent"], "observability intent"),
    (re.compile(r"\b(incident|outage|p1|rca|postmortem)\b", re.I), ["IncidentIntelligenceAgent", "ProductionTriageAgent", "LogAnalysisAgent"], "incident intent"),
    (re.compile(r"\b(policy|compliance|soc2|approval)\b", re.I), ["PolicyIntelligenceAgent", "ApprovalAgent", "EnterpriseApprovalWorkflow"], "policy intent"),
    (re.compile(r"\b(catalog|service|idp|owner)\b", re.I), ["ServiceCatalogIntelligence", "RepositoryIntelligenceAgent"], "catalog intent"),
    (re.compile(r"\b(rag|memory|explain|why)\b", re.I), ["RagIntelligence"], "rag intent"),
    (re.compile(r"\b(payment|reconcile|stripe)\b", re.I), ["PaymentAgent"], "payment intent"),
    (re.compile(r"\b(dockerfile|container|image)\b", re.I), ["DockerfileAgent", "CloudIntelligence"], "container intent"),
]

_EVENT_AGENT_MAP: dict[str, list[str]] = {
    "commit_created": ["RepositoryIntelligenceAgent", "CodeAnalysisAgent", "SecurityAgent", "QAAgent"],
    "full_scan_completed": ["TestIntelligenceAgent", "PolicyIntelligenceAgent", "RemediationIntelligenceAgent"],
    "security_completed": ["ApprovalAgent", "RemediationIntelligenceAgent"],
    "qa_completed": ["SoftwareEngineerAgent", "TestIntelligenceAgent"],
    "stress_completed": ["PerformanceIntelligenceAgent", "ApprovalAgent"],
    "approval_decided": ["DeploymentAgent", "EnterpriseApprovalWorkflow"],
    "deployment_completed": ["MonitoringAgent", "ServiceCatalogIntelligence", "RagIntelligence"],
    "monitoring_alert": ["IncidentIntelligenceAgent", "ObservabilityIntelligenceAgent"],
    "incident_detected": ["IncidentIntelligenceAgent", "ProductionTriageAgent"],
    "policy_blocked": ["PolicyIntelligenceAgent", "RemediationIntelligenceAgent"],
    "auto_pr_opened": ["SoftwareEngineerAgent"],
}


def route_mesh_intent(intent: str, *, preferred_agent: str | None = None) -> dict[str, Any]:
    registry = build_agent_mesh_registry()
    by_name = registry["agents_by_name"]
    text = (intent or "").strip()
    matches: list[dict[str, Any]] = []

    if preferred_agent:
        agent = by_name.get(preferred_agent) or registry["agents_by_alias"].get(preferred_agent)
        if agent:
            matches.append({"agent": agent["name"], "score": 100, "reason": "preferred_agent"})

    for pattern, chain, reason in _INTENT_RULES:
        if pattern.search(text):
            for idx, name in enumerate(chain):
                if name in by_name:
                    matches.append({"agent": name, "score": 10 - idx, "reason": reason})

    # Deduplicate preserving order
    seen: set[str] = set()
    chain: list[dict[str, Any]] = []
    for item in sorted(matches, key=lambda m: m["score"], reverse=True):
        if item["agent"] in seen:
            continue
        seen.add(item["agent"])
        desc = by_name.get(item["agent"], {})
        chain.append({**item, "alias": desc.get("alias"), "capabilities": desc.get("capabilities", [])})

    if not chain and text:
        chain.append({"agent": "RagIntelligence", "score": 1, "reason": "default_fallback", "alias": "rag_intelligence"})

    return {
        "intent": text,
        "recommended_chain": chain[:6],
        "chain_length": min(len(chain), 6),
        "summary": f"Mesh route: {min(len(chain), 6)} agent(s) for intent.",
    }


def route_mesh_event(event_id: str) -> dict[str, Any]:
    registry = build_agent_mesh_registry()
    by_name = registry["agents_by_name"]
    known = {e["id"] for e in DOMAIN_EVENTS}
    if event_id not in known:
        return {
            "event_id": event_id,
            "known": False,
            "subscribers": [],
            "summary": f"Unknown domain event: {event_id}",
        }
    names = _EVENT_AGENT_MAP.get(event_id, [])
    subscribers = []
    for name in names:
        agent = by_name.get(name, {})
        subscribers.append(
            {
                "agent": name,
                "alias": agent.get("alias"),
                "subscriptions": agent.get("subscriptions", []),
                "output_artifacts": agent.get("output_artifacts", []),
            }
        )
    return {
        "event_id": event_id,
        "known": True,
        "subscribers": subscribers,
        "subscriber_count": len(subscribers),
        "summary": f"Event {event_id}: {len(subscribers)} subscriber agent(s).",
    }

"""Agent mesh topology — pipeline stage DAG and domain event catalog."""

from __future__ import annotations

from typing import Any

DOMAIN_EVENTS: list[dict[str, str]] = [
    {"id": "commit_created", "description": "New commit ingested into pipeline"},
    {"id": "pipeline_started", "description": "Pipeline run queued or started"},
    {"id": "full_scan_completed", "description": "Code, security, and QA scan bundle finished"},
    {"id": "security_completed", "description": "Security scan artifact persisted"},
    {"id": "qa_completed", "description": "QA report artifact persisted"},
    {"id": "stress_completed", "description": "Stress test finished"},
    {"id": "approval_decided", "description": "Approval agent produced decision"},
    {"id": "deployment_completed", "description": "Deployment stage finished"},
    {"id": "monitoring_alert", "description": "Monitoring agent raised alert"},
    {"id": "incident_detected", "description": "Incident commander bundle triggered"},
    {"id": "policy_blocked", "description": "Policy engine blocked pipeline"},
    {"id": "auto_pr_opened", "description": "Remediation opened fix PR"},
]

PIPELINE_STAGE_GRAPH: list[dict[str, Any]] = [
    {"stage": "ingest", "agents": ["RepositoryIntelligenceAgent"], "order": 1},
    {"stage": "full_scan", "agents": ["CodeAnalysisAgent", "SecurityAgent", "QAAgent"], "order": 2, "parallel": True},
    {"stage": "enrichment", "agents": ["TestIntelligenceAgent", "PolicyIntelligenceAgent"], "order": 3},
    {"stage": "stress", "agents": ["StressTestAgent", "PerformanceIntelligenceAgent"], "order": 4},
    {"stage": "governance", "agents": ["RagIntelligence"], "order": 5},
    {"stage": "approval", "agents": ["ApprovalAgent", "EnterpriseApprovalWorkflow"], "order": 6},
    {"stage": "deploy", "agents": ["DeploymentAgent", "DeploymentIntelligenceAgent", "CloudIntelligence", "ServiceCatalogIntelligence"], "order": 7},
    {"stage": "monitor", "agents": ["MonitoringAgent", "ObservabilityIntelligenceAgent", "IncidentIntelligenceAgent"], "order": 8},
]

AGENT_DEPENDENCY_EDGES: list[dict[str, str]] = [
    {"from": "CodeAnalysisAgent", "to": "ApprovalAgent", "kind": "artifact:code_analysis"},
    {"from": "SecurityAgent", "to": "ApprovalAgent", "kind": "artifact:security_scan"},
    {"from": "QAAgent", "to": "ApprovalAgent", "kind": "artifact:qa_report"},
    {"from": "StressTestAgent", "to": "ApprovalAgent", "kind": "artifact:stress_report"},
    {"from": "ApprovalAgent", "to": "DeploymentAgent", "kind": "gate:approved"},
    {"from": "DeploymentAgent", "to": "MonitoringAgent", "kind": "artifact:deployment_info"},
    {"from": "SecurityAgent", "to": "RemediationIntelligenceAgent", "kind": "blocked:security"},
    {"from": "QAAgent", "to": "SoftwareEngineerAgent", "kind": "blocked:tests"},
    {"from": "MonitoringAgent", "to": "IncidentIntelligenceAgent", "kind": "event:monitoring_alert"},
    {"from": "RepositoryIntelligenceAgent", "to": "ServiceCatalogIntelligence", "kind": "artifact:repository_intelligence"},
    {"from": "CloudIntelligence", "to": "ServiceCatalogIntelligence", "kind": "artifact:cloud_intelligence"},
]


def build_mesh_topology() -> dict[str, Any]:
    return {
        "domain_events": DOMAIN_EVENTS,
        "event_count": len(DOMAIN_EVENTS),
        "stages": PIPELINE_STAGE_GRAPH,
        "stage_count": len(PIPELINE_STAGE_GRAPH),
        "edges": AGENT_DEPENDENCY_EDGES,
        "edge_count": len(AGENT_DEPENDENCY_EDGES),
        "summary": (
            f"Agent mesh topology: {len(PIPELINE_STAGE_GRAPH)} stage(s), "
            f"{len(AGENT_DEPENDENCY_EDGES)} dependency edge(s), {len(DOMAIN_EVENTS)} event(s)."
        ),
    }

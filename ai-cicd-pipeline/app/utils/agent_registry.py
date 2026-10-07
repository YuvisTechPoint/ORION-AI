"""ORION agent registry — catalog of pipeline and multimodal agents."""

from __future__ import annotations

from typing import Any

from app.config import settings

PIPELINE_AGENTS: list[dict[str, Any]] = [
    {
        "name": "CodeAnalysisAgent",
        "alias": "code_analysis",
        "stage": 2,
        "artifact_types": ["code_analysis"],
        "risk_level": "medium",
        "model_env": "CODE_ANALYSIS_MODEL",
    },
    {
        "name": "SecurityAgent",
        "alias": "security",
        "stage": 2,
        "artifact_types": ["security_scan"],
        "risk_level": "high",
        "model_env": "SECURITY_MODEL",
    },
    {
        "name": "QAAgent",
        "alias": "qa",
        "stage": 2,
        "artifact_types": ["qa_report"],
        "risk_level": "medium",
        "model_env": "QA_MODEL",
    },
    {
        "name": "StressTestAgent",
        "alias": "stress",
        "stage": 5,
        "artifact_types": ["stress_report"],
        "risk_level": "low",
        "model_env": "STRESS_MODEL",
    },
    {
        "name": "ApprovalAgent",
        "alias": "approval",
        "stage": 6,
        "artifact_types": ["approval"],
        "risk_level": "high",
        "model_env": "APPROVAL_MODEL",
    },
    {
        "name": "DeploymentAgent",
        "alias": "deployment",
        "stage": 7,
        "artifact_types": ["deployment_info", "last_known_good_image"],
        "risk_level": "critical",
        "model_env": "DEPLOYMENT_MODEL",
    },
    {
        "name": "MonitoringAgent",
        "alias": "monitoring",
        "stage": 8,
        "artifact_types": ["monitoring_summary", "monitoring_alert"],
        "risk_level": "high",
        "model_env": "MONITORING_MODEL",
    },
    {
        "name": "RepositoryIntelligenceAgent",
        "alias": "repository_intelligence",
        "stage": 1,
        "artifact_types": ["repository_intelligence"],
        "risk_level": "low",
        "model_env": "REPOSITORY_INTELLIGENCE_MODEL",
    },
    {
        "name": "TestIntelligenceAgent",
        "alias": "test_intelligence",
        "stage": 1,
        "artifact_types": ["test_intelligence"],
        "risk_level": "low",
        "model_env": "TEST_INTELLIGENCE_MODEL",
    },
    {
        "name": "PerformanceIntelligenceAgent",
        "alias": "performance_intelligence",
        "stage": 5,
        "artifact_types": ["performance_intelligence"],
        "risk_level": "low",
        "model_env": "PERFORMANCE_INTELLIGENCE_MODEL",
    },
    {
        "name": "DeploymentIntelligenceAgent",
        "alias": "deployment_intelligence",
        "stage": 7,
        "artifact_types": ["deployment_intelligence"],
        "risk_level": "medium",
        "model_env": "DEPLOYMENT_INTELLIGENCE_MODEL",
    },
    {
        "name": "ObservabilityIntelligenceAgent",
        "alias": "observability_intelligence",
        "stage": 8,
        "artifact_types": ["observability_intelligence"],
        "risk_level": "medium",
        "model_env": "OBSERVABILITY_INTELLIGENCE_MODEL",
    },
    {
        "name": "IncidentIntelligenceAgent",
        "alias": "incident_intelligence",
        "stage": 8,
        "artifact_types": ["incident_intelligence", "incident_commander_report"],
        "risk_level": "high",
        "model_env": "INCIDENT_INTELLIGENCE_MODEL",
    },
    {
        "name": "RemediationIntelligenceAgent",
        "alias": "remediation_intelligence",
        "stage": 2,
        "artifact_types": ["remediation_intelligence", "fix_loop_report", "patch_confidence_report"],
        "risk_level": "high",
        "model_env": "REMEDIATION_INTELLIGENCE_MODEL",
    },
    {
        "name": "PolicyIntelligenceAgent",
        "alias": "policy_intelligence",
        "stage": 4,
        "artifact_types": ["policy_intelligence", "policy_evaluation"],
        "risk_level": "high",
        "model_env": "POLICY_INTELLIGENCE_MODEL",
    },
    {
        "name": "EnterpriseApprovalWorkflow",
        "alias": "enterprise_approval",
        "stage": 6,
        "artifact_types": ["enterprise_approval", "approval_intelligence"],
        "risk_level": "high",
        "model_env": "APPROVAL_MODEL",
    },
    {
        "name": "CloudIntelligence",
        "alias": "cloud_intelligence",
        "stage": 7,
        "artifact_types": ["cloud_intelligence", "kubernetes_manifest_scan"],
        "risk_level": "high",
        "model_env": "CLOUD_INTELLIGENCE_MODEL",
    },
    {
        "name": "ServiceCatalogIntelligence",
        "alias": "service_catalog",
        "stage": 7,
        "artifact_types": ["service_catalog", "service_catalog_intelligence"],
        "risk_level": "medium",
        "model_env": "SERVICE_CATALOG_INTELLIGENCE_MODEL",
    },
    {
        "name": "RagIntelligence",
        "alias": "rag_intelligence",
        "stage": 5,
        "artifact_types": ["rag_intelligence", "devops_rag_context", "agent_memory_snapshot"],
        "risk_level": "low",
        "model_env": "DEVOPS_RAG_MODEL",
    },
    {
        "name": "AgentMeshIntelligence",
        "alias": "agent_mesh",
        "stage": 5,
        "artifact_types": ["agent_mesh_snapshot", "agent_mesh_intelligence"],
        "risk_level": "low",
        "model_env": "ORCHESTRATOR_MODEL",
    },
    {
        "name": "AIGovernanceIntelligence",
        "alias": "ai_governance",
        "stage": 5,
        "artifact_types": ["ai_governance_intelligence"],
        "risk_level": "high",
        "model_env": "ORCHESTRATOR_MODEL",
    },
    {
        "name": "FinOpsIntelligence",
        "alias": "finops",
        "stage": 4,
        "artifact_types": ["cost_report", "finops_intelligence"],
        "risk_level": "low",
        "model_env": "ORCHESTRATOR_MODEL",
    },
    {
        "name": "ReleaseIntelligence",
        "alias": "release",
        "stage": 3,
        "artifact_types": ["release_passport", "release_intelligence"],
        "risk_level": "medium",
        "model_env": "ORCHESTRATOR_MODEL",
    },
    {
        "name": "DeveloperUxIntelligence",
        "alias": "developer_ux",
        "stage": 3,
        "artifact_types": ["developer_ux_intelligence", "pr_intelligence"],
        "risk_level": "low",
        "model_env": "ORCHESTRATOR_MODEL",
    },
    {
        "name": "SoftwareEngineerAgent",
        "alias": "software_engineer",
        "stage": 0,
        "artifact_types": ["fix_loop_report"],
        "risk_level": "high",
        "model_env": "CODE_ANALYSIS_MODEL",
    },
]

MULTIMODAL_AGENTS: list[dict[str, Any]] = [
    {"name": "LogAnalysisAgent", "alias": "log", "artifact_types": ["log_analysis"]},
    {"name": "GitHubLogAgent", "alias": "github", "artifact_types": ["github_log_analysis"]},
    {"name": "CiBuildLogAgent", "alias": "ci_build", "artifact_types": ["ci_build_log_analysis"]},
    {"name": "GitLogAgent", "alias": "git", "artifact_types": ["git_log_analysis"]},
    {"name": "PaymentAgent", "alias": "payment", "artifact_types": ["payment_analysis"]},
    {"name": "DockerfileAgent", "alias": "docker", "artifact_types": ["dockerfile_analysis"]},
    {"name": "ProductionTriageAgent", "alias": "triage", "artifact_types": ["production_triage"]},
    {"name": "MetricsSnapshotAgent", "alias": "metrics", "artifact_types": ["metrics_snapshot_analysis"]},
    {"name": "KubernetesManifestAgent", "alias": "kubernetes", "artifact_types": ["kubernetes_manifest_scan"]},
    {"name": "MultimodalIntelligence", "alias": "multimodal_intelligence", "artifact_types": ["multimodal_intelligence"]},
]


def build_agent_registry() -> dict[str, Any]:
    agents: list[dict[str, Any]] = []
    for entry in PIPELINE_AGENTS:
        model_env = entry["model_env"]
        agents.append(
            {
                **entry,
                "kind": "pipeline",
                "model": getattr(settings, model_env.lower(), settings.anthropic_model),
                "llm_enabled": settings.llm_enabled,
            }
        )
    for entry in MULTIMODAL_AGENTS:
        agents.append({**entry, "kind": "multimodal", "risk_level": "medium"})
    return {
        "agents": agents,
        "pipeline_count": len(PIPELINE_AGENTS),
        "multimodal_count": len(MULTIMODAL_AGENTS),
        "total": len(agents),
        "summary": f"Agent registry: {len(agents)} registered agent(s).",
    }

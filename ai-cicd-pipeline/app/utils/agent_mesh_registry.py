"""Agent mesh registry — O2-style descriptors with capabilities, permissions, and subscriptions."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.utils.agent_permissions import AGENT_PERMISSIONS
from app.utils.agent_registry import MULTIMODAL_AGENTS, PIPELINE_AGENTS
from app.utils.agent_mesh_topology import DOMAIN_EVENTS

_AGENT_CAPABILITIES: dict[str, list[str]] = {
    "CodeAnalysisAgent": ["sast", "ast", "lint", "code_review"],
    "SecurityAgent": ["sast", "sca", "secrets", "supply_chain"],
    "QAAgent": ["pytest", "test_verdict", "simulated_qa"],
    "StressTestAgent": ["load_test", "locust", "performance_gate"],
    "ApprovalAgent": ["gate_fusion", "risk_decision"],
    "DeploymentAgent": ["docker", "canary", "rollback"],
    "MonitoringAgent": ["logs", "health", "auto_rollback"],
    "SoftwareEngineerAgent": ["patch", "sandbox", "auto_pr"],
    "RepositoryIntelligenceAgent": ["ownership", "stack_detect", "monorepo"],
    "TestIntelligenceAgent": ["test_selection", "flaky", "coverage"],
    "PerformanceIntelligenceAgent": ["baseline", "regression"],
    "DeploymentIntelligenceAgent": ["progressive_delivery", "slo_gate"],
    "ObservabilityIntelligenceAgent": ["otel", "error_budget", "synthetic"],
    "IncidentIntelligenceAgent": ["rca", "postmortem", "runbook"],
    "RemediationIntelligenceAgent": ["fix_loop", "patch_confidence"],
    "PolicyIntelligenceAgent": ["policy_as_code", "compliance"],
    "EnterpriseApprovalWorkflow": ["four_eyes", "signed_approval"],
    "CloudIntelligence": ["k8s", "cloud_target", "iac"],
    "ServiceCatalogIntelligence": ["idp", "service_graph", "fleet"],
    "RagIntelligence": ["devops_rag", "memory", "retriever"],
    "LogAnalysisAgent": ["log_parse", "error_signatures"],
    "GitHubLogAgent": ["github_actions"],
    "CiBuildLogAgent": ["jenkins", "gitlab_ci", "circleci"],
    "GitLogAgent": ["git_history"],
    "PaymentAgent": ["reconciliation"],
    "DockerfileAgent": ["container_hardening"],
    "ProductionTriageAgent": ["incident_triage"],
    "MetricsSnapshotAgent": ["prometheus", "grafana"],
    "KubernetesManifestAgent": ["k8s_manifest"],
    "MultimodalIntelligence": ["multimodal_fusion"],
}

_AGENT_INPUTS: dict[str, list[str]] = {
    "CodeAnalysisAgent": ["repo_path", "diff"],
    "SecurityAgent": ["repo_path", "diff", "requirements"],
    "QAAgent": ["repo_path", "diff", "changed_files"],
    "StressTestAgent": ["staging_url"],
    "ApprovalAgent": ["full_scan_combined", "stress_report", "change_risk_report"],
    "DeploymentAgent": ["repo_path", "commit", "approval"],
    "MonitoringAgent": ["deployment_info", "staging_url", "logs"],
    "SoftwareEngineerAgent": ["full_scan_combined", "repo_path"],
    "LogAnalysisAgent": ["text", "files"],
    "ProductionTriageAgent": ["text", "files", "images"],
}

_EVENT_SUBSCRIPTIONS: dict[str, list[str]] = {
    "SecurityAgent": ["commit_created", "full_scan_completed"],
    "QAAgent": ["commit_created", "full_scan_completed"],
    "ApprovalAgent": ["stress_completed", "full_scan_completed"],
    "DeploymentAgent": ["approval_decided"],
    "MonitoringAgent": ["deployment_completed", "monitoring_alert"],
    "IncidentIntelligenceAgent": ["monitoring_alert", "incident_detected"],
    "RemediationIntelligenceAgent": ["policy_blocked", "full_scan_completed"],
    "SoftwareEngineerAgent": ["policy_blocked", "qa_completed"],
    "PolicyIntelligenceAgent": ["full_scan_completed", "policy_blocked"],
    "RagIntelligence": ["pipeline_started", "deployment_completed"],
}

_DEFAULT_TIMEOUT = 300


def _parse_overrides() -> dict[str, Any]:
    raw = (settings.agent_mesh_overrides_json or "").strip()
    if not raw or raw == "{}":
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _descriptor(entry: dict[str, Any], *, kind: str) -> dict[str, Any]:
    name = entry["name"]
    overrides = _parse_overrides().get(name) or _parse_overrides().get(entry.get("alias", "")) or {}
    perms = AGENT_PERMISSIONS.get(name, overrides.get("permissions") or {})
    model_env = entry.get("model_env", "")
    model = getattr(settings, model_env.lower(), settings.anthropic_model) if model_env else settings.anthropic_model
    return {
        "name": name,
        "alias": entry.get("alias", name),
        "version": overrides.get("version", "2.1.0"),
        "kind": kind,
        "stage": entry.get("stage"),
        "capabilities": overrides.get("capabilities") or _AGENT_CAPABILITIES.get(name, []),
        "permissions": perms,
        "input_types": overrides.get("input_types") or _AGENT_INPUTS.get(name, ["artifacts"]),
        "output_artifacts": entry.get("artifact_types") or [],
        "risk_level": entry.get("risk_level", "medium"),
        "model": overrides.get("model") or model,
        "model_env": model_env,
        "timeout_seconds": int(overrides.get("timeout_seconds", _DEFAULT_TIMEOUT)),
        "subscriptions": overrides.get("subscriptions") or _EVENT_SUBSCRIPTIONS.get(name, []),
        "llm_enabled": settings.llm_enabled,
    }


def build_agent_mesh_registry() -> dict[str, Any]:
    agents: list[dict[str, Any]] = []
    for entry in PIPELINE_AGENTS:
        agents.append(_descriptor(entry, kind="pipeline"))
    for entry in MULTIMODAL_AGENTS:
        agents.append(_descriptor(entry, kind="multimodal"))
    by_alias = {a["alias"]: a for a in agents}
    by_name = {a["name"]: a for a in agents}
    return {
        "agents": agents,
        "agents_by_alias": by_alias,
        "agents_by_name": by_name,
        "pipeline_count": len(PIPELINE_AGENTS),
        "multimodal_count": len(MULTIMODAL_AGENTS),
        "total": len(agents),
        "domain_events": DOMAIN_EVENTS,
        "summary": f"Agent mesh registry: {len(agents)} agent descriptor(s).",
    }

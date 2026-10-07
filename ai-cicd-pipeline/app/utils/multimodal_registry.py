"""Multimodal agent catalog — aliases, inputs, and artifact types."""

from __future__ import annotations

from typing import Any

MULTIMODAL_AGENT_CATALOG: list[dict[str, Any]] = [
    {
        "id": "log_analysis",
        "name": "LogAnalysisAgent",
        "aliases": ["log", "log_analysis"],
        "artifact_type": "log_analysis",
        "inputs": ["text", "log", "zip"],
        "description": "Server, build, deployment, and application log triage.",
    },
    {
        "id": "github_actions",
        "name": "GitHubLogAgent",
        "aliases": ["github", "github_log", "github_logs", "github_actions"],
        "artifact_type": "github_log_analysis",
        "inputs": ["text", "zip", "github_run_id"],
        "description": "GitHub Actions workflow failure analysis.",
    },
    {
        "id": "ci_build_log",
        "name": "CiBuildLogAgent",
        "aliases": ["ci", "ci_build", "jenkins", "gitlab_ci", "circleci"],
        "artifact_type": "ci_build_log_analysis",
        "inputs": ["text", "log", "zip"],
        "description": "Jenkins, GitLab CI, CircleCI, and generic CI build logs.",
    },
    {
        "id": "git_logs",
        "name": "GitLogAgent",
        "aliases": ["git", "git_logs"],
        "artifact_type": "git_log_analysis",
        "inputs": ["text", "log"],
        "description": "Git history and commit message risk review.",
    },
    {
        "id": "payment",
        "name": "PaymentAgent",
        "aliases": ["payment"],
        "artifact_type": "payment_analysis",
        "inputs": ["csv", "pdf", "text"],
        "description": "Payment CSV/PDF reconciliation and failure patterns.",
    },
    {
        "id": "dockerfile",
        "name": "DockerfileAgent",
        "aliases": ["docker", "dockerfile"],
        "artifact_type": "dockerfile_analysis",
        "inputs": ["dockerfile", "text"],
        "description": "Dockerfile hardening review with optional auto-PR.",
    },
    {
        "id": "production_triage",
        "name": "ProductionTriageAgent",
        "aliases": ["triage", "production_triage"],
        "artifact_type": "production_triage",
        "inputs": ["text", "log", "image", "zip"],
        "description": "P1 incident triage from screenshots, logs, and alerts.",
    },
    {
        "id": "kubernetes",
        "name": "KubernetesManifestAgent",
        "aliases": ["kubernetes", "k8s", "manifest", "helm"],
        "artifact_type": "kubernetes_manifest_scan",
        "inputs": ["yaml", "yml", "text"],
        "description": "Kubernetes manifest readiness: probes, RBAC, ingress TLS, rollouts.",
    },
    {
        "id": "metrics_snapshot",
        "name": "MetricsSnapshotAgent",
        "aliases": ["metrics", "prometheus", "grafana"],
        "artifact_type": "metrics_snapshot_analysis",
        "inputs": ["text", "json", "csv"],
        "description": "Prometheus/Grafana export anomaly and threshold review.",
    },
]

_ALIAS_TO_ID: dict[str, str] = {}
for entry in MULTIMODAL_AGENT_CATALOG:
    _ALIAS_TO_ID[entry["id"]] = entry["id"]
    for alias in entry["aliases"]:
        _ALIAS_TO_ID[alias.lower()] = entry["id"]

MULTIMODAL_ARTIFACT_TYPES = frozenset(e["artifact_type"] for e in MULTIMODAL_AGENT_CATALOG) | {
    "payment_reconciliation",
    "multimodal_intelligence",
    "cloud_intelligence",
}


def normalize_agent_id(agent_type: str) -> str | None:
    return _ALIAS_TO_ID.get((agent_type or "").strip().lower())


def build_multimodal_catalog_report() -> dict[str, Any]:
    return {
        "agents": MULTIMODAL_AGENT_CATALOG,
        "count": len(MULTIMODAL_AGENT_CATALOG),
        "artifact_types": sorted(MULTIMODAL_ARTIFACT_TYPES),
        "summary": f"{len(MULTIMODAL_AGENT_CATALOG)} multimodal agent(s) registered.",
    }


def agent_entry(agent_id: str) -> dict[str, Any] | None:
    for entry in MULTIMODAL_AGENT_CATALOG:
        if entry["id"] == agent_id:
            return entry
    return None

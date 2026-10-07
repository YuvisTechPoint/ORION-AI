"""Cloud / Kubernetes intelligence — unified container, IaC, and target readiness report."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.cloud_target_registry import resolve_cloud_target


def evaluate_cloud_gates(
    *,
    kubernetes_manifest_scan: dict[str, Any] | None,
    iac_security_scan: dict[str, Any] | None,
    container_security_scan: dict[str, Any] | None,
    dockerfile_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    violations: list[str] = []
    k8s = kubernetes_manifest_scan or {}
    iac = iac_security_scan or {}
    container = container_security_scan or {}
    docker = dockerfile_analysis or {}

    if int(k8s.get("critical_count") or 0) > 0:
        violations.append(f"kubernetes: {k8s.get('critical_count')} critical manifest finding(s)")
    if not k8s.get("passed", True) and k8s.get("finding_count"):
        if int(k8s.get("high_count") or 0) >= 3:
            violations.append(f"kubernetes: {k8s.get('high_count')} high-severity manifest finding(s)")

    if int(iac.get("critical_count") or 0) > 0:
        violations.append(f"iac: {iac.get('critical_count')} critical finding(s)")
    if container.get("passed") is False:
        violations.append("container security scan failed")
    if int(docker.get("security_score") or 100) < 60:
        violations.append(f"dockerfile security score {docker.get('security_score')}/100")

    if violations and settings.cloud_intelligence_gate_enabled:
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_cloud_intelligence_report(
    *,
    repo: str = "",
    repo_path: str | None = None,
    environment: str | None = None,
    deploy_mode: str | None = None,
    kubernetes_manifest_scan: dict[str, Any] | None = None,
    iac_security_scan: dict[str, Any] | None = None,
    container_security_scan: dict[str, Any] | None = None,
    dockerfile_analysis: dict[str, Any] | None = None,
    service_graph: dict[str, Any] | None = None,
    deployment_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signals = None
    if repo_path:
        from app.utils.cloud_target_registry import _repo_signals

        signals = _repo_signals(repo_path)
    target = resolve_cloud_target(
        repo_path=repo_path,
        repo=repo,
        environment=environment,
        deploy_mode=deploy_mode,
        signals=signals,
    )
    graph = service_graph or {}
    k8s_nodes = [n for n, meta in (graph.get("nodes") or {}).items() if meta.get("type") == "k8s_workload"]

    gates = evaluate_cloud_gates(
        kubernetes_manifest_scan=kubernetes_manifest_scan,
        iac_security_scan=iac_security_scan,
        container_security_scan=container_security_scan,
        dockerfile_analysis=dockerfile_analysis,
    )

    report: dict[str, Any] = {
        "cloud_target": target,
        "kubernetes_manifest_scan": kubernetes_manifest_scan or {},
        "iac_security_scan": {
            "finding_count": (iac_security_scan or {}).get("finding_count", 0),
            "critical_count": (iac_security_scan or {}).get("critical_count", 0),
            "passed": (iac_security_scan or {}).get("passed", True),
        },
        "container_security_scan": {
            "passed": (container_security_scan or {}).get("passed", True),
            "finding_count": (container_security_scan or {}).get("finding_count", 0),
        },
        "dockerfile_analysis": {
            "security_score": (dockerfile_analysis or {}).get("security_score"),
            "issue_count": len((dockerfile_analysis or {}).get("dockerfile_issues") or []),
        },
        "service_graph_k8s_workloads": k8s_nodes[:20],
        "deployment_runtime": (deployment_info or {}).get("runtime") or target.get("primary_runtime"),
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"Cloud intel {gates['gate_verdict']}: target={target.get('primary_target')}, "
        f"K8s findings={(kubernetes_manifest_scan or {}).get('finding_count', 0)}, "
        f"IaC critical={(iac_security_scan or {}).get('critical_count', 0)}."
    )
    return report

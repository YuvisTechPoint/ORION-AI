"""Knowledge graph intelligence — coverage scoring, queries, and gate evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.knowledge_graph import build_knowledge_graph, query_knowledge_graph
from app.utils.knowledge_graph_registry import resolve_knowledge_graph_policy


def compute_graph_coverage(
    *,
    graph: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    def _present(key: str) -> bool:
        return key in artifacts and artifacts.get(key) is not None

    layers = {
        "service_graph": _present("service_graph"),
        "repository_intelligence": _present("repository_intelligence"),
        "sbom": _present("sbom"),
        "change_risk": _present("change_risk_report"),
        "tests": _present("test_intelligence") or _present("qa_report"),
        "deployment": _present("deployment_info"),
        "incident": _present("incident_commander_report") or _present("evidence_graph"),
    }
    present = sum(1 for v in layers.values() if v)
    total = len(layers)
    percent = round(100 * present / total, 1) if total else 0.0
    missing = [name for name, ok in layers.items() if not ok]
    return {
        "layers": layers,
        "layers_present": present,
        "layers_total": total,
        "coverage_percent": percent,
        "missing_layers": missing,
        "summary": f"Graph coverage {percent}% ({present}/{total} layers).",
    }


def evaluate_knowledge_graph_gates(
    *,
    policy: dict[str, Any],
    graph: dict[str, Any],
    coverage: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []

    min_nodes = int(policy.get("min_nodes") or 0)
    if graph.get("node_count", 0) < min_nodes:
        violations.append(f"Knowledge graph has {graph.get('node_count', 0)} nodes (min {min_nodes})")

    min_cov = float(policy.get("min_coverage_percent") or 0)
    if coverage.get("coverage_percent", 0) < min_cov:
        violations.append(
            f"Graph coverage {coverage.get('coverage_percent')}% below minimum {min_cov:.0f}%"
        )

    if policy.get("require_service_graph") and not artifacts.get("service_graph"):
        violations.append("Service graph required but not present in artifacts")

    if policy.get("require_repository_intel") and not artifacts.get("repository_intelligence"):
        violations.append("Repository intelligence required but not present")

    if coverage.get("missing_layers"):
        warnings.append(f"Missing layers: {', '.join(coverage['missing_layers'][:4])}")

    if violations and settings.knowledge_graph_gate_enabled:
        gate = "fail"
    elif violations or warnings:
        gate = "warn"
    else:
        gate = "pass"

    return {"gate_verdict": gate, "violations": violations, "warnings": warnings}


def build_knowledge_graph_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    commit: str = "",
    branch: str = "",
    artifacts: dict[str, dict[str, Any]] | None = None,
    query: str = "",
) -> dict[str, Any]:
    artifacts = artifacts or {}
    metadata = artifacts.get("metadata") or {}
    policy = resolve_knowledge_graph_policy(repo)

    graph = build_knowledge_graph(
        run_id=run_id,
        repo=repo or metadata.get("repo") or "",
        commit=commit or metadata.get("commit") or "",
        branch=branch or metadata.get("branch") or "",
        artifacts=artifacts,
    )
    coverage = compute_graph_coverage(graph=graph, artifacts=artifacts)
    gates = evaluate_knowledge_graph_gates(
        policy=policy,
        graph=graph,
        coverage=coverage,
        artifacts=artifacts,
    )

    query_result = query_knowledge_graph(graph, query) if query else None

    report: dict[str, Any] = {
        "run_id": run_id or None,
        "repository": repo or metadata.get("repo"),
        "commit": commit or metadata.get("commit"),
        "branch": branch or metadata.get("branch"),
        "policy": policy,
        "graph": graph,
        "coverage": coverage,
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "query_result": query_result,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"Knowledge graph {gates['gate_verdict']}: {graph['node_count']} nodes, "
        f"{graph['edge_count']} edges, coverage {coverage['coverage_percent']}%."
    )
    return report

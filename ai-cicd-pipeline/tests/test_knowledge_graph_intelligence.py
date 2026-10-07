"""Tests for Phase 27 knowledge graph intelligence."""

from __future__ import annotations

import json

from app.utils.knowledge_graph import build_knowledge_graph, query_knowledge_graph
from app.utils.knowledge_graph_intelligence import (
    build_knowledge_graph_intelligence_report,
    compute_graph_coverage,
    evaluate_knowledge_graph_gates,
)
from app.utils.knowledge_graph_registry import resolve_knowledge_graph_policy


def test_resolve_knowledge_graph_policy():
    policy = resolve_knowledge_graph_policy("acme/api")
    assert policy["organization"] == "acme"
    assert policy["min_nodes"] >= 1


def test_build_knowledge_graph_merges_layers():
    artifacts = {
        "metadata": {"repo": "acme/api", "commit": "abc123", "changed_files": ["src/auth.py"]},
        "service_graph": {
            "nodes": {"api": {"type": "service", "source": "compose"}, "redis": {"type": "database", "source": "compose"}},
            "edges": [{"from": "api", "to": "redis", "kind": "depends_on"}],
        },
        "repository_intelligence": {
            "languages": [{"name": "python"}],
            "frameworks": [{"name": "fastapi"}],
        },
        "sbom": {"components": [{"name": "requests", "version": "2.31.0"}]},
        "code_analysis": {"severity": "pass"},
    }
    graph = build_knowledge_graph(
        run_id="run-kg-1",
        repo="acme/api",
        commit="abc123def456",
        branch="main",
        artifacts=artifacts,
    )
    assert graph["node_count"] >= 5
    assert graph["edge_count"] >= 1
    types = {n["type"] for n in graph["nodes"]}
    assert "service" in types or "database" in types
    assert "dependency" in types


def test_query_knowledge_graph_auth():
    graph = build_knowledge_graph(
        repo="acme/api",
        artifacts={
            "metadata": {"changed_files": ["src/auth/middleware.py", "src/payment.py"]},
        },
    )
    result = query_knowledge_graph(graph, "auth")
    assert result["match_count"] >= 1
    paths = [str(m.get("path") or (m.get("meta") or {}).get("path", "")).lower() for m in result["matches"]]
    assert any("auth" in p for p in paths)


def test_compute_graph_coverage():
    coverage = compute_graph_coverage(
        graph={"node_count": 10},
        artifacts={"service_graph": {}, "repository_intelligence": {}},
    )
    assert coverage["coverage_percent"] > 0
    assert "service_graph" in coverage["layers"]


def test_evaluate_knowledge_graph_gates_fail(monkeypatch):
    monkeypatch.setattr("app.utils.knowledge_graph_intelligence.settings.knowledge_graph_gate_enabled", True)
    gates = evaluate_knowledge_graph_gates(
        policy={"min_nodes": 20, "min_coverage_percent": 80, "require_service_graph": True},
        graph={"node_count": 3},
        coverage={"coverage_percent": 10},
        artifacts={},
    )
    assert gates["gate_verdict"] == "fail"
    assert gates["violations"]


def test_build_knowledge_graph_intelligence_report():
    report = build_knowledge_graph_intelligence_report(
        run_id="run-kg-2",
        repo="org/service",
        commit="deadbeef",
        branch="main",
        artifacts={
            "service_graph": {"nodes": {"svc": {"type": "service"}}, "edges": []},
            "repository_intelligence": {"languages": [{"name": "python"}]},
        },
    )
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert report["graph"]["node_count"] >= 1
    assert report["coverage"]["coverage_percent"] >= 0


def test_policy_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.knowledge_graph_registry.settings.knowledge_graph_policy_json",
        json.dumps({"acme": {"min_nodes": 12, "min_coverage_percent": 55}}),
    )
    policy = resolve_knowledge_graph_policy("acme/checkout")
    assert policy["min_nodes"] == 12
    assert policy["min_coverage_percent"] == 55

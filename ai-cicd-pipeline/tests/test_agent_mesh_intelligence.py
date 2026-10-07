"""Tests for Phase 18 agent mesh."""

from __future__ import annotations

import json

from app.utils.agent_mesh_intelligence import build_agent_mesh_intelligence_report, evaluate_mesh_health
from app.utils.agent_mesh_registry import build_agent_mesh_registry
from app.utils.agent_mesh_router import route_mesh_event, route_mesh_intent
from app.utils.agent_mesh_topology import build_mesh_topology


def test_mesh_topology_has_stages_and_events():
    topo = build_mesh_topology()
    assert topo["stage_count"] >= 6
    assert topo["event_count"] >= 8
    assert any(s["stage"] == "full_scan" for s in topo["stages"])


def test_mesh_registry_descriptors():
    registry = build_agent_mesh_registry()
    assert registry["total"] >= 20
    security = registry["agents_by_name"]["SecurityAgent"]
    assert "sast" in security["capabilities"]
    assert security["output_artifacts"] == ["security_scan"]
    assert security["timeout_seconds"] >= 60


def test_mesh_registry_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.agent_mesh_registry.settings.agent_mesh_overrides_json",
        json.dumps({"SecurityAgent": {"version": "9.9.9", "timeout_seconds": 120}}),
    )
    registry = build_agent_mesh_registry()
    sec = registry["agents_by_name"]["SecurityAgent"]
    assert sec["version"] == "9.9.9"
    assert sec["timeout_seconds"] == 120


def test_route_mesh_intent_security():
    route = route_mesh_intent("critical security vulnerability in auth")
    names = [r["agent"] for r in route["recommended_chain"]]
    assert "SecurityAgent" in names


def test_route_mesh_event_monitoring_alert():
    route = route_mesh_event("monitoring_alert")
    assert route["known"] is True
    assert route["subscriber_count"] >= 1
    assert any(s["agent"] == "IncidentIntelligenceAgent" for s in route["subscribers"])


def test_mesh_intelligence_observes_artifacts():
    report = build_agent_mesh_intelligence_report(
        artifacts={
            "security_scan": {"passed": False, "summary": "critical"},
            "qa_report": {"verdict": "pass"},
            "approval": {"decision": "approved"},
        },
        intent="why security failed",
    )
    assert "SecurityAgent" in report["observed_agents"]
    assert report["route"]["recommended_chain"]
    assert report["health"]["coverage_percent"] > 0


def test_mesh_health_gate_fail(monkeypatch):
    monkeypatch.setattr("app.utils.agent_mesh_intelligence.settings.agent_mesh_gate_enabled", True)
    monkeypatch.setattr("app.utils.agent_mesh_intelligence.settings.agent_mesh_min_coverage_percent", 90)
    health = evaluate_mesh_health(observed={"QAAgent"}, missing_critical=["SecurityAgent"])
    assert health["gate_verdict"] == "fail"

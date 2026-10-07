"""Tests for Phase 14 multimodal expansion."""

from __future__ import annotations

from app.agents.multimodal.ci_build_log_agent import detect_ci_platform
from app.agents.multimodal.metrics_snapshot_agent import _parse_prometheus
from app.utils.multimodal_intelligence import build_multimodal_intelligence_report, evaluate_multimodal_gates
from app.utils.multimodal_registry import build_multimodal_catalog_report, normalize_agent_id
from app.utils.multimodal_router import route_multimodal_inputs


def test_catalog_has_eight_agents():
    report = build_multimodal_catalog_report()
    assert report["count"] == 9
    ids = {a["id"] for a in report["agents"]}
    assert "ci_build_log" in ids
    assert "metrics_snapshot" in ids


def test_normalize_agent_aliases():
    assert normalize_agent_id("jenkins") == "ci_build_log"
    assert normalize_agent_id("prometheus") == "metrics_snapshot"
    assert normalize_agent_id("log") == "log_analysis"


def test_route_github_actions_log():
    text = "##[error]Process completed with exit code 1\nactions/runner starting"
    route = route_multimodal_inputs(text_input=text)
    assert route["primary_agent"] == "github_actions"


def test_route_jenkins_to_ci_build():
    text = "Started by user admin\n[Pipeline] stage\nFinished: FAILURE\nERROR: script returned exit code 1"
    route = route_multimodal_inputs(text_input=text)
    assert route["primary_agent"] == "ci_build_log"


def test_route_prometheus_metrics():
    text = "# HELP http_requests_total Total requests\nhttp_requests_total 42\n"
    route = route_multimodal_inputs(text_input=text)
    assert route["primary_agent"] == "metrics_snapshot"


def test_detect_ci_platform_jenkins():
    assert detect_ci_platform("[Pipeline] Finished: FAILURE") == "jenkins"


def test_parse_prometheus_samples():
    samples = _parse_prometheus("cpu_utilization 0.92\nhttp_errors_total 3\n")
    assert ("cpu_utilization", 0.92) in samples


def test_multimodal_intelligence_aggregates_artifacts():
    artifacts = {
        "log_analysis": {"severity": "medium", "summary": "3 errors"},
        "production_triage": {"severity": "P2", "escalate_to_human": True, "summary": "Degradation"},
    }
    report = build_multimodal_intelligence_report(artifacts=artifacts)
    assert report["agents_present"] == 2
    assert report["gate_verdict"] == "fail"


def test_multimodal_gates_pass_when_clean():
    gates = evaluate_multimodal_gates({"log_analysis": {"severity": "low", "summary": "ok"}})
    assert gates["gate_verdict"] == "pass"

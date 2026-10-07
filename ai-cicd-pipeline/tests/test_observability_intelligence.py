"""Tests for Phase 9 observability / AIOps intelligence."""

from __future__ import annotations

from app.utils.observability_intelligence import (
    analyze_log_signals,
    build_observability_intelligence_report,
    build_runtime_service_map,
    correlate_deploy_window,
    detect_metric_anomalies,
    evaluate_observability_gates,
)


def test_correlate_deploy_window_links_trace_and_synthetic():
    correlation = correlate_deploy_window(
        deployment_info={
            "success": True,
            "deployed_at": "2026-10-06T00:00:00+00:00",
            "environment": "staging",
            "health_check_passed": True,
        },
        otel_trace_context={"trace_id": "trace1234567890", "spans": [{"name": "pipeline.deploy"}]},
        synthetic_monitoring_report={"all_passed": True, "passed": 2, "total": 2, "checked_at": "2026-10-06T00:01:00+00:00"},
        stress_report={"performance_verdict": "pass", "p95_ms": 320},
        error_budget_report={"error_budget_remaining_percent": 72},
        service_graph={"root_service": "api", "changed_services": ["api"], "node_count": 2},
        monitoring_summary=None,
    )
    assert correlation["trace_id"] == "trace1234567890"
    assert correlation["monitoring_status"] == "pending"
    assert correlation["blast_radius"]["changed_services"] == ["api"]
    assert len(correlation["timeline"]) >= 2


def test_detect_metric_anomalies_synthetic_failure(monkeypatch):
    monkeypatch.setattr("app.utils.observability_intelligence.settings.observability_anomaly_gate_enabled", True)
    result = detect_metric_anomalies(
        synthetic_monitoring_report={
            "all_passed": False,
            "journeys": [{"journey": "health", "passed": False}],
        },
        stress_report={"performance_verdict": "pass", "p95_ms": 300},
    )
    assert result["anomaly_count"] >= 1
    assert result["verdict"] == "fail"


def test_detect_metric_anomalies_latency_regression():
    historical = [{"journeys": [{"passed": True, "latency_ms": 20.0}]} for _ in range(3)]
    result = detect_metric_anomalies(
        synthetic_monitoring_report={"journeys": [{"passed": True, "latency_ms": 120.0}]},
        stress_report={},
        historical_synthetic=historical,
    )
    assert any(a.get("type") == "latency_regression" for a in result["anomalies"])


def test_analyze_log_signals_from_monitoring_summary():
    signals = analyze_log_signals(
        monitoring_summary={
            "checks_performed": 3,
            "assessment": {
                "status": "degraded",
                "recommended_action": "alert",
                "anomalies": [{"type": "errors", "description": "5 error log lines", "severity": "medium"}],
            },
        }
    )
    assert signals["status"] == "degraded"
    assert signals["recommended_action"] == "alert"


def test_build_runtime_service_map_marks_changed():
    overlay = build_runtime_service_map(
        {
            "root_service": "api",
            "nodes": {"api": {"type": "service"}, "db": {"type": "database"}},
            "edges": [{"from": "api", "to": "db", "kind": "datastore"}],
            "node_count": 2,
            "edge_count": 1,
            "changed_services": ["api"],
        },
        deployment_info={"environment": "staging"},
    )
    changed = [n for n in overlay["nodes"] if n.get("changed_in_deploy")]
    assert len(changed) == 1
    assert changed[0]["name"] == "api"


def test_build_observability_report_gate_pass():
    report = build_observability_intelligence_report(
        deployment_info={"success": True, "deployed_at": "2026-10-06T00:00:00+00:00", "environment": "staging"},
        otel_trace_context={"trace_id": "abc", "spans": []},
        synthetic_monitoring_report={"all_passed": True, "passed": 2, "total": 2, "journeys": [{"passed": True, "latency_ms": 12}]},
        stress_report={"performance_verdict": "pass", "p95_ms": 300},
        service_graph={"root_service": "api", "nodes": {"api": {}}, "node_count": 1},
    )
    assert report["gate_verdict"] in {"pass", "warn"}
    assert report["deploy_correlation"]["correlation_confidence"] >= 0.5


def test_evaluate_observability_gates_fail_on_synthetic():
    report = {
        "deploy_correlation": {"monitoring_status": "pending"},
        "metric_anomalies": {"verdict": "pass", "anomalies": []},
        "log_signals": {"status": "healthy"},
        "signals": {"synthetic_monitoring": {"all_passed": False}},
    }
    gates = evaluate_observability_gates(report)
    assert gates["gate_verdict"] == "fail"

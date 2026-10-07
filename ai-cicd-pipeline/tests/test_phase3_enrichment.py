"""Phase 3 SRE intelligence unit tests."""

import pytest

from app.utils.chaos_engineering import run_chaos_experiment, run_chaos_suite
from app.utils.error_budget import compute_error_budget
from app.utils.evidence_graph import build_evidence_graph
from app.utils.incident_commander import run_incident_commander
from app.utils.otel_context import build_otel_trace_context
from app.utils.rca_engine import analyze_root_cause
from app.utils.runbook_automation import match_runbooks
from app.utils.synthetic_monitoring import run_synthetic_checks


def test_evidence_graph_links_artifacts() -> None:
    graph = build_evidence_graph(
        run_id="abc12345-0000-0000-0000-000000000000",
        repo="org/app",
        commit="deadbeef",
        branch="main",
        artifacts={
            "code_analysis": {"severity": "pass"},
            "monitoring_alert": {"assessment": {"status": "degraded"}},
        },
    )
    assert graph["incident_id"].startswith("INC-")
    assert graph["node_count"] >= 4
    assert any(n["type"] == "alert" for n in graph["nodes"])


def test_rca_health_failure_hypothesis() -> None:
    rca = analyze_root_cause(
        metrics={"health_status_code": 503, "response_time_ms": 3200},
        artifacts={"change_risk_report": {"final_risk": 20}},
    )
    causes = [h["cause"] for h in rca["hypotheses"]]
    assert any("Health check" in c for c in causes)


def test_runbook_matches_redis_logs() -> None:
    rca = analyze_root_cause(log_excerpt="ERROR redis connection pool exhausted on 6379")
    books = match_runbooks("redis connection pool", rca)
    assert books["matched_count"] >= 1
    assert books["runbooks"][0]["runbook_id"] == "REDIS-004"


def test_incident_commander_bundle() -> None:
    commander = run_incident_commander(
        run_id="abc12345-0000-0000-0000-000000000000",
        repo="org/app",
        branch="main",
        commit="cafebabe",
        artifacts={"deployment_info": {"image_tag": "v1.2.3"}},
        metrics={"health_status_code": 503, "error_count": 12},
        log_excerpt="health check failed",
    )
    assert commander["severity"] == "P1"
    assert commander["lifecycle"]["status"] == "investigating"
    assert commander["evidence_graph"]["incident_id"]
    assert commander["postmortem"]["summary"]


def test_otel_trace_context_export() -> None:
    ctx = build_otel_trace_context(
        run_id="abc12345-0000-0000-0000-000000000000",
        commit="abc",
        repo="org/app",
        environment="staging",
    )
    assert len(ctx["trace_id"]) == 32
    assert len(ctx["spans"]) >= 3


def test_error_budget_from_slo() -> None:
    budget = compute_error_budget(
        {"window_runs": 20, "success_rate": 0.85},
        target_availability=0.999,
    )
    assert budget["error_budget_remaining_percent"] < 50
    assert budget["freeze_risky_releases"] is True


def test_chaos_suite_simulated() -> None:
    suite = run_chaos_suite(simulated=True)
    assert suite["passed"] == suite["total"]
    assert suite["simulated"] is True


def test_chaos_live_requires_approval() -> None:
    report = run_chaos_experiment(simulated=False)
    assert report["status"] == "skipped"


@pytest.mark.asyncio
async def test_synthetic_monitoring_simulated() -> None:
    report = await run_synthetic_checks(simulated=True)
    assert report["all_passed"] is True
    assert report["simulated"] is True

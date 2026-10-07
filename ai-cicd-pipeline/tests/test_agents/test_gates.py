from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.approval_agent import ApprovalAgent
from app.agents.monitoring_agent import heuristic_assessment, needs_analysis
from app.agents.stress_test_agent import StressTestAgent, parse_locust_stats, verdict_for
from app.models.pipeline_artifact import PipelineArtifact


def summary(code="pass", security="low", qa="pass", stress="pass") -> dict:
    return {
        "code_analysis": {"severity": code},
        "security": {"highest_severity": security},
        "qa": {"verdict": qa},
        "stress": {"performance_verdict": stress},
        "has_warnings": False,
    }


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, []),
        ({"code": "fail"}, ["code analysis severity is fail"]),
        ({"security": "high"}, ["security severity high exceeds medium"]),
        ({"security": "medium"}, []),
        ({"qa": "fail"}, ["tests failed"]),
        ({"stress": "fail"}, ["load test failed"]),
    ],
)
def test_hard_rule_violations(kwargs, expected):
    assert ApprovalAgent.hard_rule_violations(summary(**kwargs)) == expected


async def _artifacts(db, run, **contents):
    for artifact_type, content in contents.items():
        db.add(PipelineArtifact(pipeline_run_id=run.id, artifact_type=artifact_type, content=content))
    await db.commit()


async def test_rule_engine_rejects_without_llm(pipeline_run, db_session, mock_anthropic_client):
    await _artifacts(
        db_session,
        pipeline_run,
        code_analysis={"severity": "pass"},
        security_scan={"highest_severity": "critical"},
        qa_report={"verdict": "pass"},
        stress_report={"performance_verdict": "pass"},
    )
    result = await ApprovalAgent(pipeline_run.id, db_session, mock_anthropic_client).execute()
    assert result["decision"] == "rejected"
    assert result["blocked_by"] == "rule_engine"
    mock_anthropic_client.messages.create.assert_not_called()


async def test_heuristic_approval_flags_skipped_stress(pipeline_run, db_session):
    await _artifacts(
        db_session,
        pipeline_run,
        code_analysis={"severity": "pass"},
        security_scan={"highest_severity": "low"},
        qa_report={"verdict": "pass"},
        stress_report={"performance_verdict": "warn", "skipped": True},
    )
    result = await ApprovalAgent(pipeline_run.id, db_session, None).execute()
    assert result["decision"] == "approved"
    assert "Load testing was skipped." in result["warnings"]
    assert result["risk_level"] == "medium"


@pytest.mark.parametrize(
    ("error_rate", "p95", "verdict"),
    [(0.5, 300, "pass"), (2, 300, "warn"), (0.1, 1500, "warn"), (6, 100, "fail"), (0, 2500, "fail")],
)
def test_stress_verdict_thresholds(error_rate, p95, verdict):
    assert verdict_for(error_rate, p95) == verdict


def test_parse_locust_stats_uses_aggregated_row(tmp_path: Path):
    stats = tmp_path / "stress_stats.csv"
    stats.write_text(
        "Type,Name,Request Count,Failure Count,Average Response Time,Max Response Time,Requests/s,95%\n"
        "GET,/health,900,9,40,800,30,120\n"
        "GET,/api/v1/pipeline/runs,100,1,300,2500,3,1800\n"
        ",Aggregated,1000,10,66,2500,33,400\n",
        encoding="utf-8",
    )
    rows, overall = parse_locust_stats(stats)
    assert len(rows) == 2
    assert overall["total_requests"] == 1000
    assert overall["failure_rate_pct"] == pytest.approx(1.0)
    assert overall["p95_ms"] == 400


async def test_stress_skips_with_warning_when_staging_unreachable(pipeline_run, db_session, tmp_path):
    agent = StressTestAgent(pipeline_run.id, db_session, None, str(tmp_path))
    with patch.object(agent, "_staging_reachable", AsyncMock(return_value=False)):
        result = await agent.execute()
    assert result["skipped"] is True
    assert result["performance_verdict"] == "warn"


def _metrics(**overrides):
    base = {"error_count": 0, "exception_count": 0, "health_status_code": 200, "response_time_ms": 50}
    return {**base, **overrides}


def test_monitoring_heuristics():
    assert not needs_analysis(_metrics())
    assert heuristic_assessment(_metrics())["recommended_action"] == "monitor"
    assert heuristic_assessment(_metrics(error_count=30))["status"] == "degraded"
    critical = heuristic_assessment(_metrics(health_status_code=503))
    assert critical["status"] == "critical"
    assert critical["recommended_action"] == "rollback"

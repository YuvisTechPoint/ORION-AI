import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agents.multimodal import (
    DockerfileAgent,
    GitHubLogAgent,
    LogAnalysisAgent,
    PaymentAgent,
    ProductionTriageAgent,
    artifact_from_upload,
)
from app.agents.multimodal.dockerfile_agent import analyze_dockerfile, optimize_dockerfile
from app.api.routes.multimodal import get_anthropic_client
from app.main import app
from app.models.pipeline_artifact import PipelineArtifact
from tests.conftest import make_claude_response

ANALYZE = "/api/v1/multimodal/analyze"

PAYMENTS_CSV = (
    "transaction_id,amount,currency,status,error_code,error_message,timestamp\n"
    "t1,10.00,USD,succeeded,,,2026-01-01T00:00:00Z\n"
    "t2,25.50,USD,failed,card_declined,Card declined,2026-01-01T00:01:00Z\n"
    "t3,99.99,USD,failed,processing_error,Gateway timeout,2026-01-01T00:02:00Z\n"
    "t4,5.00,USD,succeeded,,,2026-01-01T00:03:00Z\n"
)
BAD_DOCKERFILE = (
    "FROM python:3.7\n"
    "ENV DB_PASSWORD=hunter2\n"
    "ADD . /app\n"
    "RUN pip install -r /app/requirements.txt\n"
    "EXPOSE 22\n"
    'CMD ["python", "/app/main.py"]\n'
)
BUILD_LOG = (
    "2026-01-01T00:00:00Z ##[group]Run pytest\n"
    "2026-01-01T00:00:01Z ImportError: No module named requests\n"
    "2026-01-01T00:00:02Z ##[error]Process completed with exit code 1.\n"
)


@pytest.fixture
def slack():
    with patch("app.api.routes.multimodal.slack_service") as svc:
        svc.send_triage_alert = AsyncMock()
        svc.enabled = True
        yield svc


def upload(name: str, data: str | bytes, mime: str = "text/plain"):
    return ("files", (name, data.encode() if isinstance(data, str) else data, mime))


def test_artifact_from_upload_maps_extensions():
    assert artifact_from_upload("shot.PNG", None, b"\x89PNG")["type"] == "image"
    assert artifact_from_upload("report.pdf", None, b"%PDF")["type"] == "pdf"
    assert artifact_from_upload("tx.csv", None, b"a,b")["type"] == "csv"
    assert artifact_from_upload("app.log", None, b"x")["type"] == "log"
    assert artifact_from_upload("logs.zip", None, b"PK")["type"] == "zip"
    assert artifact_from_upload("Dockerfile", None, b"FROM x")["type"] == "text"


async def test_unsupported_agent_type(async_client):
    r = await async_client.post(ANALYZE, data={"agent_type": "unknown", "text_input": "hello"})
    assert r.status_code == 400


async def test_requires_some_input(async_client):
    r = await async_client.post(ANALYZE, data={"agent_type": "log"})
    assert r.status_code == 400


async def test_invalid_log_type(async_client):
    r = await async_client.post(ANALYZE, data={"agent_type": "log", "log_type": "astrology", "text_input": "x"})
    assert r.status_code == 400
    assert "log_type" in r.json()["detail"]


async def test_bad_and_missing_pipeline_run(async_client):
    r = await async_client.post(ANALYZE, data={"agent_type": "log", "text_input": "x", "pipeline_run_id": "nope"})
    assert r.status_code == 400
    r = await async_client.post(
        ANALYZE, data={"agent_type": "log", "text_input": "x", "pipeline_run_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert r.status_code == 404


async def test_payment_heuristic(async_client):
    r = await async_client.post(ANALYZE, data={"agent_type": "payment"}, files=[upload("tx.csv", PAYMENTS_CSV, "text/csv")])
    assert r.status_code == 200
    body = r.json()
    assert body["agent_type"] == "payment"
    result = body["result"]
    assert result["analysis_mode"] == "heuristic"
    assert [t["transaction_id"] for t in result["failed_transactions"]] == ["t2", "t3"]
    assert result["severity"] == "critical"
    assert result["artifacts_analyzed"] == ["tx.csv"]


async def test_payment_reconciliation_without_actuals(async_client):
    r = await async_client.post(
        "/api/v1/multimodal/payment", data={"reconcile": "true"}, files=[upload("tx.csv", PAYMENTS_CSV, "text/csv")]
    )
    assert r.status_code == 200
    recon = r.json()["result"]["reconciliation"]
    assert "unable_to_determine" in json.dumps(recon)


async def test_log_analysis_persists_to_pipeline_run(async_client, pipeline_run, db_session):
    log = "2026-01-01 ERROR worker: ModuleNotFoundError: No module named 'redis'\n2026-01-01 WARNING slow\n"
    r = await async_client.post(
        ANALYZE,
        data={"agent_type": "log_analysis", "log_type": "build_error", "pipeline_run_id": str(pipeline_run.id)},
        files=[upload("build.log", log)],
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["log_type"] == "build_error"
    assert result["severity"] in {"low", "medium", "high", "critical"}
    assert r.json()["pipeline_run_id"] == str(pipeline_run.id)

    types = (
        await db_session.execute(
            select(PipelineArtifact.artifact_type).where(PipelineArtifact.pipeline_run_id == pipeline_run.id)
        )
    ).scalars().all()
    assert "log_analysis" in types


async def test_github_actions_zip_upload(async_client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("build/3_Run pytest.txt", BUILD_LOG)
        zf.writestr("build/image.png", b"\x89PNG")
    r = await async_client.post(ANALYZE, data={"agent_type": "github"}, files=[upload("logs.zip", buf.getvalue(), "application/zip")])
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["failed_steps"]
    assert "exit code 1" in result["root_cause"]


async def test_github_run_id_requires_repo(async_client):
    r = await async_client.post(ANALYZE, data={"agent_type": "github", "github_run_id": "42", "text_input": "x"})
    assert r.status_code == 400


async def test_dockerfile_analysis_without_token_skips_pr(async_client):
    r = await async_client.post(
        ANALYZE,
        data={"agent_type": "dockerfile", "repo_full_name": "testuser/testrepo"},
        files=[upload("Dockerfile", BAD_DOCKERFILE)],
    )
    assert r.status_code == 200
    result = r.json()["result"]
    severities = {i["severity"] for i in result["dockerfile_issues"]}
    assert "critical" in severities
    assert result["optimized_dockerfile"].startswith("FROM python:3.11-slim")
    assert result["auto_pr"]["triggered"] is False
    assert "token" in result["auto_pr"]["reason"].lower()


async def test_dockerfile_opens_remediation_pr(pipeline_run, db_session):
    bundle = MagicMock(pr_url="https://github.com/o/r/pull/9", pr_number=9, branch_name="orion/fix-dockerfile-x", error=None)
    service = MagicMock()
    service.open_dockerfile_remediation_pr = AsyncMock(return_value=bundle)
    service.save_pr_registry = AsyncMock()
    service.close = AsyncMock()
    agent = DockerfileAgent(
        pipeline_run_id=pipeline_run.id,
        db=db_session,
        artifacts=[artifact_from_upload("Dockerfile", None, BAD_DOCKERFILE.encode())],
        repo_full_name="o/r",
        clone_url="https://github.com/o/r.git",
        github_token="ghp_session",
    )
    with patch("app.services.auto_pr_service.AutoPRService", return_value=service):
        result = await agent.execute()
    assert result["auto_pr"] == {
        "triggered": True,
        "pr_url": "https://github.com/o/r/pull/9",
        "pr_number": 9,
        "branch_name": "orion/fix-dockerfile-x",
        "error": None,
    }
    service.save_pr_registry.assert_awaited_once()
    blocking = service.open_dockerfile_remediation_pr.await_args.args[2]
    assert all(i["severity"] in {"high", "critical"} for i in blocking)


async def test_triage_escalates_p1_and_alerts_slack(async_client, slack):
    r = await async_client.post(
        "/api/v1/multimodal/triage",
        data={"text_input": "checkout-api is down: 503 Service Unavailable, connection refused from db"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["incident_severity"] == "P1"
    assert body["result"]["escalate_to_human"] is True
    assert body["slack_alert_sent"] is True
    slack.send_triage_alert.assert_awaited_once()


async def test_triage_low_severity_does_not_alert(async_client, slack):
    r = await async_client.post(ANALYZE, data={"agent_type": "triage", "text_input": "dashboard feels slow"})
    assert r.status_code == 200
    assert r.json()["result"]["escalate_to_human"] is False
    slack.send_triage_alert.assert_not_awaited()


async def test_git_logs_endpoint(async_client):
    r = await async_client.post(
        "/api/v1/multimodal/git-logs", data={"text_input": "fatal: Authentication failed for 'https://github.com/o/r.git/'"}
    )
    assert r.status_code == 200
    assert r.json()["agent_type"] == "git_log_analysis"


async def test_llm_result_used_when_client_available(async_client, mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_claude_response(
        {"failed_transactions": [], "error_patterns": [], "summary": "LLM says fine", "severity": "low"}
    )
    app.dependency_overrides[get_anthropic_client] = lambda: mock_anthropic_client
    try:
        r = await async_client.post(ANALYZE, data={"agent_type": "payment"}, files=[upload("tx.csv", PAYMENTS_CSV, "text/csv")])
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)
    result = r.json()["result"]
    assert result["analysis_mode"] == "llm"
    assert result["summary"] == "LLM says fine"
    content = mock_anthropic_client.messages.create.await_args.kwargs["messages"][0]["content"]
    assert any(block.get("type") == "text" and "t2" in block.get("text", "") for block in content)


async def test_llm_error_falls_back_to_heuristic(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = RuntimeError("overloaded")
    agent = PaymentAgent(anthropic_client=mock_anthropic_client, artifacts=[artifact_from_upload("tx.csv", None, PAYMENTS_CSV.encode())])
    result = await agent.execute()
    assert result["analysis_mode"] == "heuristic"
    assert "overloaded" in result["llm_unavailable_reason"]


def test_image_artifacts_become_image_blocks():
    agent = ProductionTriageAgent(artifacts=[artifact_from_upload("graph.png", "image/png", b"\x89PNG\r\n")])
    content = agent._build_multimodal_message("analyze")
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[-1] == {"type": "text", "text": "analyze"}


def test_log_agent_rejects_unknown_type():
    with pytest.raises(ValueError):
        LogAnalysisAgent(log_type="nope", artifacts=[])


def test_github_agent_classes_export():
    assert GitHubLogAgent.artifact_type == "github_log_analysis"


def test_dockerfile_rules():
    issues = analyze_dockerfile(BAD_DOCKERFILE, has_dockerignore=False)
    titles = " ".join(i["description"].lower() for i in issues)
    assert "password" in titles or "secret" in titles
    assert any("22" in i["description"] for i in issues)
    assert any(i["severity"] == "high" and "root" in i["description"].lower() for i in issues)
    assert any(".dockerignore" in i["description"] for i in issues)

    optimized = optimize_dockerfile(BAD_DOCKERFILE)
    assert "hunter2" not in optimized
    assert "USER " in optimized
    assert "HEALTHCHECK" in optimized
    assert "EXPOSE 22" not in optimized

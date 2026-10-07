"""Pipeline retry and text-tools API tests."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import async_session_factory
from app.main import app
from app.models import PipelineRun, PipelineStatus


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    mock_dispatch = MagicMock(return_value="inline")
    monkeypatch.setattr("app.routers.pipelines.dispatch_pipeline", mock_dispatch)
    return TestClient(app)


async def _seed_pipeline(status: PipelineStatus) -> str:
    pid = uuid4()
    async with async_session_factory() as session:
        session.add(
            PipelineRun(
                id=pid,
                repo_url="https://github.com/octocat/hello-world",
                commit_sha="",
                status=status,
                metadata_json={"repo_url": "https://github.com/octocat/hello-world"},
            )
        )
        await session.commit()
    return str(pid)


@pytest.mark.asyncio
async def test_retry_blocked_pipeline(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_REQUIRE_AUTH", "false")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    pid = await _seed_pipeline(PipelineStatus.BLOCKED)
    res = client.post(f"/api/pipeline/{pid}/retry")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "retrying"
    assert body["pipeline_id"] == pid
    assert body["executor"] == "inline"


@pytest.mark.asyncio
async def test_retry_completed_pipeline_returns_409(client: TestClient) -> None:
    pid = await _seed_pipeline(PipelineStatus.COMPLETED)
    res = client.post(f"/api/pipeline/{pid}/retry")
    assert res.status_code == 409


def test_text_analyze_classify_log(client: TestClient) -> None:
    res = client.post(
        "/api/tools/text-analyze",
        json={
            "text": "ERROR connection timed out after 30s",
            "operations": ["metrics", "classify_log", "errors"],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["log_type"] == "server_timeout"
    assert body["metrics"]["error_lines"] >= 1


def test_text_analyze_rejects_unknown_operation(client: TestClient) -> None:
    res = client.post(
        "/api/tools/text-analyze",
        json={"text": "hello", "operations": ["not_real"]},
    )
    assert res.status_code == 422

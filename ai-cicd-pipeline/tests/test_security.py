import pytest
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.models.pipeline_run import PipelineRun


async def test_invalid_status_filter_returns_422(async_client, pipeline_run):
    r = await async_client.get("/api/v1/pipeline/runs", params={"status": "not-a-real-status"})
    assert r.status_code == 422


async def test_invalid_artifact_type_returns_422(async_client, pipeline_run):
    r = await async_client.get(f"/api/v1/pipeline/runs/{pipeline_run.id}/artifacts/not_real_type")
    assert r.status_code == 422


async def test_trigger_deduplicates_inflight_run(async_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "deploy_mode", "skip")

    def fake_head(url: str, branch: str) -> str:
        return "abc123def456abc123def456abc123def456abc1"

    with patch("app.api.routes.pipeline._resolve_head", fake_head):
        with patch("app.api.routes.pipeline.dispatch_pipeline", return_value="inline") as dispatch:
            body = {
                "clone_url": "https://github.com/octocat/Hello-World.git",
                "branch": "master",
                "repo_full_name": "octocat/Hello-World",
            }
            first = await async_client.post("/api/v1/pipeline/trigger", json=body)
            assert first.status_code == 202
            assert first.json()["status"] == "accepted"

            second = await async_client.post("/api/v1/pipeline/trigger", json=body)
            assert second.status_code == 202
            assert second.json()["status"] == "duplicate"
            assert second.json()["pipeline_run_id"] == first.json()["pipeline_run_id"]
            assert dispatch.call_count == 2


async def test_api_require_auth_blocks_trigger(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "api_require_auth", True)
    monkeypatch.setattr(settings, "orion_api_key", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/pipeline/trigger",
            json={"clone_url": "https://github.com/octocat/Hello-World.git", "branch": "master"},
        )
        assert r.status_code == 401


async def test_api_key_allows_trigger(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "api_require_auth", True)
    monkeypatch.setattr(settings, "orion_api_key", "test-secret-key")

    def fake_head(url: str, branch: str) -> str:
        return "fedcba9876543210fedcba9876543210fedcba98"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.api.routes.pipeline._resolve_head", fake_head):
            with patch("app.api.routes.pipeline.dispatch_pipeline", return_value="inline"):
                r = await client.post(
                    "/api/v1/pipeline/trigger",
                    json={"clone_url": "https://github.com/octocat/Hello-World.git", "branch": "master"},
                    headers={"X-ORION-API-Key": "test-secret-key"},
                )
        assert r.status_code == 202


async def test_local_trigger_requires_git_dir(async_client, tmp_path):
    not_git = tmp_path / "plain"
    not_git.mkdir()
    r = await async_client.post(
        "/api/v1/pipeline/trigger",
        json={"clone_url": str(not_git), "branch": "main"},
    )
    assert r.status_code == 400
    assert "git repository" in r.json()["detail"].lower()


def test_validate_startup_rejects_production_placeholders():
    from app.config import Settings

    cfg = Settings(
        app_env="production",
        secret_key="your-secret-key-here",
        session_secret_key="your-session-secret-here",
        github_webhook_secret="your-webhook-secret",
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        cfg.validate_startup()

"""Tests for Command Hub control-plane federation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from hub.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_control_plane_health(client):
    with patch(
        "hub.federation.adapters.fetch_json",
        new=AsyncMock(side_effect=[(200, {"status": "ok"}), (200, {"ready": True})] * 3),
    ):
        resp = client.get("/api/v1/control-plane/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hub_status"] == "ok"
    assert "stacks" in body
    assert resp.headers.get("X-Correlation-ID")


def test_federated_pipelines_merge(client):
    orion_rows = {
        "items": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "repo_full_name": "acme/orion-app",
                "branch": "main",
                "commit_id": "a" * 40,
                "short_commit_id": "aaaaaaaa",
                "status": "deployed",
                "correlation_id": "abc123",
                "created_at": "2026-10-06T00:00:00+00:00",
            }
        ]
    }

    async def fake_fetch(url, **kwargs):
        if "/api/v1/pipeline/runs" in url:
            return 200, orion_rows
        if url.endswith("/pipelines"):
            return 200, [{"pipeline_id": "p1", "repo_name": "demo", "status": "running", "current_stage": "qa", "created_at": "2026-10-06T00:00:00+00:00", "updated_at": "2026-10-06T00:01:00+00:00"}]
        if url.endswith("/api/pipelines"):
            return 200, [{"id": "22222222-2222-2222-2222-222222222222", "repo_url": "https://github.com/acme/platform", "status": "completed", "created_at": "2026-10-06T00:00:00+00:00"}]
        return 404, {}

    with patch("hub.federation.adapters.fetch_json", new=AsyncMock(side_effect=fake_fetch)):
        resp = client.get("/api/v1/control-plane/pipelines?limit=10")
    assert resp.status_code == 200
    items = resp.json()["items"]
    stacks = {i["stack"] for i in items}
    assert "orion" in stacks
    assert any(i["correlation_id"] == "abc123" for i in items)


def test_pipeline_timeline(client):
    run_id = "orion:11111111-1111-1111-1111-111111111111"

    async def fake_get_run(stack, native_id, **kwargs):
        from hub.federation.models import UnifiedPipelineRun

        return UnifiedPipelineRun(
            id=f"{stack}:{native_id}",
            stack="orion",
            native_id=native_id,
            repository="acme/orion-app",
            status="running_qa",
        )

    with patch("hub.server.get_run", new=AsyncMock(side_effect=fake_get_run)):
        resp = client.get(f"/api/v1/control-plane/pipelines/{run_id}/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_status"] == "running_qa"
    assert any(s["key"] == "running_qa" and s["state"] == "active" for s in body["stages"])


def test_control_plane_retry(client):
    with patch(
        "hub.server.control_action",
        new=AsyncMock(return_value=(202, {"status": "retrying"})),
    ):
        resp = client.post("/api/v1/control-plane/pipelines/orion:abc/retry")
    assert resp.status_code == 200
    assert resp.json()["action"] == "retry"

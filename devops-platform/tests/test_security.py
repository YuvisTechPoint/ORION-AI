"""API_REQUIRE_AUTH and WebSocket auth tests."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    mock_dispatch = MagicMock(return_value="inline")
    monkeypatch.setattr("app.routers.pipelines.dispatch_pipeline", mock_dispatch)
    return TestClient(app)


def test_api_require_auth_blocks_trigger(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "api_require_auth", True)
    monkeypatch.setattr(settings, "orion_api_key", "")
    res = client.post(
        "/api/pipeline/trigger",
        json={"repo_url": "https://github.com/octocat/hello-world"},
    )
    assert res.status_code == 401


def test_api_key_allows_trigger(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "api_require_auth", True)
    monkeypatch.setattr(settings, "orion_api_key", "test-secret-key")
    res = client.post(
        "/api/pipeline/trigger",
        json={"repo_url": "https://github.com/octocat/hello-world"},
        headers={"X-ORION-API-Key": "test-secret-key"},
    )
    assert res.status_code == 200


def test_ws_requires_api_key_when_auth_enabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "api_require_auth", True)
    monkeypatch.setattr(settings, "orion_api_key", "test-secret-key")
    pipeline_id = str(uuid4())
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/{pipeline_id}"):
            pass

    with client.websocket_connect(f"/ws/{pipeline_id}?api_key=test-secret-key") as ws:
        ws.send_json({"type": "ping"})

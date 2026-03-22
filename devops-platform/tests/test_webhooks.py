"""GitHub webhook endpoint tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _sign(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    mock_celery = MagicMock()
    mock_celery.delay = MagicMock(return_value=None)
    monkeypatch.setattr("app.routers.webhooks.run_pipeline", mock_celery)
    return TestClient(app)


def test_github_webhook_enqueues_pipeline(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "repository": {
            "clone_url": "https://github.com/octocat/hello-world.git",
            "html_url": "https://github.com/octocat/hello-world",
        },
        "after": "abc123",
    }
    body = json.dumps(payload).encode()
    sig = _sign(body, "test-webhook-secret")
    res = client.post("/webhook/github", content=body, headers={"X-Hub-Signature-256": sig})
    assert res.status_code == 200
    data = res.json()
    assert "pipeline_id" in data
    assert data.get("status") == "enqueued"


def test_github_webhook_rejects_bad_signature(client: TestClient) -> None:
    payload = {"repository": {"clone_url": "https://github.com/o/r.git"}}
    body = json.dumps(payload).encode()
    res = client.post("/webhook/github", content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef"})
    assert res.status_code == 401

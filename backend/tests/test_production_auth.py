from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from api.routes import get_orchestrator
from core.config import Settings
from main import create_app
from services.orchestrator import Orchestrator


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_webhook_rejects_missing_signature(tmp_path) -> None:
    db_path = tmp_path / "wh.db"
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
            GITHUB_WEBHOOK_SECRET="prod-webhook-secret",
        )
    )
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    payload = json.dumps({"ref": "refs/heads/main", "repository": {"full_name": "o/r"}}).encode()
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/webhook/github",
            content=payload,
            headers={"Content-Type": "application/json", "X-GitHub-Event": "push"},
        )
        assert res.status_code == 401
    app.dependency_overrides.clear()


def test_webhook_rejects_invalid_signature(tmp_path) -> None:
    db_path = tmp_path / "wh2.db"
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
            GITHUB_WEBHOOK_SECRET="prod-webhook-secret",
        )
    )
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    payload = json.dumps({"ref": "refs/heads/main", "repository": {"full_name": "o/r"}}).encode()
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/webhook/github",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=deadbeef",
            },
        )
        assert res.status_code == 401
    app.dependency_overrides.clear()


def test_intelligence_requires_auth_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AUTH_API_KEYS_JSON", '{"dash-key":{"user_id":"ops","roles":["viewer"]}}')
    client = TestClient(create_app())
    denied = client.get("/api/v1/intelligence/dashboard")
    assert denied.status_code == 401
    allowed = client.get("/api/v1/intelligence/dashboard", headers={"X-API-Key": "dash-key"})
    assert allowed.status_code == 200


def test_production_auto_enables_api_require_auth() -> None:
    cfg = Settings(APP_ENV="production", API_REQUIRE_AUTH=False)
    assert cfg.api_require_auth is True

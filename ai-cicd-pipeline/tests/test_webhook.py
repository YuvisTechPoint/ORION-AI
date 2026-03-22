import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings


def _sign(body: bytes) -> str:
    return (
        "sha256="
        + hmac.new(
            settings.github_webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
    )


def test_valid_hmac_returns_202(client, sample_github_payload: dict) -> None:
    body = json.dumps(sample_github_payload).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": _sign(body),
        "X-GitHub-Event": "push",
        "Content-Type": "application/json",
    }

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def add(self, obj):
            obj.id = uuid.uuid4()

        async def commit(self):
            return None

        async def refresh(self, obj):
            return None

    with patch("app.api.routes.webhook.run_pipeline_task") as task:
        task.delay = MagicMock()
        with patch(
            "app.api.routes.webhook.AsyncSessionLocal", lambda: DummySession()
        ):
            with patch("app.api.routes.webhook.github_service") as gh:
                gh.set_commit_status = AsyncMock(return_value={})
                res = client.post(
                    "/api/v1/webhook/github", content=body, headers=headers
                )
    assert res.status_code == 202


def test_invalid_hmac_returns_403(client, sample_github_payload: dict) -> None:
    body = json.dumps(sample_github_payload).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": "sha256=deadbeef",
        "X-GitHub-Event": "push",
        "Content-Type": "application/json",
    }
    res = client.post("/api/v1/webhook/github", content=body, headers=headers)
    assert res.status_code == 403


def test_tag_push_ignored(client) -> None:
    payload = {
        "ref": "refs/tags/v1.0.0",
        "after": "a" * 40,
        "commits": [],
        "repository": {
            "full_name": "acme/demo",
            "clone_url": "https://github.com/acme/demo.git",
        },
        "pusher": {"name": "alice"},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": _sign(body),
        "X-GitHub-Event": "push",
        "Content-Type": "application/json",
    }
    res = client.post("/api/v1/webhook/github", content=body, headers=headers)
    assert res.status_code == 200


def test_missing_header_returns_403(client, sample_github_payload: dict) -> None:
    body = json.dumps(sample_github_payload).encode("utf-8")
    headers = {"X-GitHub-Event": "push", "Content-Type": "application/json"}
    res = client.post("/api/v1/webhook/github", content=body, headers=headers)
    assert res.status_code == 403


def test_invalid_json_returns_400(client) -> None:
    body = b"{not-json"
    headers = {
        "X-Hub-Signature-256": _sign(body),
        "X-GitHub-Event": "push",
        "Content-Type": "application/json",
    }
    res = client.post("/api/v1/webhook/github", content=body, headers=headers)
    assert res.status_code == 400

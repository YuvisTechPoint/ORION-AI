import json
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from api import routes as api_routes
from api.routes import get_orchestrator
from core.config import Settings, get_settings
from core.llm_client import LLMClient
from main import app
from models.schemas import PipelineState
from services.orchestrator import Orchestrator
from services.github_service import GitHubService


@pytest.mark.asyncio
async def test_fetch_workflow_logs_soft_fails_when_run_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run_gh_command(args: list[str], context: str) -> str:
        if args[:2] == ["auth", "status"]:
            return "ok"
        if args[:2] == ["run", "list"]:
            return json.dumps(
                [
                    {
                        "databaseId": 23399562999,
                        "workflowName": "CI",
                        "status": "in_progress",
                        "conclusion": "",
                        "url": "https://github.com/example/repo/actions/runs/23399562999",
                    }
                ]
            )
        raise AssertionError(f"unexpected gh command: {args}")

    monkeypatch.setattr(api_routes, "_run_gh_command", _fake_run_gh_command)

    logs, metadata = await api_routes._fetch_github_workflow_logs_via_gh("example/repo", "main")

    assert "currently in_progress" in logs
    assert metadata["run_id"] == "23399562999"
    assert metadata["status"] == "in_progress"


def _fake_generate(self: LLMClient, prompt: str, **kwargs) -> str:
    if "Code Analysis Agent" in prompt:
        return json.dumps(
            {
                "summary": "quality reviewed",
                "issues": [],
                "quality_score": 96,
                "suggestions": ["solid"],
            }
        )
    if "Security Agent" in prompt:
        return json.dumps({"summary": "secure", "issues": [], "blocked": False})
    if "Pipeline Control Agent" in prompt:
        return json.dumps({"next_stage": "deployment", "reason": "approved", "approved": True})
    if "Deployment Agent" in prompt:
        return json.dumps({"status": "deployed", "reason": "ok", "environment": "staging"})
    if "Monitoring Agent" in prompt:
        return json.dumps(
            {
                "summary": "anomaly detected",
                "anomalies": ["db timeout"],
                "suggestions": ["increase pool size"],
            }
        )
    return json.dumps({"summary": "unused"})


def test_submit_status_and_logs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(LLMClient, "generate", _fake_generate)

    db_path = tmp_path / "api.db"
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
            AUTH_ENABLED=True,
            AUTH_API_KEYS_JSON='{"approver-key":{"user_id":"qa","roles":["approver"]}}',
        )
    )
    test_settings = Settings(
        DATABASE_URL=f"sqlite:///{db_path}",
        QUEUE_BACKEND="memory",
        QA_MODE="simulated",
        AUTH_ENABLED=True,
        AUTH_API_KEYS_JSON='{"approver-key":{"user_id":"qa","roles":["approver"]}}',
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["llm_mode"] in {"live", "mock"}
        assert health.json()["auth_enabled"] is True
        assert health.json()["qa_mode"] in {"simulated", "real"}

        submit = client.post(
            "/submit-code",
            json={
                "repo_name": "svc",
                    "code": "def noop():\\n    return 1",
                "diff": "",
                "config_text": "",
                "multimodal_inputs": [
                    {"modality": "code", "content": "def noop(): return 1", "name": "inline_snippet", "metadata": {}},
                    {"modality": "metrics", "content": "cpu=84,latency_p95=340ms", "name": "qa_metrics", "metadata": {}},
                ],
            },
        )
        assert submit.status_code == 200
        submit_data = submit.json()
        assert submit_data["status"] == "completed"

        pipeline_id = submit_data["pipeline_id"]

        with client.websocket_connect(f"/ws/pipeline-status/{pipeline_id}") as ws:
            message = ws.receive_json()
            assert message["pipeline_id"] == pipeline_id

        trigger_unauthorized = client.post(
            "/trigger-deployment",
            json={"pipeline_id": pipeline_id, "approved_by": "tester"},
        )
        assert trigger_unauthorized.status_code in {401, 403}

        trigger_authorized = client.post(
            "/trigger-deployment",
            headers={"X-API-Key": "approver-key"},
            json={"pipeline_id": pipeline_id, "approved_by": "tester"},
        )
        assert trigger_authorized.status_code == 200

        status = client.get(f"/pipeline-status/{pipeline_id}")
        assert status.status_code == 200
        assert status.json()["current_stage"] == "completed"

        logs = client.post(
            "/analyze-logs",
            json={
                "pipeline_id": pipeline_id,
                "logs": "ERROR timeout",
                "multimodal_inputs": [
                    {"modality": "log", "content": "ERROR timeout", "name": "runtime_log", "metadata": {}},
                    {"modality": "metrics", "content": "cpu=91", "name": "runtime_metric", "metadata": {}},
                ],
            },
        )
        assert logs.status_code == 200
        assert "db timeout" in logs.json()["anomalies"]

        with client.websocket_connect("/ws/analyze-logs") as ws:
            ws.send_json(
                {
                    "pipeline_id": pipeline_id,
                    "logs": "ERROR timeout",
                    "multimodal_inputs": [],
                }
            )
            monitoring_event = ws.receive_json()
            assert monitoring_event["type"] == "monitoring_result"
            assert monitoring_event["pipeline_id"] == pipeline_id
            assert "db timeout" in monitoring_event["result"]["anomalies"]

        runtime = client.get("/runtime-config")
        assert runtime.status_code == 200
        runtime_json = runtime.json()
        assert runtime_json["queue_backend"] == "memory"
        assert runtime_json["database_backend"] == "sqlite"
        assert runtime_json["qa_mode"] == "simulated"

    app.dependency_overrides.clear()


def test_github_pr_webhook_deletes_branch(monkeypatch, tmp_path) -> None:
    async def _fake_delete_branch(self, repo_full_name: str, branch_name: str) -> bool:
        return True

    monkeypatch.setattr(GitHubService, "delete_branch", _fake_delete_branch)

    db_path = tmp_path / "api_webhook.db"
    webhook_secret = "test-webhook-secret"
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
            GITHUB_WEBHOOK_SECRET=webhook_secret,
        )
    )
    test_settings = Settings(
        DATABASE_URL=f"sqlite:///{db_path}",
        QUEUE_BACKEND="memory",
        QA_MODE="simulated",
        GITHUB_WEBHOOK_SECRET=webhook_secret,
    )

    state = PipelineState(repo_name="svc")
    state.artifacts["auto_pr_registry"] = {
        "branches": [
            {
                "branch_name": "orion/security-fixes",
                "pr_number": 12,
                "category": "security",
                "merged": False,
                "deleted": False,
            }
        ]
    }
    orchestrator.state_store.upsert(state)

    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_settings] = lambda: test_settings

    payload = {
        "action": "closed",
        "pull_request": {
            "merged": True,
            "number": 12,
            "head": {"ref": "orion/security-fixes"},
        },
        "repository": {"full_name": "owner/repo"},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/webhook/github/pr",
            content=body,
            headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["processed"] is True
        updated = orchestrator.get_status(state.pipeline_id)
        branch = updated.artifacts["auto_pr_registry"]["branches"][0]
        assert branch["merged"] is True
        assert branch["deleted"] is True

    app.dependency_overrides.clear()


def _tiny_repo_zip() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("owner-repo/app.py", "def noop():\n    return 1\n")
    return buffer.getvalue()


class _FakeGithubResponse:
    def __init__(self, status_code: int, payload: dict | bytes) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = payload if isinstance(payload, bytes) else b""

    def json(self) -> dict:
        assert isinstance(self._payload, dict)
        return self._payload


class _FakeGithubClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, timeout: float = 20.0):
        if "/zipball/" in url:
            return _FakeGithubResponse(200, _tiny_repo_zip())
        return _FakeGithubResponse(200, {"default_branch": "main"})


def test_submit_github_wait_false_keeps_seed_and_completes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    monkeypatch.setattr("httpx.AsyncClient", _FakeGithubClient)

    db_path = tmp_path / "wait_false.db"
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
        )
    )
    test_settings = Settings(
        DATABASE_URL=f"sqlite:///{db_path}",
        QUEUE_BACKEND="memory",
        QA_MODE="simulated",
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app) as client:
        submit = client.post(
            "/submit-github?wait=false&force_real=false",
            data={"repo_url": "https://github.com/owner/repo", "branch": "main"},
        )
        assert submit.status_code == 200
        body = submit.json()
        assert body["status"] == "running"
        pipeline_id = body["pipeline_id"]

        finished = None
        for _ in range(40):
            status = client.get(f"/pipeline-status/{pipeline_id}")
            assert status.status_code == 200
            finished = status.json()
            if finished["status"] in {"completed", "failed", "blocked", "cancelled"}:
                break
        assert finished is not None
        assert finished["pipeline_id"] == pipeline_id
        assert finished["status"] in {"completed", "failed", "blocked"}

    app.dependency_overrides.clear()


def test_retry_blocked_pipeline(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_REQUIRE_AUTH", "false")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    db_path = tmp_path / "retry.db"
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
        )
    )
    state = PipelineState(repo_name="demo", status="blocked", current_stage="blocked")
    state.artifacts["submit_request"] = {
        "repo_name": "demo",
        "code": "print('hello')\n",
        "diff": "",
        "enable_auto_pr": False,
    }
    orchestrator.state_store.upsert(state)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    with TestClient(app) as client:
        retry = client.post(f"/pipelines/{state.pipeline_id}/retry")
        assert retry.status_code == 200
        body = retry.json()
        assert body["status"] == "running"
        assert body["current_stage"] == "dev"

        completed = client.post(f"/pipelines/{state.pipeline_id}/retry")
        assert completed.status_code == 409
    app.dependency_overrides.clear()


def test_retry_requires_auth_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AUTH_API_KEYS_JSON", '{"retry-key":{"user_id":"qa","roles":["approver"]}}')
    db_path = tmp_path / "retry-auth.db"
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
            API_REQUIRE_AUTH=True,
            AUTH_API_KEYS_JSON='{"retry-key":{"user_id":"qa","roles":["approver"]}}',
        )
    )
    state = PipelineState(repo_name="demo", status="blocked", current_stage="blocked")
    state.artifacts["submit_request"] = {
        "repo_name": "demo",
        "code": "print('hello')\n",
        "diff": "",
        "enable_auto_pr": False,
    }
    orchestrator.state_store.upsert(state)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    with TestClient(app) as client:
        denied = client.post(f"/pipelines/{state.pipeline_id}/retry")
        assert denied.status_code == 401
        allowed = client.post(
            f"/pipelines/{state.pipeline_id}/retry",
            headers={"X-API-Key": "retry-key"},
        )
        assert allowed.status_code == 200
    app.dependency_overrides.clear()


def test_list_and_cancel_pipeline(tmp_path) -> None:
    db_path = tmp_path / "list.db"
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
        )
    )
    state = PipelineState(repo_name="demo", status="running")
    orchestrator.state_store.upsert(state)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    with TestClient(app) as client:
        listed = client.get("/pipelines")
        assert listed.status_code == 200
        assert listed.json()[0]["pipeline_id"] == state.pipeline_id
        cancelled = client.post(f"/pipelines/{state.pipeline_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["cancelled"] is True
    app.dependency_overrides.clear()

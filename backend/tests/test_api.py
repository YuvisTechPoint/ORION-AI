import json
import hashlib
import hmac

from fastapi.testclient import TestClient

from api.routes import get_orchestrator
from core.config import Settings, get_settings
from core.llm_client import LLMClient
from main import app
from models.schemas import PipelineState
from services.orchestrator import Orchestrator
from services.github_service import GitHubService


def _fake_generate(self: LLMClient, prompt: str) -> str:
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
    orchestrator = Orchestrator(
        Settings(
            DATABASE_URL=f"sqlite:///{db_path}",
            QUEUE_BACKEND="memory",
            QA_MODE="simulated",
            GITHUB_TOKEN="secret-token",
        )
    )
    test_settings = Settings(
        DATABASE_URL=f"sqlite:///{db_path}",
        QUEUE_BACKEND="memory",
        QA_MODE="simulated",
        GITHUB_TOKEN="secret-token",
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
    sig = "sha256=" + hmac.new(b"secret-token", body, hashlib.sha256).hexdigest()

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

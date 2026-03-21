from __future__ import annotations

import io
import zipfile

import pytest

from agents.multimodal.github_log_agent import GitHubLogAgent
from agents.multimodal.payment_agent import PaymentAgent
from agents.multimodal.production_triage_agent import ProductionTriageAgent


class _DummyLLMClient:
    def generate(self, prompt: str):  # noqa: ARG002
        return {"summary": "mock"}


def _build_zip_with_txt() -> bytes:
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("step-1.txt", "Build failed at step 4")
        zf.writestr("nested/step-2.txt", "Retry recommended")
        zf.writestr("artifact.bin", b"\x00\x01\x02")
    return buff.getvalue()


def test_github_log_agent_extracts_txt_from_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def _fake_call(self, system_prompt: str, text_prompt: str, max_tokens: int = 3000):  # noqa: ARG001
        captured["filenames"] = [str(item.get("filename", "")) for item in self.artifacts]
        captured["types"] = [str(item.get("type", "")) for item in self.artifacts]
        return ('{"workflow_name":"ci","summary":"ok"}', 42)

    monkeypatch.setattr(GitHubLogAgent, "_call_claude_multimodal", _fake_call)

    agent = GitHubLogAgent(
        llm_client=_DummyLLMClient(),
        artifacts=[
            {
                "type": "text",
                "content": "plain log",
                "filename": "build.log",
                "mime_type": "text/plain",
            },
            {
                "type": "text",
                "content": _build_zip_with_txt(),
                "filename": "gh_logs.zip",
                "mime_type": "application/zip",
            },
        ],
    )

    result = agent.execute()

    assert result["workflow_name"] == "ci"
    assert any(name.endswith("step-1.txt") for name in captured["filenames"])
    assert any(name.endswith("nested/step-2.txt") for name in captured["filenames"])
    assert "text" in captured["types"]


@pytest.mark.asyncio
async def test_fetch_run_logs_uses_github_actions_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    class _FakeResponse:
        def __init__(self) -> None:
            self.content = b"zip-bytes"

        def raise_for_status(self) -> None:
            return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401, ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        async def get(self, url: str, headers: dict[str, str]):
            called["url"] = url
            called["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr("agents.multimodal.github_log_agent.httpx.AsyncClient", _FakeAsyncClient)

    agent = GitHubLogAgent(llm_client=_DummyLLMClient(), artifacts=[])
    content = await agent.fetch_run_logs("owner/repo", 1234, "token-123")

    assert content == b"zip-bytes"
    assert called["url"] == "https://api.github.com/repos/owner/repo/actions/runs/1234/logs"
    assert called["headers"]["Authorization"] == "token token-123"


def test_payment_agent_prompt_is_strict_json_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def _fake_call(self, system_prompt: str, text_prompt: str, max_tokens: int = 3000):  # noqa: ARG001
        captured["system_prompt"] = system_prompt
        captured["text_prompt"] = text_prompt
        return (
            '{"failed_transactions":[],"error_patterns":[],"webhook_failures":[],"fraud_indicators":[],"total_failed_amount":"0","summary":"ok","immediate_actions":[],"severity":"low"}',
            100,
        )

    monkeypatch.setattr(PaymentAgent, "_call_claude_multimodal", _fake_call)
    agent = PaymentAgent(llm_client=_DummyLLMClient(), artifacts=[])
    result = agent.execute()

    assert "Return ONLY valid JSON" in captured["system_prompt"]
    assert "failed_transactions" in captured["system_prompt"]
    assert "webhook_failures" in captured["system_prompt"]
    assert result["severity"] == "low"


def test_payment_agent_normalizes_invalid_payload_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_call(self, system_prompt: str, text_prompt: str, max_tokens: int = 3000):  # noqa: ARG001
        return (
            '{"failed_transactions":[{"transaction_id":123,"recommended_retry":"yes"}],"error_patterns":"invalid","webhook_failures":{},"fraud_indicators":"x","total_failed_amount":10,"summary":99,"immediate_actions":"do-now","severity":"urgent"}',
            50,
        )

    monkeypatch.setattr(PaymentAgent, "_call_claude_multimodal", _fake_call)
    result = PaymentAgent(llm_client=_DummyLLMClient(), artifacts=[]).execute()

    assert set(result.keys()) >= {
        "failed_transactions",
        "error_patterns",
        "webhook_failures",
        "fraud_indicators",
        "total_failed_amount",
        "summary",
        "immediate_actions",
        "severity",
    }
    assert isinstance(result["failed_transactions"], list)
    assert isinstance(result["error_patterns"], list)
    assert isinstance(result["webhook_failures"], list)
    assert isinstance(result["fraud_indicators"], list)
    assert isinstance(result["immediate_actions"], list)
    assert result["severity"] in {"low", "medium", "high", "critical"}


def test_triage_agent_prompt_is_strict_json_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def _fake_call(self, system_prompt: str, text_prompt: str, max_tokens: int = 3000):  # noqa: ARG001
        captured["system_prompt"] = system_prompt
        captured["text_prompt"] = text_prompt
        return (
            '{"incident_severity":"P2","incident_type":"degradation","affected_services":[],"root_cause":"unknown","blast_radius":"limited","time_to_resolve_estimate_minutes":20,"immediate_actions":[],"rollback_steps":[],"post_incident_tasks":[],"monitoring_checks":[],"summary":"ok","escalate_to_human":false,"escalation_reason":null}',
            90,
        )

    monkeypatch.setattr(ProductionTriageAgent, "_call_claude_multimodal", _fake_call)
    result = ProductionTriageAgent(llm_client=_DummyLLMClient(), artifacts=[]).execute()

    assert "Return ONLY valid JSON" in captured["system_prompt"]
    assert "incident_severity" in captured["system_prompt"]
    assert "escalate_to_human" in captured["system_prompt"]
    assert result["incident_severity"] == "P2"


def test_triage_agent_normalizes_invalid_payload_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_call(self, system_prompt: str, text_prompt: str, max_tokens: int = 3000):  # noqa: ARG001
        return (
            '{"incident_severity":"P0","incident_type":"other","affected_services":"api","root_cause":404,"blast_radius":{},"time_to_resolve_estimate_minutes":"soon","immediate_actions":["restart"],"rollback_steps":"rollback","post_incident_tasks":{},"monitoring_checks":1,"summary":true,"escalate_to_human":"true","escalation_reason":11}',
            60,
        )

    monkeypatch.setattr(ProductionTriageAgent, "_call_claude_multimodal", _fake_call)
    result = ProductionTriageAgent(llm_client=_DummyLLMClient(), artifacts=[]).execute()

    assert result["incident_severity"] in {"P1", "P2", "P3", "P4"}
    assert result["incident_type"] in {"outage", "degradation", "data_loss", "security_breach", "performance"}
    assert isinstance(result["affected_services"], list)
    assert isinstance(result["immediate_actions"], list)
    assert isinstance(result["rollback_steps"], list)
    assert isinstance(result["post_incident_tasks"], list)
    assert isinstance(result["monitoring_checks"], list)
    assert isinstance(result["escalate_to_human"], bool)

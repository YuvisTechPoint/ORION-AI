import json

import pytest

from core.config import Settings
from core.llm_client import LLMClient
from models.schemas import AnalyzeLogsRequest, SubmitCodeRequest
from services.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_submit_code_blocks_on_high_severity(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    def fake_generate(self: LLMClient, prompt: str) -> str:
        if "Code Analysis Agent" in prompt:
            return json.dumps(
                {
                    "summary": "quality reviewed",
                    "issues": [],
                    "quality_score": 92,
                    "suggestions": ["looks good"],
                }
            )
        if "Security Agent" in prompt:
            return json.dumps(
                {
                    "summary": "security issues detected",
                    "issues": [
                        {
                            "type": "sql_injection",
                            "severity": "high",
                            "line": "2",
                            "fix": "Use parameterized query",
                            "snippet": "SELECT * FROM users WHERE ...",
                        }
                    ],
                    "blocked": True,
                }
            )
        return json.dumps({"summary": "unused"})

    monkeypatch.setattr(LLMClient, "generate", fake_generate)
    db_path = tmp_path / "blocked.db"
    settings = Settings(DATABASE_URL=f"sqlite:///{db_path}", QUEUE_BACKEND="memory", QA_MODE="simulated")
    orchestrator = Orchestrator(settings)

    state = await orchestrator.submit_code(
        SubmitCodeRequest(repo_name="svc", code="def noop():\n    return 1", diff="", config_text="")
    )

    assert state.current_stage == "blocked"
    assert state.status == "blocked"
    assert "security" in state.artifacts


@pytest.mark.asyncio
async def test_submit_code_completes_when_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    def fake_generate(self: LLMClient, prompt: str) -> str:
        if "Code Analysis Agent" in prompt:
            return json.dumps(
                {
                    "summary": "quality reviewed",
                    "issues": [],
                    "quality_score": 98,
                    "suggestions": ["ship it"],
                }
            )
        if "Security Agent" in prompt:
            return json.dumps({"summary": "no critical findings", "issues": [], "blocked": False})
        if "Pipeline Control Agent" in prompt:
            return json.dumps(
                {
                    "next_stage": "deployment",
                    "reason": "all quality gates passed",
                    "approved": True,
                }
            )
        if "Deployment Agent" in prompt:
            return json.dumps(
                {
                    "status": "deployed",
                    "reason": "deployment successful",
                    "environment": "staging",
                }
            )
        if "Monitoring Agent" in prompt:
            return json.dumps(
                {
                    "summary": "normal",
                    "anomalies": [],
                    "suggestions": [],
                }
            )
        return json.dumps({"summary": "unused"})

    monkeypatch.setattr(LLMClient, "generate", fake_generate)
    db_path = tmp_path / "complete.db"
    settings = Settings(DATABASE_URL=f"sqlite:///{db_path}", QUEUE_BACKEND="memory", QA_MODE="simulated")
    orchestrator = Orchestrator(settings)

    state = await orchestrator.submit_code(
        SubmitCodeRequest(repo_name="svc", code="def noop():\n    return 1", diff="", config_text="")
    )

    assert state.current_stage == "completed"
    assert state.status == "completed"

    monitoring = orchestrator.analyze_logs(AnalyzeLogsRequest(pipeline_id=state.pipeline_id, logs="INFO healthy"))
    assert monitoring.summary == "normal"


@pytest.mark.asyncio
async def test_submit_code_auto_redeploys_when_blocked_on_approval_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    def fake_generate(self: LLMClient, prompt: str) -> str:
        if "Code Analysis Agent" in prompt:
            return json.dumps(
                {
                    "summary": "quality reviewed",
                    "issues": [],
                    "quality_score": 100,
                    "suggestions": ["ship it"],
                }
            )
        if "Security Agent" in prompt:
            return json.dumps({"summary": "no critical findings", "issues": [], "blocked": False})
        # Return invalid shape for pipeline/deployment agents to force deterministic fallback policy.
        return json.dumps({"summary": "fallback"})

    monkeypatch.setattr(LLMClient, "generate", fake_generate)
    db_path = tmp_path / "auto_redeploy.db"
    settings = Settings(DATABASE_URL=f"sqlite:///{db_path}", QUEUE_BACKEND="memory", QA_MODE="simulated")
    orchestrator = Orchestrator(settings)

    state = await orchestrator.submit_code(
        SubmitCodeRequest(repo_name="svc", code="def noop():\n    return 1", diff="", config_text="")
    )

    assert state.current_stage == "completed"
    assert state.status == "completed"
    assert "deployment_auto" in state.artifacts
    assert any("Auto-remediation started" in item.get("message", "") for item in state.history)

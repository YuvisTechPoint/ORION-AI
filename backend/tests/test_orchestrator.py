import json

import pytest

from core.config import Settings
from core.llm_client import LLMClient
from models.schemas import AnalyzeLogsRequest, SubmitCodeRequest
from services.auto_pr_service import AutoPRService, IssueBundle
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


@pytest.mark.asyncio
async def test_submit_code_blocks_with_prs_sent_when_auto_pr_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    def fake_generate(self: LLMClient, prompt: str) -> str:
        if "Code Analysis Agent" in prompt:
            return json.dumps(
                {
                    "summary": "quality issues found",
                    "issues": [
                        {
                            "type": "style",
                            "severity": "medium",
                            "line": "1",
                            "fix": "Refactor naming",
                            "snippet": "x=1",
                            "file_path": "app.py",
                        }
                    ],
                    "quality_score": 70,
                    "suggestions": ["rename variables"],
                }
            )
        if "Security Agent" in prompt:
            return json.dumps({"summary": "secure", "issues": [], "blocked": False})
        return json.dumps({"summary": "unused"})

    monkeypatch.setattr(LLMClient, "generate", fake_generate)

    async def _fake_open_all_prs(self, combined_issues, repo_path, run_id, anthropic_client):  # noqa: ANN001, ARG002
        return [
            IssueBundle(
                category="code-quality",
                issues=[{"type": "style", "file_path": "app.py"}],
                file_patches=[{"file_path": "app.py", "fixed_content": "x = 1\n"}],
                branch_name="orion/code-quality-fixes",
                pr_title="fix(code-quality): automated ORION remediation",
                pr_body="body",
                pr_number=42,
            )
        ]

    monkeypatch.setattr(AutoPRService, "open_all_prs", _fake_open_all_prs)

    db_path = tmp_path / "prs_sent.db"
    settings = Settings(
        DATABASE_URL=f"sqlite:///{db_path}",
        QUEUE_BACKEND="memory",
        QA_MODE="simulated",
        GITHUB_TOKEN="test-token",
    )
    orchestrator = Orchestrator(settings)

    state = await orchestrator.submit_code(
        SubmitCodeRequest(
            repo_name="svc",
            code="x=1",
            diff="",
            config_text="",
            enable_auto_pr=True,
            repo_files={"app.py": "x=1"},
        )
    )

    assert state.current_stage == "blocked_with_prs_sent"
    assert state.status == "blocked_with_prs_sent"
    assert "full_scan_combined" in state.artifacts
    assert "auto_pr_registry" in state.artifacts

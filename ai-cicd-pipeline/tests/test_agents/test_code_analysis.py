import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agents.code_analysis_agent import CodeAnalysisAgent, files_in_diff
from app.models.pipeline_artifact import PipelineArtifact

PASS_RESPONSE = {
    "severity": "pass",
    "issues": [],
    "summary": "Clean code",
    "good_practices_found": [],
    "critical_issues_count": 0,
    "warnings_count": 0,
}
CLEAN_SOURCE = '"""Module."""\n\n\ndef add(a, b):\n    """Add numbers."""\n    return a + b\n'


def pylint_result(stdout: str) -> MagicMock:
    return MagicMock(returncode=0, stdout=stdout, stderr="")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text(CLEAN_SOURCE, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def no_git_lookup():
    with patch("app.agents.code_analysis_agent.GitService") as git:
        git.return_value.get_changed_files = AsyncMock(return_value=[])
        yield


def make_agent(run, db, client, repo: Path, diff: str) -> CodeAnalysisAgent:
    return CodeAnalysisAgent(run.id, db, client, str(repo), diff)


async def test_code_analysis_pass(pipeline_run, db_session, mock_anthropic_client, repo):
    agent = make_agent(pipeline_run, db_session, mock_anthropic_client, repo, "+++ b/app/calc.py\n+def add(a, b):")
    with (
        patch("app.agents.code_analysis_agent.subprocess.run", return_value=pylint_result("[]")),
        patch.object(agent, "_call_claude_json", AsyncMock(return_value=dict(PASS_RESPONSE))),
    ):
        result = await agent.execute()

    assert result["severity"] == "pass"
    assert result["files_analyzed"] == ["app/calc.py"]
    assert result["analysis_mode"] == "llm"


async def test_code_analysis_fail_on_errors(pipeline_run, db_session, mock_anthropic_client, repo):
    errors = [
        {"type": "error", "path": "app/calc.py", "line": i, "column": 0, "message-id": "E0602", "message": "Undefined variable"}
        for i in (1, 2, 3)
    ]
    fail_response = {**PASS_RESPONSE, "severity": "fail", "critical_issues_count": 3, "summary": "Broken"}
    agent = make_agent(pipeline_run, db_session, mock_anthropic_client, repo, "+++ b/app/calc.py\n")
    with (
        patch("app.agents.code_analysis_agent.subprocess.run", return_value=pylint_result(json.dumps(errors))),
        patch.object(agent, "_call_claude_json", AsyncMock(return_value=fail_response)),
    ):
        result = await agent.execute()
    assert result["severity"] == "fail"


async def test_code_analysis_heuristic_fails_without_llm(pipeline_run, db_session, repo):
    errors = [{"type": "error", "path": "app/calc.py", "line": i, "message-id": "E1101", "message": "x"} for i in (1, 2, 3)]
    agent = make_agent(pipeline_run, db_session, None, repo, "+++ b/app/calc.py\n")
    with patch("app.agents.code_analysis_agent.subprocess.run", return_value=pylint_result(json.dumps(errors))):
        result = await agent.execute()
    assert result["analysis_mode"] == "heuristic"
    assert result["severity"] == "fail"
    assert result["critical_issues_count"] == 3


async def test_code_analysis_saves_artifact(pipeline_run, db_session, mock_anthropic_client, repo):
    agent = make_agent(pipeline_run, db_session, mock_anthropic_client, repo, "+++ b/app/calc.py\n")
    mock_anthropic_client.messages.create.return_value.content[0].text = json.dumps(PASS_RESPONSE)
    with patch("app.agents.code_analysis_agent.subprocess.run", return_value=pylint_result("[]")):
        await agent.execute()

    artifacts = (
        await db_session.execute(
            select(PipelineArtifact).where(
                PipelineArtifact.pipeline_run_id == pipeline_run.id,
                PipelineArtifact.artifact_type == "code_analysis",
            )
        )
    ).scalars().all()
    assert len(artifacts) == 1
    assert artifacts[0].content["severity"] == "pass"
    assert artifacts[0].tokens_used is None or artifacts[0].tokens_used >= 0


async def test_code_analysis_handles_pylint_crash(pipeline_run, db_session, mock_anthropic_client, repo):
    agent = make_agent(pipeline_run, db_session, mock_anthropic_client, repo, "+++ b/app/calc.py\n")
    with (
        patch(
            "app.agents.code_analysis_agent.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pylint", timeout=30),
        ),
        patch.object(agent, "_call_claude_json", AsyncMock(return_value=dict(PASS_RESPONSE))),
    ):
        result = await agent.execute()
    assert result["severity"] == "pass"
    assert isinstance(result["issues"], list)


async def test_code_analysis_truncates_large_diff(pipeline_run, db_session, mock_anthropic_client, repo):
    diff = "+++ b/app/calc.py\n" + ("+x = 1\n" * 3000)
    assert len(diff) >= 20000
    agent = make_agent(pipeline_run, db_session, mock_anthropic_client, repo, diff)
    claude = AsyncMock(return_value=dict(PASS_RESPONSE))
    with (
        patch("app.agents.code_analysis_agent.subprocess.run", return_value=pylint_result("[]")),
        patch.object(agent, "_call_claude_json", claude),
    ):
        await agent.execute()
    user_message = claude.call_args.args[1]
    assert len(user_message) <= 12000


def test_files_in_diff_skips_dev_null(sample_diff_text):
    assert files_in_diff(sample_diff_text) == ["app/api/users.py"]
    assert files_in_diff("+++ /dev/null\n") == []

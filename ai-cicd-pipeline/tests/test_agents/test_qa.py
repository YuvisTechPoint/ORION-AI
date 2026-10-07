import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.qa_agent import QAAgent


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_users.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("x = 1\n")
    return tmp_path


def agent_with_report(run, db, client, repo: Path, report: dict | None, returncode: int) -> QAAgent:
    agent = QAAgent(run.id, db, client, str(repo))
    report_path = repo.parent / f"{repo.name}-report.json"
    agent._report_path = lambda: report_path  # type: ignore[method-assign]

    def fake_pytest(path: Path, test_targets=None) -> tuple[int, str]:
        if report is not None:
            path.write_text(json.dumps(report), encoding="utf-8")
        return returncode, "pytest output"

    agent._run_pytest = fake_pytest  # type: ignore[method-assign]
    return agent


async def test_failures_fail_the_gate_and_map_to_files(pipeline_run, db_session, repo, sample_pytest_report):
    agent = agent_with_report(pipeline_run, db_session, None, repo, sample_pytest_report, 1)
    result = await agent.execute()

    assert result["verdict"] == "fail"
    assert result["test_summary"]["total"] == 7
    assert result["test_summary"]["failed"] == 2
    failed = {c["test"] for c in result["root_causes"]}
    assert failed == {"tests/test_users.py::test_user_creation", "tests/test_models.py::test_delete_cascade"}
    issue_files = {i["file"] for i in result["issues"]}
    assert {"tests/test_users.py", "tests/test_models.py", "app/models.py"} <= issue_files


async def test_llm_cannot_pass_real_failures(pipeline_run, db_session, mock_anthropic_client, repo, sample_pytest_report):
    agent = agent_with_report(pipeline_run, db_session, mock_anthropic_client, repo, sample_pytest_report, 1)
    with patch.object(agent, "_call_claude_json", AsyncMock(return_value={"verdict": "pass", "summary": "looks flaky"})):
        result = await agent.execute()
    assert result["verdict"] == "fail"
    assert result["analysis_mode"] == "llm"


async def test_all_passing_skips_llm(pipeline_run, db_session, mock_anthropic_client, repo):
    report = {"summary": {"total": 3, "passed": 3}, "duration": 0.5, "tests": []}
    agent = agent_with_report(pipeline_run, db_session, mock_anthropic_client, repo, report, 0)
    result = await agent.execute()
    assert result["verdict"] == "pass"
    mock_anthropic_client.messages.create.assert_not_called()


async def test_no_tests_collected_passes(pipeline_run, db_session, repo):
    agent = agent_with_report(pipeline_run, db_session, None, repo, {"summary": {"total": 0}, "tests": []}, 5)
    assert (await agent.execute())["verdict"] == "pass"


async def test_infrastructure_error_does_not_block(pipeline_run, db_session, repo):
    agent = agent_with_report(pipeline_run, db_session, None, repo, None, 127)
    result = await agent.execute()
    assert result["verdict"] == "pass"
    assert result["infrastructure_error"] is True


async def test_repo_without_tests_is_skipped(pipeline_run, db_session, tmp_path):
    result = await QAAgent(pipeline_run.id, db_session, None, str(tmp_path)).execute()
    assert result["skipped"] is True
    assert result["verdict"] == "pass"
    assert result["analysis_mode"] == "simulated"
    assert "no tests/" in result["summary"].lower()

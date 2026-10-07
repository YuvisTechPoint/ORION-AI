from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agents.orchestrator import PipelineOrchestrator, block_status_for, has_warnings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.auto_pr_service import IssueBundle

CLEAN = {
    "code_issues": {"severity": "pass", "issues": []},
    "security_issues": {"highest_severity": None, "vulnerabilities": []},
    "qa_issues": {"verdict": "pass", "issues": []},
}


@pytest.mark.parametrize(
    ("combined", "expected"),
    [
        (CLEAN, None),
        ({**CLEAN, "code_issues": {"severity": "fail"}}, "blocked_code"),
        ({**CLEAN, "security_issues": {"highest_severity": "critical"}}, "blocked_security"),
        ({**CLEAN, "security_issues": {"highest_severity": "medium"}}, None),
        ({**CLEAN, "qa_issues": {"verdict": "fail"}}, "blocked_tests"),
        ({**CLEAN, "qa_issues": {"error": "boom", "skipped": True}}, None),
    ],
)
def test_block_status_for(combined, expected):
    assert block_status_for(combined)[0] == expected


def test_has_warnings():
    assert not has_warnings(CLEAN)
    assert has_warnings({**CLEAN, "code_issues": {"severity": "warn"}})
    assert has_warnings({**CLEAN, "qa_issues": {"skipped": True}})


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.orch = PipelineOrchestrator()
        self.orch.slack_service = MagicMock()
        for name in ("send_pipeline_start", "send_pipeline_blocked", "send_pipeline_deployed"):
            setattr(self.orch.slack_service, name, AsyncMock())
        git = MagicMock()
        git.clone_repo = AsyncMock(return_value=str(tmp_path))
        git.get_diff = AsyncMock(return_value="+++ b/app/api/users.py\n+x = 1\n")
        git.get_changed_files = AsyncMock(return_value=["app/api/users.py"])
        git.get_commit_message = AsyncMock(return_value="Add user lookup")
        git.cleanup_repo = MagicMock()
        self.orch.git_service = git
        self.orch._start_monitoring = MagicMock()
        self.gh = MagicMock()
        self.gh.safe_commit_status = AsyncMock()
        self.gh.close = AsyncMock()


async def status_of(db_session, run) -> PipelineRun:
    await db_session.refresh(run)
    return run


async def run_pipeline(harness: Harness, run, **kwargs: Any) -> dict[str, MagicMock]:
    with (
        patch("app.agents.orchestrator.FullScanOrchestrator") as fs,
        patch("app.agents.orchestrator.StressTestAgent") as st,
        patch("app.agents.orchestrator.ApprovalAgent") as ap,
        patch("app.agents.orchestrator.DeploymentAgent") as dp,
        patch("app.agents.orchestrator.GitHubService", return_value=harness.gh),
    ):
        fs.return_value.execute = AsyncMock(return_value=kwargs.get("combined", CLEAN))
        st.return_value.execute = AsyncMock(return_value=kwargs.get("stress") or {"performance_verdict": "pass"})
        ap.return_value.execute = AsyncMock(return_value=kwargs.get("approval") or {"decision": "approved"})
        dp.return_value.execute = AsyncMock(return_value=kwargs.get("deployment") or {"success": True})
        dp.return_value.execute_simulated = AsyncMock(
            return_value=kwargs.get("simulated_deployment") or {"success": True, "simulated": True}
        )
        await harness.orch.execute_pipeline(str(run.id))
        return {"full_scan": fs, "stress": st, "approval": ap, "deploy": dp}


@pytest.fixture
def harness(tmp_path, session_factory) -> Harness:
    return Harness(tmp_path)


async def test_happy_path_deploys_and_starts_monitoring(harness, pipeline_run, db_session):
    agents = await run_pipeline(harness, pipeline_run)
    run = await status_of(db_session, pipeline_run)

    assert run.status == "deployed"
    assert run.completed_at is not None
    types = set((await db_session.execute(select(PipelineArtifact.artifact_type))).scalars())
    assert {"metadata", "diff"} <= types
    agents["deploy"].return_value.execute.assert_awaited_once()
    harness.orch._start_monitoring.assert_called_once_with(run.id)
    assert harness.gh.safe_commit_status.await_args_list[-1].args[2] == "success"
    harness.orch.git_service.cleanup_repo.assert_called_once_with(run.id)


async def test_security_block_without_github_token(harness, pipeline_run, db_session):
    combined = {**CLEAN, "security_issues": {"highest_severity": "critical", "vulnerabilities": [{"file": "a.py", "severity": "critical"}]}}
    agents = await run_pipeline(harness, pipeline_run, combined=combined)
    run = await status_of(db_session, pipeline_run)

    assert run.status == "blocked_security"
    assert "security severity critical" in run.error_message
    agents["stress"].return_value.execute.assert_not_called()
    assert harness.gh.safe_commit_status.await_args_list[-1].args[2] == "failure"
    harness.orch.slack_service.send_pipeline_blocked.assert_awaited_once()


async def test_block_with_fix_prs_sent(harness, pipeline_run, db_session):
    bundle = IssueBundle("security", [{}], [{"file_path": "a.py"}], "orion/fix-security-x", "t", "", pr_number=7,
                         pr_url="https://github.com/o/r/pull/7")
    harness.orch._open_fix_prs = AsyncMock(return_value=[bundle])
    await run_pipeline(harness, pipeline_run, combined={**CLEAN, "code_issues": {"severity": "fail"}})
    run = await status_of(db_session, pipeline_run)

    assert run.status == "blocked_with_prs_sent"
    assert "https://github.com/o/r/pull/7" in run.error_message
    kwargs = harness.orch.slack_service.send_pipeline_blocked.await_args.kwargs
    assert kwargs["pr_urls"] == ["https://github.com/o/r/pull/7"]


@pytest.mark.parametrize(
    ("kwargs", "expected_status"),
    [
        ({"stress": {"performance_verdict": "fail", "summary": "p95 too high"}}, "blocked_stress"),
        ({"approval": {"decision": "rejected", "reason": "risky"}}, "rejected"),
        ({"deployment": {"success": False, "rollback": {"rolled_back": True}}}, "rolled_back"),
        ({"deployment": {"success": False, "error": "docker build failed"}}, "failed"),
    ],
)
async def test_later_stage_outcomes(harness, pipeline_run, db_session, kwargs, expected_status):
    await run_pipeline(harness, pipeline_run, **kwargs)
    run = await status_of(db_session, pipeline_run)
    assert run.status == expected_status
    harness.orch._start_monitoring.assert_not_called()


async def test_warnings_are_recorded_but_do_not_block(harness, pipeline_run, db_session):
    await run_pipeline(harness, pipeline_run, stress={"performance_verdict": "warn", "skipped": True})
    run = await status_of(db_session, pipeline_run)
    assert run.status == "deployed"
    assert run.has_warnings is True


async def test_unexpected_exception_marks_run_failed(harness, pipeline_run, db_session):
    harness.orch.git_service.clone_repo = AsyncMock(side_effect=RuntimeError("git clone failed: auth"))
    await run_pipeline(harness, pipeline_run)
    run = await status_of(db_session, pipeline_run)
    assert run.status == "failed"
    assert "Stage ingesting failed: git clone failed: auth" in run.error_message
    assert harness.gh.safe_commit_status.await_args_list[-1].args[2] == "error"
    harness.orch.git_service.cleanup_repo.assert_called_once()


async def test_missing_run_raises(harness, session_factory):
    import uuid

    with pytest.raises(ValueError):
        await harness.orch.execute_pipeline(str(uuid.uuid4()))

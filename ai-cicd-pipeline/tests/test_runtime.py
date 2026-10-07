"""Redis-free / Docker-free runtime: trigger endpoint, inline dispatcher, cancellation, deploy-skip."""

import asyncio
import os
import stat
import subprocess
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.agents import deployment_agent
from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.events import channel_for, event_bus
from app.tasks import dispatch

TRIGGER = "/api/v1/pipeline/trigger"


def _git(cwd, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", check=True,
    )
    return p.stdout.strip()


@pytest.fixture
def local_repo(tmp_path):
    repo = tmp_path / "sample-service"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


async def test_trigger_local_repo(async_client, db_session, local_repo):
    with patch("app.api.routes.pipeline.dispatch_pipeline", return_value="inline") as d:
        r = await async_client.post(TRIGGER, json={"clone_url": str(local_repo), "branch": "main"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["commit_id"] == _git(local_repo, "rev-parse", "HEAD")
    assert body["repo_full_name"] == "local/sample-service"
    assert body["executor"] == "inline"
    d.assert_called_once()
    run = await db_session.get(PipelineRun, uuid.UUID(body["pipeline_run_id"]))
    assert run.status == "queued"
    assert run.short_commit_id == body["commit_id"][:8]


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"clone_url": "--upload-pack=evil", "branch": "main"}, "Invalid"),
        ({"clone_url": "https://github.com/a/b.git", "branch": "-x"}, "Invalid"),
        ({"clone_url": "https://github.com/a/b.git", "branch": "a..b"}, "Invalid"),
        ({"clone_url": "Z:/definitely/not/here", "branch": "main"}, "git repository"),
    ],
)
async def test_trigger_rejects_bad_input(async_client, payload, detail):
    with patch("app.api.routes.pipeline.dispatch_pipeline") as d:
        r = await async_client.post(TRIGGER, json=payload)
    assert r.status_code == 400
    assert detail in r.json()["detail"]
    d.assert_not_called()


async def test_trigger_unknown_branch(async_client, local_repo):
    with patch("app.api.routes.pipeline.dispatch_pipeline") as d:
        r = await async_client.post(TRIGGER, json={"clone_url": str(local_repo), "branch": "nope"})
    assert r.status_code == 400
    d.assert_not_called()


async def test_trigger_local_path_blocked_in_production(async_client, local_repo, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    r = await async_client.post(TRIGGER, json={"clone_url": str(local_repo)})
    assert r.status_code == 400
    assert "production" in r.json()["detail"]


def test_executor_mode(monkeypatch):
    monkeypatch.setattr(settings, "pipeline_executor", "auto")
    with patch("app.tasks.dispatch.redis_available", return_value=False):
        assert dispatch.executor_mode() == "inline"
    with patch("app.tasks.dispatch.redis_available", return_value=True):
        assert dispatch.executor_mode() == "celery"
    monkeypatch.setattr(settings, "pipeline_executor", "inline")
    with patch("app.tasks.dispatch.redis_available", return_value=True):
        assert dispatch.executor_mode() == "inline"


def test_dispatch_celery(monkeypatch):
    monkeypatch.setattr(settings, "pipeline_executor", "celery")
    with patch("app.tasks.pipeline_tasks.run_pipeline_task") as task:
        assert dispatch.dispatch_pipeline("abc", github_token="t") == "celery"
    task.delay.assert_called_once_with("abc", github_token="t", resume=False)


async def test_inline_dispatch_runs_and_cancel_stops_it(async_client, db_session, pipeline_run, session_factory):
    started = asyncio.Event()

    async def forever(run_id, github_token=None, **kwargs):
        started.set()
        await asyncio.sleep(3600)

    with patch("app.agents.orchestrator.orchestrator.execute_pipeline", side_effect=forever):
        assert dispatch.dispatch_pipeline(pipeline_run.id) == "inline"
        await asyncio.wait_for(started.wait(), 5)
        task = next(t for t in dispatch.inline_tasks() if t.get_name() == f"pipeline-{pipeline_run.id}")

        queue, _ = event_bus.subscribe(channel_for(pipeline_run.id))
        try:
            r = await async_client.post(f"/api/v1/pipeline/runs/{pipeline_run.id}/cancel")
            assert r.json()["cancelled"] is True
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            event = await asyncio.wait_for(queue.get(), 2)
            assert '"cancelled"' in event
        finally:
            event_bus.unsubscribe(channel_for(pipeline_run.id), queue)

    await db_session.refresh(pipeline_run)
    assert pipeline_run.status == "cancelled"
    assert pipeline_run.completed_at is not None


async def test_inline_crash_marks_run_failed(db_session, pipeline_run, session_factory):
    with patch("app.agents.orchestrator.orchestrator.execute_pipeline", AsyncMock(side_effect=RuntimeError("boom"))):
        dispatch.dispatch_pipeline(pipeline_run.id)
        task = next(t for t in dispatch.inline_tasks() if t.get_name() == f"pipeline-{pipeline_run.id}")
        await asyncio.wait_for(task, 5)
    await db_session.refresh(pipeline_run)
    assert pipeline_run.status == "failed"
    assert "boom" in pipeline_run.error_message


async def test_recover_interrupted_runs(db_session, pipeline_run, session_factory):
    def mk(status):
        return PipelineRun(
            commit_id="e" * 40, short_commit_id="eeeeeee", branch="main", repo_full_name="o/r",
            clone_url="https://github.com/o/r.git", pusher="p", status=status,
        )

    running, monitoring, done = mk("running_qa"), mk("monitoring"), mk("deployed")
    db_session.add_all([running, monitoring, done])
    await db_session.commit()

    requeue = await dispatch.recover_interrupted_runs()
    assert requeue == [str(pipeline_run.id)]
    for row in (running, monitoring, done):
        await db_session.refresh(row)
    assert running.status == "failed" and "restarted" in running.error_message
    assert monitoring.status == "deployed"
    assert done.status == "deployed"


def test_resolved_deploy_mode(monkeypatch):
    monkeypatch.setattr(settings, "deploy_mode", "skip")
    assert deployment_agent.resolved_deploy_mode() == "skip"
    monkeypatch.setattr(settings, "deploy_mode", "simulate")
    assert deployment_agent.resolved_deploy_mode() == "simulate"
    monkeypatch.setattr(settings, "deploy_mode", "auto")
    with patch.object(deployment_agent, "docker_available", return_value=False):
        assert deployment_agent.resolved_deploy_mode() == "simulate"
    with patch.object(deployment_agent, "docker_available", return_value=True):
        assert deployment_agent.resolved_deploy_mode() == "docker"


async def test_pipeline_without_docker_simulates_deploy(tmp_path, session_factory, db_session, pipeline_run, monkeypatch):
    from tests.test_orchestrator import Harness, run_pipeline

    monkeypatch.setattr(settings, "deploy_mode", "auto")
    with patch.object(deployment_agent, "docker_available", return_value=False):
        harness = Harness(tmp_path)
        agents = await run_pipeline(harness, pipeline_run)

    await db_session.refresh(pipeline_run)
    assert pipeline_run.status == "deployed"
    assert pipeline_run.completed_at is not None
    agents["deploy"].return_value.execute.assert_not_awaited()
    agents["deploy"].return_value.execute_simulated.assert_awaited_once()
    harness.orch._start_monitoring.assert_called_once()
    deployment = agents["deploy"].return_value.execute_simulated.return_value
    assert deployment["simulated"] is True
    assert deployment["success"] is True
    assert harness.gh.safe_commit_status.await_args_list[-1].args[2] == "success"
    harness.orch.git_service.cleanup_repo.assert_called_once_with(pipeline_run.id)


async def test_pipeline_deploy_skip_still_ends_approved(tmp_path, session_factory, db_session, pipeline_run, monkeypatch):
    from tests.test_orchestrator import Harness, run_pipeline

    monkeypatch.setattr(settings, "deploy_mode", "skip")
    harness = Harness(tmp_path)
    agents = await run_pipeline(harness, pipeline_run)

    await db_session.refresh(pipeline_run)
    assert pipeline_run.status == "approved"
    agents["deploy"].return_value.execute.assert_not_awaited()
    agents["deploy"].return_value.execute_simulated.assert_not_awaited()
    harness.orch._start_monitoring.assert_not_called()


def test_force_rmtree_removes_readonly_files(tmp_path):
    from app.services.git_service import force_rmtree

    target = tmp_path / "repo" / ".git" / "objects"
    target.mkdir(parents=True)
    f = target / "pack"
    f.write_text("x")
    os.chmod(f, stat.S_IREAD)
    force_rmtree(tmp_path / "repo")
    assert not (tmp_path / "repo").exists()


async def test_diff_with_non_ascii_content(local_repo):
    from app.services.git_service import GitService

    # "Ï" encodes to C3 8F; 0x8F is undefined in cp1252, the Windows default decoder.
    (local_repo / "notes.md").write_text("Café Ï — déployé 🚀\n", encoding="utf-8")
    _git(local_repo, "add", ".")
    _git(local_repo, "commit", "-m", "docs: ünïcode ✓")
    git = GitService()

    diff = await git.get_diff(str(local_repo))
    assert "Café Ï — déployé 🚀" in diff
    assert await git.get_changed_files(str(local_repo)) == ["notes.md"]
    assert await git.get_commit_message(str(local_repo)) == "docs: ünïcode ✓"


def test_repo_env_exposes_flat_and_src_layouts(tmp_path, monkeypatch):
    from app.utils.tools import repo_env

    monkeypatch.setenv("PYTHONPATH", "existing")
    (tmp_path / "src").mkdir()
    parts = repo_env(str(tmp_path))["PYTHONPATH"].split(os.pathsep)
    assert parts == [str(tmp_path.resolve()), str((tmp_path / "src").resolve()), "existing"]


def test_stress_prefers_repo_locustfile(tmp_path):
    from app.agents.stress_test_agent import StressTestAgent

    agent = StressTestAgent.__new__(StressTestAgent)
    agent.repo_path = str(tmp_path)
    assert agent._repo_locustfile() is None
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "locustfile.py").write_text("")
    assert agent._repo_locustfile() == (tmp_path / "tests" / "locustfile.py").resolve()


async def test_rejected_api_key_pauses_llm_calls(monkeypatch):
    import anthropic
    import httpx

    from app.agents import base_agent
    from app.agents.code_analysis_agent import CodeAnalysisAgent

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-api03-" + "x" * 40)
    monkeypatch.setattr(base_agent, "_llm_state", dict(base_agent._llm_state, status="unverified", retry_after=0.0))
    client = anthropic.AsyncAnthropic(api_key="sk-ant-api03-" + "x" * 40)
    denied = anthropic.AuthenticationError(
        "invalid x-api-key",
        response=httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
        body=None,
    )
    create = AsyncMock(side_effect=denied)
    monkeypatch.setattr(client.messages, "create", create)
    agent = CodeAnalysisAgent(uuid.uuid4(), None, client, ".", "")

    first = await agent._call_claude_json("sys", "msg")
    second = await agent._call_claude_json("sys", "msg")

    assert base_agent.LLM_ERROR_KEY in first and base_agent.LLM_ERROR_KEY in second
    assert create.await_count == 1
    assert base_agent.llm_status()["status"] == "auth_failed"
    assert "paused" in second[base_agent.LLM_ERROR_KEY]


def test_cleanup_tolerates_missing_dir(tmp_path):
    from app.services.git_service import force_rmtree

    force_rmtree(tmp_path / "missing")
    assert not (tmp_path / "missing").exists()

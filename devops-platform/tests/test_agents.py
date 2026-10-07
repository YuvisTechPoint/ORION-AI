"""Agent unit tests — security hard gate must block on critical findings."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.agents.base_agent import AgentInput
from app.agents.security import SecurityAgent
from app.config import get_settings
from app.database import Base
from app.models import PipelineRun, PipelineStatus


@pytest.fixture
def db_session() -> Session:
    settings = get_settings()
    eng = create_engine(settings.sync_database_url)
    Base.metadata.create_all(bind=eng)
    SessionLocal = sessionmaker(bind=eng)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def test_security_agent_hard_gate_critical_forces_failed(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """If LLM reports a critical vulnerability, passed must be False (orchestrator must not proceed)."""

    pid = uuid4()
    db_session.add(
        PipelineRun(
            id=pid,
            repo_url="https://github.com/o/r",
            commit_sha="",
            status=PipelineStatus.DEV,
            metadata_json={},
        )
    )
    db_session.commit()

    agent = SecurityAgent(db_session)

    def fake_llm(_prompt: str, schema):
        return {
            "vulnerabilities": [
                {
                    "id": "CVE-TEST",
                    "title": "RCE",
                    "severity": "critical",
                    "cve": "CVE-TEST",
                    "description": "test",
                    "affected_code": "x",
                }
            ],
            "overall_risk": "low",
            "passed": True,
        }

    monkeypatch.setattr(agent, "_call_llm", fake_llm)

    out = agent.run(
        AgentInput(
            pipeline_id=pid,
            stage_name="DEV",
            context={"code_snapshot": {"files": [{"path": "a.py", "content": "print(1)"}]}},
        )
    )
    assert out.passed is False


def test_security_agent_passes_when_clean(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = uuid4()
    db_session.add(
        PipelineRun(
            id=pid,
            repo_url="https://github.com/o/r",
            commit_sha="",
            status=PipelineStatus.DEV,
            metadata_json={},
        )
    )
    db_session.commit()

    agent = SecurityAgent(db_session)

    def fake_llm(_prompt: str, schema):
        return {
            "vulnerabilities": [],
            "overall_risk": "low",
            "passed": True,
        }

    monkeypatch.setattr(agent, "_call_llm", fake_llm)

    out = agent.run(
        AgentInput(
            pipeline_id=pid,
            stage_name="DEV",
            context={"code_snapshot": {"files": []}},
        )
    )
    assert out.passed is True


def test_qa_skips_without_tests_dir(db_session: Session, tmp_path) -> None:
    from app.agents.qa_agent import QAAgent

    pid = uuid4()
    db_session.add(
        PipelineRun(
            id=pid,
            repo_url="https://github.com/o/r",
            commit_sha="",
            status=PipelineStatus.QA,
            metadata_json={},
        )
    )
    db_session.commit()
    agent = QAAgent(db_session)
    out = agent.run(AgentInput(pipeline_id=pid, stage_name="QA", context={"temp_dir": str(tmp_path)}))
    assert out.passed is True
    assert "skipped" in out.summary.lower()


def test_deployment_builds_from_temp_dir(db_session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agents.deployment import DeploymentAgent
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DEPLOY_MODE", "docker")
    monkeypatch.setattr("app.agents.deployment.resolved_deploy_mode", lambda: "docker")

    pid = uuid4()
    captured: dict[str, str] = {}

    def fake_run(cmd, cwd=None, capture_output=True, timeout=120, check=False, **kwargs):
        if cmd and cmd[0] == "docker" and "build" in cmd:
            captured["cwd"] = str(cwd)
            captured["cmd"] = " ".join(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr("app.agents.deployment.subprocess.run", fake_run)
    db_session.add(
        PipelineRun(
            id=pid,
            repo_url="https://github.com/o/r",
            commit_sha="abcdef12",
            status=PipelineStatus.DEPLOYMENT,
            metadata_json={"repo_url": "https://github.com/o/r", "commit_sha": "abcdef12"},
        )
    )
    db_session.commit()
    agent = DeploymentAgent(db_session)
    agent.run(
        AgentInput(
            pipeline_id=pid,
            stage_name="DEPLOYMENT",
            context={"temp_dir": str(tmp_path), "metadata_json": {"repo_url": "https://github.com/o/r", "commit_sha": "abcdef12"}},
        )
    )
    assert captured["cwd"] == str(tmp_path)


def test_deployment_simulated_without_docker(db_session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agents.deployment import DeploymentAgent
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DEPLOY_MODE", "simulate")
    docker_calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, capture_output=True, timeout=120, check=False, **kwargs):
        docker_calls.append(list(cmd))
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr("app.agents.deployment.subprocess.run", fake_run)

    pid = uuid4()
    db_session.add(
        PipelineRun(
            id=pid,
            repo_url="https://github.com/o/r",
            commit_sha="abcdef12",
            status=PipelineStatus.DEPLOYMENT,
            metadata_json={"repo_url": "https://github.com/o/r", "commit_sha": "abcdef12"},
        )
    )
    db_session.commit()
    agent = DeploymentAgent(db_session)
    out = agent.run(
        AgentInput(
            pipeline_id=pid,
            stage_name="DEPLOYMENT",
            context={"temp_dir": str(tmp_path), "metadata_json": {"repo_url": "https://github.com/o/r", "commit_sha": "abcdef12"}},
        )
    )
    assert out.passed is True
    assert out.artifacts["deployment"]["simulated"] is True
    assert not any(cmd and cmd[0] == "docker" for cmd in docker_calls)


def test_deployment_skip_mode(db_session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agents.deployment import DeploymentAgent
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DEPLOY_MODE", "skip")

    pid = uuid4()
    db_session.add(
        PipelineRun(
            id=pid,
            repo_url="https://github.com/o/r",
            commit_sha="abcdef12",
            status=PipelineStatus.DEPLOYMENT,
            metadata_json={"repo_url": "https://github.com/o/r", "commit_sha": "abcdef12"},
        )
    )
    db_session.commit()
    agent = DeploymentAgent(db_session)
    out = agent.run(
        AgentInput(
            pipeline_id=pid,
            stage_name="DEPLOYMENT",
            context={"temp_dir": str(tmp_path), "metadata_json": {"repo_url": "https://github.com/o/r", "commit_sha": "abcdef12"}},
        )
    )
    assert out.passed is True
    assert out.artifacts["deployment"]["skipped"] is True

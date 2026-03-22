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

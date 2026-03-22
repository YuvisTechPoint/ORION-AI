"""Orchestrator behavior: security failure must set BLOCKED and not continue to QA."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.config import get_settings
from app.database import Base
from app.models import PipelineRun, PipelineStatus
from app.orchestrator import pipeline_runner as pr


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


def test_run_pipeline_stops_after_security_gate(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = uuid4()
    p = PipelineRun(
        id=pid,
        repo_url="https://github.com/octocat/hello-world",
        commit_sha="",
        status=PipelineStatus.PENDING,
        metadata_json={"repo_url": "https://github.com/octocat/hello-world"},
    )
    db_session.add(p)
    db_session.commit()

    monkeypatch.setattr(pr, "fetch_zipball_to_temp", lambda url, td: ("abc123", td))
    monkeypatch.setattr(pr, "fetch_repo_snapshot", lambda url: {"files": [], "repo": "x/y", "default_branch": "main"})

    class FakeCA:
        def __init__(self, db):
            self.db = db

        def run(self, inp):
            from app.agents.base_agent import AgentOutput

            return AgentOutput(passed=True, summary="ok", artifacts={"code_analysis": {}}, next_context={})

    class FakeSec:
        def __init__(self, db):
            self.db = db

        def run(self, inp):
            from app.agents.base_agent import AgentOutput

            return AgentOutput(passed=False, summary="blocked", artifacts={"security": {}}, next_context={})

    monkeypatch.setattr(pr, "CodeAnalysisAgent", FakeCA)
    monkeypatch.setattr(pr, "SecurityAgent", FakeSec)

    qa_called = {"n": 0}

    class FakeQA:
        def __init__(self, db):
            self.db = db

        def run(self, inp):
            qa_called["n"] += 1
            from app.agents.base_agent import AgentOutput

            return AgentOutput(passed=True, summary="qa", artifacts={}, next_context={})

    monkeypatch.setattr(pr, "QAAgent", FakeQA)

    pr._run_pipeline_impl(str(pid))

    db_session.expire_all()
    row = db_session.query(PipelineRun).filter(PipelineRun.id == pid).first()
    assert row is not None
    assert row.status == PipelineStatus.BLOCKED
    assert qa_called["n"] == 0

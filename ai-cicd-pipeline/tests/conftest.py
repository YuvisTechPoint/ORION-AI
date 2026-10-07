import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Tests must never reach real Anthropic/GitHub/Slack/Postgres, whatever a developer's .env contains.
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "SYNC_DATABASE_URL": "sqlite:///:memory:",
        "ANTHROPIC_API_KEY": "sk-ant-api03-your-key-here",
        "GITHUB_TOKEN": "ghp_your-personal-access-token",
        "GITHUB_WEBHOOK_SECRET": "test-webhook-secret",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/xxx/yyy/zzz",
        "API_REQUIRE_AUTH": "false",
        "JOURNALD_ENABLED": "false",
        "REDIS_URL": "redis://127.0.0.1:1/0",
        "PIPELINE_EXECUTOR": "inline",
        "DEPLOY_MODE": "docker",
        "PIPELINE_WORKDIR": str(Path(__file__).parent / ".work"),
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.pipeline_artifact import PipelineArtifact  # noqa: E402,F401
from app.models.pipeline_run import PipelineRun  # noqa: E402
from app.models.performance_baseline import PerformanceBaseline  # noqa: E402, F401

FIXTURES = Path(__file__).parent / "fixtures"
SESSION_FACTORY_TARGETS = (
    "app.database.AsyncSessionLocal",
    "app.api.routes.webhook.AsyncSessionLocal",
    "app.agents.orchestrator.AsyncSessionLocal",
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop() -> None:
        return None

    monkeypatch.setattr("app.main.init_db", noop)
    monkeypatch.setattr("app.agents.orchestrator.emit_ws", lambda *a, **k: None)


@pytest_asyncio.fixture
async def test_db_engine() -> AsyncIterator[Any]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(test_db_engine: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    factory = async_sessionmaker(test_db_engine, class_=AsyncSession, expire_on_commit=False)
    for target in SESSION_FACTORY_TARGETS:
        monkeypatch.setattr(target, factory)

    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    yield factory
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_session(session_factory: Any) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(session_factory: Any) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def pipeline_run(db_session: AsyncSession) -> PipelineRun:
    run = PipelineRun(
        commit_id="abc123def456abc123def456abc123def456abc1",
        short_commit_id="abc123de",
        branch="main",
        pusher="testuser",
        repo_full_name="testuser/testrepo",
        clone_url="https://github.com/testuser/testrepo.git",
        status="queued",
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


def make_claude_response(payload: dict[str, Any] | str, input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return MagicMock(content=[MagicMock(text=text)], usage=MagicMock(input_tokens=input_tokens, output_tokens=output_tokens))


@pytest.fixture
def mock_anthropic_client() -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=make_claude_response({"severity": "pass", "issues": [], "summary": "ok"})
    )
    return client


@pytest.fixture
def sample_github_payload() -> dict[str, Any]:
    commit = "abc123def456abc123def456abc123def456abc1"
    return {
        "ref": "refs/heads/main",
        "before": "0123456789012345678901234567890123456789",
        "after": commit,
        "repository": {
            "id": 1,
            "full_name": "testuser/testrepo",
            "clone_url": "https://github.com/testuser/testrepo.git",
            "default_branch": "main",
        },
        "pusher": {"name": "testuser", "email": "test@example.com"},
        "head_commit": {"id": commit, "message": "Add user lookup"},
        "commits": [{"id": commit, "message": "Add user lookup", "added": [], "modified": ["app/api/users.py"], "removed": []}],
    }


@pytest.fixture
def sample_diff_text() -> str:
    return (FIXTURES / "sample_diff.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_pytest_report() -> dict[str, Any]:
    return json.loads((FIXTURES / "sample_pytest_report.json").read_text(encoding="utf-8"))

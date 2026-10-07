"""Test configuration: SQLite DB + schema before importing the app."""

from __future__ import annotations

import os
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_db_path = _root / ".pytest_devops.db"
if _db_path.exists():
    try:
        _db_path.unlink()
    except OSError:
        pass

# Force isolated test env — parent shell may inherit production flags from run_all_stacks.ps1
os.environ["APP_ENV"] = "development"
os.environ["API_REQUIRE_AUTH"] = "false"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_path.as_posix()}"
os.environ["SYNC_DATABASE_URL"] = f"sqlite:///{_db_path.as_posix()}"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["DEPLOYMENT_API_KEY"] = "devops-approver-key"
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")


def _create_schema() -> None:
    from sqlalchemy import create_engine

    import app.models  # noqa: F401
    from app.config import get_settings
    from app.database import Base

    get_settings.cache_clear()
    eng = create_engine(get_settings().sync_database_url)
    Base.metadata.create_all(bind=eng)
    eng.dispose()


_create_schema()


import pytest


@pytest.fixture(autouse=True)
def _refresh_settings_cache() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

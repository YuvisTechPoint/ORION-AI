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

os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_db_path.as_posix()}")
os.environ.setdefault("SYNC_DATABASE_URL", f"sqlite:///{_db_path.as_posix()}")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("DEPLOYMENT_API_KEY", "devops-approver-key")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")


def _create_schema() -> None:
    from sqlalchemy import create_engine

    import app.models  # noqa: F401
    from app.config import get_settings
    from app.database import Base

    eng = create_engine(get_settings().sync_database_url)
    Base.metadata.create_all(bind=eng)
    eng.dispose()


_create_schema()

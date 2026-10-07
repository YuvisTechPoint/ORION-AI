from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Generator

from core.config import Settings, get_settings


def resolve_sync_database_url(database_url: str, sync_database_url: str = "") -> str:
    """Canonical backend uses sync SQLAlchemy; prefer SYNC_DATABASE_URL when async URL is set."""
    sync = (sync_database_url or "").strip()
    if sync:
        return sync
    url = (database_url or "").strip()
    if "+aiosqlite" in url:
        return url.replace("sqlite+aiosqlite", "sqlite", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def build_sync_engine(settings: Settings | None = None):
    cfg = settings or get_settings()
    return create_engine(resolve_sync_database_url(cfg.database_url, cfg.sync_database_url), future=True)


settings = get_settings()

engine = build_sync_engine(settings)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

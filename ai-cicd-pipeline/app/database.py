"""Async SQLAlchemy engine/session setup.

Alembic owns schema migrations in production (`alembic upgrade head`); `init_db()` exists for
local development and tests where creating tables directly from metadata is convenient.
"""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings


def _engine_kwargs(url: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
        "echo": settings.app_env == "development" and settings.sql_echo,
    }
    if not url.startswith("sqlite"):
        kwargs.update(pool_size=10, max_overflow=20)
    return kwargs


async_engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    from app.models import pipeline_artifact  # noqa: F401
    from app.models import pipeline_run  # noqa: F401
    from app.models import webhook_delivery  # noqa: F401

    async with async_engine.begin() as conn:
        if conn.engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.run_sync(Base.metadata.create_all)

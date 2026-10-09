"""Memory store factory — sqlite (Wave 1) or postgres+pgvector (Wave 4)."""

from __future__ import annotations

from shared.memory_gateway.config import MemoryGatewayConfig
from shared.memory_gateway.pg_store import MemoryPgStore
from shared.memory_gateway.store import MemorySqliteStore


def normalize_sync_dsn(url: str) -> str:
    raw = (url or "").strip()
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgres+asyncpg://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix) :]
    return raw


def resolve_postgres_dsn(config: MemoryGatewayConfig, fallback_database_url: str | None = None) -> str | None:
    explicit = (config.postgres_url or "").strip()
    if explicit:
        return normalize_sync_dsn(explicit)
    fallback = (fallback_database_url or "").strip()
    if fallback and "postgres" in fallback.lower():
        return normalize_sync_dsn(fallback)
    return None


def build_memory_store(config: MemoryGatewayConfig, fallback_database_url: str | None = None):
    backend = (config.backend or "sqlite").strip().lower()
    if backend in {"postgres", "postgresql", "pg"}:
        dsn = resolve_postgres_dsn(config, fallback_database_url)
        if not dsn:
            raise ValueError(
                "MEMORY_BACKEND=postgres requires MEMORY_POSTGRES_URL or a PostgreSQL DATABASE_URL/SYNC_DATABASE_URL"
            )
        return MemoryPgStore(dsn, embedding_dims=config.embedding_dims)
    return MemorySqliteStore(config.sqlite_path)

"""Memory store factory."""

from __future__ import annotations

import pytest

from shared.memory_gateway.config import MemoryGatewayConfig
from shared.memory_gateway.factory import build_memory_store, normalize_sync_dsn
from shared.memory_gateway.store import MemorySqliteStore


def test_normalize_sync_dsn_asyncpg():
    url = "postgresql+asyncpg://user:pass@localhost:5432/orion"
    assert normalize_sync_dsn(url) == "postgresql://user:pass@localhost:5432/orion"


def test_build_sqlite_store(tmp_path):
    cfg = MemoryGatewayConfig(sqlite_path=str(tmp_path / "m.db"), backend="sqlite")
    store = build_memory_store(cfg)
    assert isinstance(store, MemorySqliteStore)


def test_build_postgres_requires_dsn():
    cfg = MemoryGatewayConfig(backend="postgres")
    with pytest.raises(ValueError, match="MEMORY_BACKEND=postgres"):
        build_memory_store(cfg)

"""Memory Gateway v2 API smoke tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_memory_health(async_client, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "api-memory.db"))
    from app.services.memory_gateway_service import get_memory_gateway

    get_memory_gateway.cache_clear()

    resp = await async_client.get("/api/v2/memory/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert data["backend"] == "sqlite"


@pytest.mark.asyncio
async def test_memory_write_and_context(async_client, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "api-memory.db"))
    from app.services.memory_gateway_service import get_memory_gateway

    get_memory_gateway.cache_clear()

    write = await async_client.post(
        "/api/v2/memory/records",
        json={
            "tenant_id": "testorg",
            "namespace": "testorg/platform/demo/demo/l2/episodic/manual",
            "title": "Operator note",
            "body": "Staging stress gate failed twice last week.",
        },
    )
    assert write.status_code == 200
    body = write.json()
    assert body.get("written") is True or body.get("deduplicated") is True

    ctx = await async_client.post(
        "/api/v2/memory/context",
        json={"tenant_id": "testorg", "repo_full_name": "testorg/demo"},
    )
    assert ctx.status_code == 200
    assert ctx.json().get("advisory_only") is True

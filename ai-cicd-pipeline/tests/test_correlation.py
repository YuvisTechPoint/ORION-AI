"""Correlation ID middleware and helpers."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.utils.correlation import CORRELATION_HEADER, TRACE_HEADER, resolve_correlation_id


def test_resolve_correlation_id_generates_when_missing():
    cid = resolve_correlation_id(None)
    assert len(cid) == 32


@pytest.mark.asyncio
async def test_correlation_headers_on_health():
    transport = ASGITransport(app=app)
    cid = "a" * 32
    tid = "b" * 32
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/health",
            headers={CORRELATION_HEADER: cid, TRACE_HEADER: tid},
        )
    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_HEADER) == cid
    assert resp.headers.get(TRACE_HEADER) == tid

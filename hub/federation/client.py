"""HTTP client with correlation header propagation."""

from __future__ import annotations

from typing import Any

import httpx

CORRELATION_HEADER = "X-Correlation-ID"
TRACE_HEADER = "X-Trace-ID"


def correlation_headers(correlation_id: str | None, trace_id: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if correlation_id:
        headers[CORRELATION_HEADER] = correlation_id
    if trace_id:
        headers[TRACE_HEADER] = trace_id
    return headers


async def post_json(
    url: str,
    *,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=correlation_headers(correlation_id, trace_id))
    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return resp.status_code, body


async def fetch_json(
    url: str,
    *,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    timeout: float = 15.0,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                url,
                params=params,
                headers=correlation_headers(correlation_id, trace_id),
            )
    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return resp.status_code, body

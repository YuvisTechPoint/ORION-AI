"""Optional API-key auth (ORION parity) for pipeline and tool endpoints."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import HTTPException, Request, WebSocket, status

from app.config import get_settings

_API_KEY_HEADERS = ("x-orion-api-key", "x-api-key", "x-deployment-key")


def expected_api_key() -> str:
    settings = get_settings()
    explicit = (getattr(settings, "orion_api_key", "") or "").strip()
    if explicit:
        return explicit
    return (settings.deployment_api_key or "").strip()


def api_key_from_request(request: Request) -> str | None:
    for header in _API_KEY_HEADERS:
        value = request.headers.get(header)
        if value:
            return value.strip()
    return None


def validate_api_key(provided: str | None) -> bool:
    expected = expected_api_key()
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


async def optional_auth(request: Request) -> dict[str, Any]:
    settings = get_settings()
    if settings.api_require_auth and not validate_api_key(api_key_from_request(request)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if validate_api_key(api_key_from_request(request)):
        return {"username": "api-key", "api_key_auth": True}
    return {"username": "anonymous", "dev_anonymous": True}


async def ws_require_auth(websocket: WebSocket) -> bool:
    settings = get_settings()
    if not settings.api_require_auth:
        return True
    query = websocket.query_params
    token = query.get("api_key") or query.get("token")
    return validate_api_key(token)

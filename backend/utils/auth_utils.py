from __future__ import annotations

from typing import Optional

import httpx
from fastapi import Request

from core.config import get_settings

settings = get_settings()


def get_token_from_session(request: Request) -> Optional[str]:
    """Safely read the GitHub token from the session, if present."""
    if not hasattr(request, "session"):
        return None
    token = request.session.get("github_token")
    if isinstance(token, str) and token.strip():
        return token.strip()
    return None


def get_effective_github_token(session_token: Optional[str] = None) -> str:
    """Return a usable GitHub token, preferring the session token and falling back to env settings."""
    if isinstance(session_token, str) and session_token.strip():
        return session_token.strip()

    env_token = (settings.github_token or "").strip()
    if env_token:
        return env_token

    raise ValueError(
        "No GitHub token available — please login with GitHub at /api/v1/auth/github or set GITHUB_TOKEN in .env"
    )


async def validate_github_token(token: str) -> dict:
    """Validate the token by fetching the user profile from GitHub."""
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get("https://api.github.com/user", headers=headers)
    if resp.status_code != 200:
        raise ValueError("GitHub token is invalid or expired")
    return resp.json()


def get_token_scopes(token: str) -> list[str]:
    """Return scopes parsed from the GitHub API root response header."""
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        resp = httpx.get("https://api.github.com/", headers=headers, timeout=10.0)
    except httpx.RequestError:
        return []

    raw_scopes = resp.headers.get("X-OAuth-Scopes", "")
    return [scope.strip() for scope in raw_scopes.split(",") if scope.strip()]

import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])

_PLACEHOLDER_MARKERS = (
    "your-oauth-app-client-id",
    "your-oauth-app-client-secret",
)


def _github_oauth_configured() -> bool:
    cid = (settings.github_client_id or "").strip()
    csec = (settings.github_client_secret or "").strip()
    if not cid or not csec:
        return False
    low = cid.lower()
    if any(p in low for p in _PLACEHOLDER_MARKERS):
        return False
    if "your-oauth" in (settings.github_client_secret or "").lower():
        return False
    return True


async def require_auth(request: Request) -> dict[str, Any]:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {
        "username": request.session.get("github_username"),
        "avatar": request.session.get("github_avatar"),
        "name": request.session.get("github_name"),
    }


async def get_github_token(request: Request) -> str:
    token = request.session.get("github_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No GitHub token in session")
    return str(token)


@router.get("/github")
async def github_oauth_start(request: Request) -> RedirectResponse:
    if not _github_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "GitHub OAuth is not configured — set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in "
                ".env to the values from your GitHub OAuth app (Developer Settings). "
                "GITHUB_REDIRECT_URI must exactly match the app's Authorization callback URL."
            ),
        )
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    params = {
        "client_id": settings.github_client_id,
        "scope": "repo,read:user,user:email",
        "redirect_uri": settings.github_redirect_uri,
        "state": state,
    }
    url = "https://github.com/login/oauth/authorize?" + urlencode(params)
    return RedirectResponse(url, status_code=302)


@router.get("/github/callback")
async def github_oauth_callback(request: Request, code: str, state: str) -> RedirectResponse:
    saved = request.session.get("oauth_state")
    if not saved or saved != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        token_res.raise_for_status()
        token_data = token_res.json()

        if token_data.get("error"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "GitHub authentication failed: "
                    f"{token_data.get('error_description', token_data['error'])}. "
                    "Verify GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET match your OAuth app, and "
                    "GITHUB_REDIRECT_URI matches the Authorization callback URL registered on GitHub "
                    f"(expected: {settings.github_redirect_uri})."
                ),
            )

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=400,
                detail="GitHub did not return an access token — check OAuth app settings and callback URL.",
            )

        try:
            user_res = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            user_res.raise_for_status()
            user = user_res.json()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to load GitHub profile: {exc}",
            ) from exc

    login = user.get("login")
    if not login:
        raise HTTPException(status_code=400, detail="GitHub user profile did not include a login.")

    request.session["authenticated"] = True
    request.session["github_token"] = access_token
    request.session["github_username"] = login
    request.session["github_avatar"] = user.get("avatar_url")
    request.session["github_name"] = user.get("name") or login
    request.session["login_at"] = datetime.now(timezone.utc).isoformat()
    return RedirectResponse(settings.frontend_url, status_code=302)


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {
        "username": request.session.get("github_username"),
        "avatar": request.session.get("github_avatar"),
        "name": request.session.get("github_name"),
        "login_at": request.session.get("login_at"),
    }


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(settings.frontend_url, status_code=302)


@router.get("/status")
async def auth_status(request: Request) -> dict[str, Any]:
    return {
        "authenticated": bool(request.session.get("authenticated")),
        "username": request.session.get("github_username"),
        "avatar": request.session.get("github_avatar"),
        "has_token": bool(request.session.get("github_token")),
        "oauth_configured": _github_oauth_configured(),
    }

from __future__ import annotations

import secrets
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from core.config import get_settings
from core.logging_config import get_logger
from utils.auth_utils import get_token_scopes

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = get_logger("auth.github")


@router.get("/github")
async def github_login(request: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    github_auth_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        "&scope=repo,read:user,user:email"
        f"&redirect_uri={settings.github_redirect_uri}"
        f"&state={state}"
    )
    return RedirectResponse(url=github_auth_url, status_code=302)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"GitHub OAuth denied: {error}")
    if code is None:
        raise HTTPException(status_code=400, detail="No authorization code received from GitHub")
    if state != request.session.get("oauth_state"):
        raise HTTPException(status_code=400, detail="Invalid OAuth state — possible CSRF attack")

    request.session.pop("oauth_state", None)

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
            },
        )
        token_data = token_resp.json()
        if "error" in token_data:
            logger.error("GitHub token exchange failed: %s", token_data)
            raise HTTPException(
                status_code=400,
                detail=f"Token exchange failed: {token_data.get('error_description', token_data['error'])}",
            )

        access_token = token_data["access_token"]
        token_scope = token_data.get("scope", "")

        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()

    github_username = user_data.get("login")
    github_avatar = user_data.get("avatar_url", "")
    github_name = user_data.get("name", github_username)
    github_email = user_data.get("email", "")

    request.session["authenticated"] = True
    request.session["github_token"] = access_token
    request.session["github_username"] = github_username
    request.session["github_avatar"] = github_avatar
    request.session["github_name"] = github_name
    request.session["github_email"] = github_email
    request.session["token_scope"] = token_scope
    request.session["login_at"] = datetime.utcnow().isoformat()

    logger.info("GitHub OAuth success: user=%s scopes=%s", github_username, token_scope)
    return RedirectResponse(url=settings.frontend_url, status_code=302)


@router.get("/me")
async def get_current_user(request: Request) -> JSONResponse:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated — please login with GitHub")

    return JSONResponse(
        {
            "username": request.session.get("github_username"),
            "avatar": request.session.get("github_avatar"),
            "name": request.session.get("github_name"),
            "email": request.session.get("github_email"),
            "token_scope": request.session.get("token_scope", ""),
            "login_at": request.session.get("login_at"),
            "authenticated": True,
        }
    )


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url=settings.frontend_url, status_code=302)


async def require_auth(request: Request) -> dict:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return request.session


async def get_github_token(request: Request) -> str:
    await require_auth(request)
    token = request.session.get("github_token")
    if not token:
        raise HTTPException(status_code=401, detail="GitHub token missing — please re-authenticate")
    return token


@router.get("/status")
async def auth_status(request: Request) -> dict:
    token = request.session.get("github_token")
    has_token = bool(token)
    token_valid = False

    if has_token:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.github.com/rate_limit",
                    headers={"Authorization": f"token {token}"},
                )
                token_valid = resp.status_code == 200
        except httpx.RequestError:
            token_valid = False

    return {
        "authenticated": bool(request.session.get("authenticated")),
        "username": request.session.get("github_username"),
        "has_github_token": has_token,
        "token_valid": token_valid,
    }


@router.get("/github/permissions")
async def github_permissions(token: str = Depends(get_github_token)) -> dict:
    scopes = get_token_scopes(token)
    return {
        "scopes": scopes,
        "has_repo_access": "repo" in scopes,
        "has_user_access": "read:user" in scopes,
        "sufficient_for_auto_pr": "repo" in scopes,
    }

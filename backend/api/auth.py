from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from core.config import get_settings
from core.logging_config import get_logger
from utils.auth_utils import get_token_scopes

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = get_logger("auth.github")


def generate_state_with_signature() -> tuple[str, str]:
    """Generate a cryptographically signed state token."""
    state_token = secrets.token_urlsafe(24)
    # Create HMAC signature of the state token
    signature = hmac.new(
        settings.session_secret_key.encode(),
        state_token.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    # Combine state and signature
    signed_state = f"{state_token}.{signature}"
    return state_token, signed_state


def validate_state_signature(signed_state: str) -> bool:
    """Validate a cryptographically signed state token."""
    try:
        state_token, signature = signed_state.rsplit(".", 1)
        expected_sig = hmac.new(
            settings.session_secret_key.encode(),
            state_token.encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        return hmac.compare_digest(signature, expected_sig)
    except (ValueError, AttributeError):
        return False


@router.get("/github")
async def github_login(request: Request) -> RedirectResponse:
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth is not configured — set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in backend/.env (values from your GitHub OAuth app).",
        )

    state_token, signed_state = generate_state_with_signature()
    # Also store in session as backup
    request.session["oauth_state_token"] = state_token

    github_auth_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={quote(settings.github_client_id, safe='')}"
        "&scope=repo,read:user,user:email"
        f"&redirect_uri={quote(settings.github_redirect_uri, safe='')}"
        f"&state={quote(signed_state, safe='')}"
    )
    logger.info("GitHub OAuth initiated")
    
    return RedirectResponse(url=github_auth_url, status_code=302)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    if error:
        logger.error(f"GitHub OAuth error: {error}")
        raise HTTPException(status_code=400, detail=f"GitHub OAuth denied: {error}")
    if code is None:
        logger.error("No authorization code received")
        raise HTTPException(status_code=400, detail="No authorization code received from GitHub")
    
    # Validate state signature
    if not state or not validate_state_signature(state):
        logger.error(f"State validation failed: {state is not None}")
        raise HTTPException(status_code=400, detail="Invalid OAuth state — possible CSRF attack")

    # Clean up session
    request.session.pop("oauth_state_token", None)

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
                detail=f"GitHub authentication failed: {token_data.get('error_description', token_data['error'])} — "
                       "please ensure your GitHub OAuth app credentials are correctly configured.",
            )

        if "access_token" not in token_data:
            logger.error("GitHub response missing access_token: %s", token_data)
            raise HTTPException(
                status_code=400,
                detail="GitHub did not return an access token — authentication cannot proceed.",
            )

        access_token = token_data["access_token"]
        token_scope = token_data.get("scope", "")

        try:
            user_resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            user_resp.raise_for_status()
            user_data = user_resp.json()
        except httpx.HTTPError as e:
            logger.error("Failed to fetch GitHub user profile: %s", str(e))
            raise HTTPException(
                status_code=400,
                detail="Failed to retrieve GitHub user profile — your token may have expired or permissions may be insufficient.",
            )

    github_username = user_data.get("login")
    if not github_username:
        logger.error("GitHub user data missing login field: %s", user_data)
        raise HTTPException(
            status_code=400,
            detail="GitHub user profile is incomplete — cannot determine username.",
        )
    
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

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from urllib.parse import quote, urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from core.config import get_settings
from core.logging_config import get_logger
from utils.auth_utils import get_token_scopes

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = get_logger("auth.github")

_PLACEHOLDER_MARKERS = ("your-oauth", "replace_oauth", "changeme")


def _oauth_redirect_uri(request: Request) -> str:
    configured = (settings.github_redirect_uri or "").strip()
    if configured and not any(m in configured.lower() for m in _PLACEHOLDER_MARKERS):
        return configured
    return f"{request.url.scheme}://{request.url.netloc}/api/v1/auth/github/callback"


def _frontend_redirect(request: Request) -> str:
    configured = (settings.frontend_url or "").strip()
    if configured:
        return configured.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}"


def _auth_failure_redirect(request: Request, message: str) -> RedirectResponse:
    target = _frontend_redirect(request) + f"?auth_error={quote(message)}"
    return RedirectResponse(url=target, status_code=302)


def _github_oauth_configured() -> bool:
    cid = (settings.github_client_id or "").strip()
    csec = (settings.github_client_secret or "").strip()
    if not cid or not csec:
        return False
    low = cid.lower()
    return not any(m in low for m in _PLACEHOLDER_MARKERS)


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
    if not _github_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth is not configured — set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in backend/.env (values from your GitHub OAuth app).",
        )

    state_token, signed_state = generate_state_with_signature()
    request.session["oauth_state_token"] = state_token
    redirect_uri = _oauth_redirect_uri(request)
    request.session["oauth_redirect_uri"] = redirect_uri

    params = {
        "client_id": settings.github_client_id,
        "scope": "repo,read:user,user:email",
        "redirect_uri": redirect_uri,
        "state": signed_state,
    }
    github_auth_url = "https://github.com/login/oauth/authorize?" + urlencode(params)
    logger.info("GitHub OAuth initiated redirect_uri=%s", redirect_uri)

    return RedirectResponse(url=github_auth_url, status_code=302)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    if error:
        logger.error("GitHub OAuth error: %s", error)
        return _auth_failure_redirect(request, f"GitHub OAuth denied: {error}")
    if code is None:
        logger.error("No authorization code received")
        return _auth_failure_redirect(request, "No authorization code received from GitHub")

    if not state or not validate_state_signature(state):
        logger.error("State validation failed: %s", state is not None)
        return _auth_failure_redirect(
            request,
            "Invalid OAuth state — open the console and click Login with GitHub again.",
        )

    request.session.pop("oauth_state_token", None)
    redirect_uri = request.session.pop("oauth_redirect_uri", None) or _oauth_redirect_uri(request)

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
                "redirect_uri": redirect_uri,
            },
        )
        token_data = token_resp.json()
        if "error" in token_data:
            logger.error("GitHub token exchange failed: %s", token_data)
            return _auth_failure_redirect(
                request,
                f"GitHub authentication failed: {token_data.get('error_description', token_data['error'])}. "
                f"Register callback URL {redirect_uri} on your OAuth app.",
            )

        if "access_token" not in token_data:
            logger.error("GitHub response missing access_token: %s", token_data)
            return _auth_failure_redirect(
                request, "GitHub did not return an access token — check OAuth app settings."
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
            return _auth_failure_redirect(request, "Failed to retrieve GitHub user profile.")

    github_username = user_data.get("login")
    if not github_username:
        logger.error("GitHub user data missing login field: %s", user_data)
        return _auth_failure_redirect(request, "GitHub user profile is incomplete.")
    
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
    target = _frontend_redirect(request)
    return RedirectResponse(url=f"{target}?auth_success=1", status_code=302)


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
    if request.session.get("authenticated"):
        return request.session
    cfg = get_settings()
    api_key = request.headers.get("X-API-Key") or request.headers.get("X-ORION-API-Key")
    if api_key and (cfg.auth_enabled or cfg.api_require_auth):
        from services.auth import AuthService

        user = AuthService(cfg).authenticate(api_key)
        return {
            "authenticated": True,
            "github_username": user.user_id,
            "roles": user.roles,
            "api_key_auth": True,
        }
    if cfg.multimodal_auth_required or cfg.app_env.lower() in {"prod", "production"}:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {
        "authenticated": False,
        "github_username": "anonymous",
        "dev_anonymous": True,
    }


async def optional_pipeline_auth(request: Request) -> dict:
    """Session or API key when AUTH_ENABLED / API_REQUIRE_AUTH is set."""
    cfg = get_settings()
    if not cfg.auth_enabled and not cfg.api_require_auth:
        return {"authenticated": False, "dev_anonymous": True}
    if request.session.get("authenticated"):
        return request.session
    api_key = request.headers.get("X-API-Key") or request.headers.get("X-ORION-API-Key")
    if api_key:
        from services.auth import AuthService

        user = AuthService(cfg).authenticate(api_key)
        return {
            "authenticated": True,
            "github_username": user.user_id,
            "roles": user.roles,
            "api_key_auth": True,
        }
    raise HTTPException(status_code=401, detail="Authentication required")


async def get_github_token(request: Request) -> str:
    await require_auth(request)
    token = request.session.get("github_token")
    if not token:
        raise HTTPException(status_code=401, detail="GitHub token missing — please re-authenticate")
    return token


async def optional_github_token(request: Request) -> str | None:
    token = request.session.get("github_token")
    return token if token else None


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

    redirect_uri = _oauth_redirect_uri(request)
    return {
        "authenticated": bool(request.session.get("authenticated")),
        "username": request.session.get("github_username"),
        "has_github_token": has_token,
        "token_valid": token_valid,
        "oauth_configured": _github_oauth_configured(),
        "oauth_client_id": settings.github_client_id if _github_oauth_configured() else None,
        "oauth_callback_url": redirect_uri if _github_oauth_configured() else None,
        "login_url": f"{request.url.scheme}://{request.url.netloc}/api/v1/auth/github",
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

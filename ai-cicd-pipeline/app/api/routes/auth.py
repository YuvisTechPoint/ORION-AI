import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.config import settings
from app.services.auth_service import OrionUserContext, auth_service
from app.services.user_preferences import get_user_preferences, update_user_preferences

router = APIRouter(prefix="/auth", tags=["Authentication"])

_PLACEHOLDER_MARKERS = (
    "your-oauth-app-client-id",
    "your-oauth-app-client-secret",
)
_API_KEY_HEADERS = ("x-orion-api-key", "x-api-key")


def _configured_redirect_uri() -> str | None:
    configured = (settings.github_redirect_uri or "").strip()
    if not configured or "your-oauth" in configured.lower():
        return None
    return configured


def _oauth_redirect_uri(request: Request) -> str:
    """Callback URL sent to GitHub — must exactly match a URL on the OAuth app."""
    configured = _configured_redirect_uri()
    if configured:
        return configured
    return f"{request.url.scheme}://{request.url.netloc}/api/v1/auth/github/callback"


def _auth_failure_redirect(request: Request, message: str) -> RedirectResponse:
    target = _frontend_redirect(request) + f"?auth_error={quote(message)}"
    return RedirectResponse(target, status_code=302)


def _frontend_redirect(request: Request) -> str:
    """Return the dashboard URL — must share host with GITHUB_REDIRECT_URI for session cookies."""
    configured = (settings.frontend_url or "").strip()
    if configured and "your-oauth" not in configured.lower():
        return configured.rstrip("/") + "/"
    path = "/ui/"
    return f"{request.url.scheme}://{request.url.netloc}{path}"


def _issue_oauth_state() -> str:
    """Signed state survives the GitHub redirect even if the session cookie is not replayed."""
    nonce = secrets.token_urlsafe(32)
    sig = hmac.new(
        settings.session_secret_key.encode(),
        nonce.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()[:16]
    return f"{nonce}.{sig}"


def _verify_oauth_state(state: str) -> bool:
    if "." not in state:
        return False
    nonce, sig = state.rsplit(".", 1)
    if not nonce or not sig:
        return False
    expected = hmac.new(
        settings.session_secret_key.encode(),
        nonce.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()[:16]
    return hmac.compare_digest(expected, sig)


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


def _api_key_from_request(request: Request) -> str | None:
    for header in _API_KEY_HEADERS:
        value = request.headers.get(header)
        if value:
            return value.strip()
    return None


def _validate_api_key(provided: str | None) -> OrionUserContext | None:
    return auth_service.resolve_api_key(provided)


def _context_from_request(request: Request) -> dict[str, Any]:
    session_user = _session_user(request)
    if session_user:
        session_user.setdefault("roles", ["operator"])
        return session_user
    ctx = _validate_api_key(_api_key_from_request(request))
    if ctx:
        return {"username": ctx.user_id, "api_key_auth": True, "roles": ctx.roles}
    return {"username": "anonymous", "roles": ["anonymous"]}


def require_pipeline_operator(user: dict[str, Any]) -> None:
    if not settings.api_require_auth:
        return
    roles = set(user.get("roles") or [])
    if roles.intersection({"admin", "operator", "approver"}):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator role required")


def _session_user(request: Request) -> dict[str, Any] | None:
    if not request.session.get("authenticated"):
        return None
    return {
        "username": request.session.get("github_username"),
        "avatar": request.session.get("github_avatar"),
        "name": request.session.get("github_name"),
    }


async def require_auth(request: Request) -> dict[str, Any]:
    session_user = _session_user(request)
    if session_user:
        session_user.setdefault("roles", ["operator"])
        return session_user
    ctx = _validate_api_key(_api_key_from_request(request))
    if ctx:
        return {"username": ctx.user_id, "api_key_auth": True, "roles": ctx.roles}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def optional_auth(request: Request) -> dict[str, Any]:
    """Enforce login (session or ORION API key) when API_REQUIRE_AUTH is enabled."""
    if settings.api_require_auth:
        return await require_auth(request)
    session_user = _session_user(request)
    if session_user:
        session_user.setdefault("roles", ["operator"])
        return session_user
    ctx = _validate_api_key(_api_key_from_request(request))
    if ctx:
        return {"username": ctx.user_id, "api_key_auth": True, "roles": ctx.roles}
    return {
        "username": request.session.get("github_username") or "anonymous",
        "avatar": request.session.get("github_avatar"),
        "name": request.session.get("github_name"),
        "roles": ["anonymous"],
    }


async def ws_require_auth(websocket: WebSocket) -> bool:
    """Return True when the WebSocket caller is allowed to subscribe."""
    if not settings.api_require_auth:
        return True
    session = websocket.scope.get("session") or {}
    if session.get("authenticated"):
        return True
    query = websocket.query_params
    token = query.get("api_key") or query.get("token")
    return _validate_api_key(token) is not None


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
    state = _issue_oauth_state()
    request.session["oauth_state"] = state
    redirect_uri = _oauth_redirect_uri(request)
    request.session["oauth_redirect_uri"] = redirect_uri
    params = {
        "client_id": settings.github_client_id,
        "scope": "repo,read:user,user:email",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    url = "https://github.com/login/oauth/authorize?" + urlencode(params)
    return RedirectResponse(url, status_code=302)


@router.get("/github/callback")
async def github_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    if error:
        return _auth_failure_redirect(request, error_description or error)

    if not code or not state:
        return _auth_failure_redirect(request, "GitHub did not return an authorization code.")

    saved = request.session.get("oauth_state")
    if not ((saved and saved == state) or _verify_oauth_state(state)):
        return _auth_failure_redirect(
            request,
            "Invalid OAuth state — open the dashboard and click Login with GitHub again (do not bookmark the callback URL).",
        )
    request.session.pop("oauth_state", None)

    redirect_uri = request.session.pop("oauth_redirect_uri", None) or _oauth_redirect_uri(request)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            token_res = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            token_res.raise_for_status()
            token_data = token_res.json()

            if token_data.get("error"):
                return _auth_failure_redirect(
                    request,
                    (
                        f"GitHub rejected the token exchange ({token_data.get('error')}): "
                        f"{token_data.get('error_description', '')}. "
                        f"Register callback URL {redirect_uri} on your OAuth app and ensure "
                        "GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET in ai-cicd-pipeline/.env match that app."
                    ).strip(),
                )

            access_token = token_data.get("access_token")
            if not access_token:
                return _auth_failure_redirect(
                    request, "GitHub did not return an access token — check OAuth app settings."
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
                return _auth_failure_redirect(request, f"Failed to load GitHub profile: {exc}")

        login = user.get("login")
        if not login:
            return _auth_failure_redirect(request, "GitHub user profile did not include a login.")

        request.session["authenticated"] = True
        request.session["github_token"] = access_token
        request.session["github_username"] = login
        request.session["github_avatar"] = user.get("avatar_url")
        request.session["github_name"] = user.get("name") or login
        request.session["login_at"] = datetime.now(timezone.utc).isoformat()
        target = _frontend_redirect(request)
        return RedirectResponse(f"{target}?auth_success=1", status_code=302)
    except httpx.HTTPError as exc:
        return _auth_failure_redirect(request, f"Could not reach GitHub during login: {exc}")


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
    return RedirectResponse(_frontend_redirect(request), status_code=302)


@router.get("/status")
async def auth_status(request: Request) -> dict[str, Any]:
    return {
        "authenticated": bool(request.session.get("authenticated")),
        "username": request.session.get("github_username"),
        "avatar": request.session.get("github_avatar"),
        "has_token": bool(request.session.get("github_token")),
        "oauth_configured": _github_oauth_configured(),
        "oauth_client_id": settings.github_client_id if _github_oauth_configured() else None,
        "oauth_callback_url": _oauth_redirect_uri(request) if _github_oauth_configured() else None,
        "oauth_register_hint": (
            "Add this exact URL under GitHub OAuth app → Authorization callback URL: "
            + _oauth_redirect_uri(request)
            if _github_oauth_configured()
            else None
        ),
        "api_require_auth": settings.api_require_auth,
        "api_key_configured": bool((settings.orion_api_key or "").strip()),
    }


class PreferencesUpdate(BaseModel):
    default_branch: str | None = None
    default_repo_url: str | None = None
    default_repo_name: str | None = None
    auto_pr_enabled: bool | None = None
    notify_on_block: bool | None = None
    open_github_profile: bool | None = None


def _github_auth_block(request: Request) -> dict[str, Any]:
    oauth = _github_oauth_configured()
    callback = _oauth_redirect_uri(request) if oauth else None
    return {
        "connected": bool(request.session.get("authenticated")),
        "has_token": bool(request.session.get("github_token")),
        "oauth_configured": oauth,
        "oauth_client_id": settings.github_client_id if oauth else None,
        "oauth_callback_url": callback,
        "scopes": "repo, read:user, user:email",
        "login_url": f"{request.url.scheme}://{request.url.netloc}/api/v1/auth/github",
        "logout_url": f"{request.url.scheme}://{request.url.netloc}/api/v1/auth/logout",
        "profile_url": (
            f"https://github.com/{request.session.get('github_username')}"
            if request.session.get("github_username")
            else None
        ),
    }


def _platform_block(request: Request) -> dict[str, Any]:
    return {
        "product": "ORION CI/CD",
        "environment": settings.app_env,
        "deploy_mode": settings.deploy_mode,
        "api_require_auth": settings.api_require_auth,
        "api_base": f"{request.url.scheme}://{request.url.netloc}",
        "frontend_url": _frontend_redirect(request),
        "docs_url": f"{request.url.scheme}://{request.url.netloc}/docs",
    }


@router.get("/profile")
async def auth_profile(request: Request) -> dict[str, Any]:
    """Operator profile, GitHub connection, and saved pipeline preferences."""
    authenticated = bool(request.session.get("authenticated"))
    user = None
    if authenticated:
        user = {
            "username": request.session.get("github_username"),
            "name": request.session.get("github_name"),
            "avatar": request.session.get("github_avatar"),
            "login_at": request.session.get("login_at"),
        }
    return {
        "authenticated": authenticated,
        "user": user,
        "github": _github_auth_block(request),
        "preferences": get_user_preferences(request.session),
        "platform": _platform_block(request),
    }


@router.patch("/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    request: Request,
) -> dict[str, Any]:
    if not request.session.get("authenticated"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in with GitHub to save profile settings on this platform.",
        )
    prefs = update_user_preferences(request.session, body.model_dump(exclude_unset=True))
    return {"preferences": prefs, "saved": True}

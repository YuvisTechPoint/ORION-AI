from typing import Any

from fastapi import APIRouter

from app.config import settings
from app.services.navigation import stack_catalog

router = APIRouter(prefix="/runtime", tags=["Runtime"])


@router.get("/navigation")
async def navigation() -> dict[str, Any]:
    """Cross-stack URLs and labels for the ORION dashboard navigation bar."""
    return stack_catalog()


@router.get("/config")
async def runtime_config() -> dict[str, Any]:
    """Public runtime identifiers (no secrets)."""
    nav = stack_catalog()
    return {
        "product": nav["product"],
        "environment": settings.app_env,
        "app_port": settings.app_port,
        "host": settings.stack_host,
        "frontend_url": settings.frontend_url,
        "github_redirect_uri": settings.github_redirect_uri,
        "api_require_auth": settings.api_require_auth,
        "orion": nav["orion"],
    }

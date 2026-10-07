"""Cross-stack navigation map (Binary-v2 Command Hub layout)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.config import settings

_SHARED = Path(__file__).resolve().parents[3] / "shared"
if str(_SHARED.parent) not in sys.path:
    sys.path.insert(0, str(_SHARED.parent))

from shared.stack_catalog import build_stack_catalog  # noqa: E402


def stack_catalog() -> dict[str, Any]:
    """Navigation catalog for dashboards and the Command Hub."""
    orion_api = settings.orion_api_url
    orion_ui = settings.orion_ui_url
    return build_stack_catalog(
        active_stack="orion",
        host=settings.stack_host,
        hub_url=settings.hub_url,
        canonical_api_url=settings.canonical_api_url,
        canonical_ui_url=settings.canonical_ui_url,
        orion_api_url=orion_api,
        orion_ui_url=orion_ui,
        devops_api_url=settings.devops_api_url,
        devops_ui_url=settings.devops_ui_url,
        product="ORION CI/CD",
        orion_block={
            "api_base": orion_api,
            "ui_url": orion_ui,
            "docs_url": f"{orion_api}/docs",
            "oauth_login_url": f"{orion_api}/api/v1/auth/github",
            "oauth_callback_url": settings.github_redirect_uri,
            "oauth_logout_url": f"{orion_api}/api/v1/auth/logout",
        },
    )

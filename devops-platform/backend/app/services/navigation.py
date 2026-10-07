"""Cross-stack navigation for DevOps Platform."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.config import get_settings

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.stack_catalog import build_stack_catalog  # noqa: E402


def stack_catalog() -> dict[str, Any]:
    settings = get_settings()
    host = "127.0.0.1"
    api = f"http://{host}:8002"
    return build_stack_catalog(
        active_stack="platform",
        host=host,
        hub_url=getattr(settings, "hub_url", None),
        canonical_api_url=getattr(settings, "canonical_api_url", None),
        canonical_ui_url=getattr(settings, "canonical_ui_url", None),
        orion_api_url=getattr(settings, "orion_api_url", None),
        orion_ui_url=f"{getattr(settings, 'orion_api_url', 'http://127.0.0.1:8001')}/ui/",
        devops_api_url=api,
        devops_ui_url=getattr(settings, "devops_ui_url", None),
        product="DevOps Platform",
    )

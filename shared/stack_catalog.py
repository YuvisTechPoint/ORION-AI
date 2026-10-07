"""Binary-v2 cross-stack navigation catalog — single source loaded from config/stacks.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STACKS_JSON = _REPO_ROOT / "config" / "stacks.json"


def repo_root() -> Path:
    return _REPO_ROOT


def _read_raw() -> dict[str, Any]:
    if not _STACKS_JSON.is_file():
        return {"host": "127.0.0.1", "stacks": [], "views": []}
    return json.loads(_STACKS_JSON.read_text(encoding="utf-8-sig"))


def _url(host: str, port: int, path: str = "") -> str:
    base = f"http://{host}:{port}"
    return f"{base}{path}" if path else base


def build_stack_catalog(
    *,
    active_stack: str,
    host: str = "127.0.0.1",
    hub_url: str | None = None,
    canonical_api_url: str | None = None,
    canonical_ui_url: str | None = None,
    orion_api_url: str | None = None,
    orion_ui_url: str | None = None,
    devops_api_url: str | None = None,
    devops_ui_url: str | None = None,
    product: str | None = None,
    orion_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge config/stacks.json with runtime URLs from each stack's settings."""
    raw = _read_raw()
    host = str(raw.get("host") or host)

    def canon_api() -> str:
        return canonical_api_url or _url(host, 8000)

    def canon_ui() -> str:
        return canonical_ui_url or _url(host, 5173)

    def orion_api() -> str:
        return orion_api_url or _url(host, 8001)

    def orion_ui() -> str:
        return orion_ui_url or f"{orion_api()}/ui/"

    def devops_api() -> str:
        return devops_api_url or _url(host, 8002)

    def devops_ui() -> str:
        return devops_ui_url or _url(host, 3000)

    overrides: dict[str, dict[str, str | None]] = {
        "hub": {
            "ui": hub_url or _url(host, 5180),
            "api": None,
            "health": None,
            "ready": None,
            "intelligence": None,
        },
        "canonical": {
            "ui": canon_ui(),
            "api": canon_api(),
            "health": f"{canon_api()}/health",
            "ready": f"{canon_api()}/ready",
            "intelligence": f"{canon_api()}/api/v1/intelligence/dashboard",
        },
        "orion": {
            "ui": orion_ui(),
            "api": orion_api(),
            "health": f"{orion_api()}/health",
            "ready": f"{orion_api()}/ready",
            "intelligence": f"{orion_api()}/api/v1/intelligence/dashboard",
        },
        "platform": {
            "ui": devops_ui(),
            "api": devops_api(),
            "health": f"{devops_api()}/health",
            "ready": f"{devops_api()}/ready",
            "intelligence": f"{devops_api()}/api/intelligence/dashboard",
        },
    }

    stacks: list[dict[str, Any]] = []
    for entry in raw.get("stacks") or []:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("id") or "")
        merged = {**entry, **{k: v for k, v in overrides.get(sid, {}).items() if v is not None}}
        if sid == "hub":
            for key in ("api", "health", "ready", "intelligence"):
                merged[key] = overrides["hub"].get(key)
        stacks.append(merged)

    titles = {
        "hub": "Command Hub",
        "canonical": "DevOps Console",
        "orion": "ORION CI/CD",
        "platform": "DevOps Platform",
    }
    result: dict[str, Any] = {
        "host": host,
        "active_stack": active_stack,
        "product": product or titles.get(active_stack, "Binary-v2"),
        "stacks": stacks,
        "views": raw.get("views") or [],
        "catalog_source": str(_STACKS_JSON),
    }
    if orion_block:
        result["orion"] = orion_block
    return result


def hub_probe_stacks(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Stacks shown on Command Hub cards (excludes hub launcher itself)."""
    cat = catalog or build_stack_catalog(active_stack="hub")
    return [s for s in cat.get("stacks") or [] if s.get("id") != "hub" and s.get("health")]

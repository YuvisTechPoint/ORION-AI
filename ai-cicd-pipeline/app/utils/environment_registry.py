"""Environment registry for ORION deployment targets."""

from __future__ import annotations

from typing import Any

from app.config import settings


def build_environment_registry() -> dict[str, Any]:
    environments: list[dict[str, Any]] = [
        {
            "name": settings.deploy_environment or "staging",
            "kind": "runtime",
            "url": settings.staging_url.rstrip("/"),
            "health_path": "/health",
            "container_port": settings.staging_container_port,
            "host_port": settings.staging_host_port,
            "registry": settings.container_registry if settings.registry_enabled else None,
        },
        {
            "name": "preview",
            "kind": "preview",
            "url_template": settings.preview_base_url,
            "simulated": True,
        },
        {
            "name": "hub",
            "kind": "control_plane",
            "url": settings.hub_url.rstrip("/"),
        },
    ]
    return {
        "default_environment": settings.deploy_environment or "staging",
        "deploy_mode_resolved_hint": settings.deploy_mode,
        "environments": environments,
        "count": len(environments),
        "summary": f"{len(environments)} registered environment(s); default={settings.deploy_environment}.",
    }

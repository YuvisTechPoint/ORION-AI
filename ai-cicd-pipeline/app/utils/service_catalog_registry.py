"""Service catalog registry — org/repo overrides and IDP golden paths."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

DEFAULT_GOLDEN_PATHS: list[dict[str, str]] = [
    {"id": "trigger_pipeline", "label": "Trigger pipeline", "path": "/api/v1/pipeline/trigger"},
    {"id": "view_runs", "label": "View pipeline runs", "path": "/api/v1/pipeline/runs"},
    {"id": "repository_intel", "label": "Repository intelligence", "path": "/api/v1/intelligence/repository"},
    {"id": "service_catalog", "label": "Service catalog", "path": "/api/v1/intelligence/catalog"},
    {"id": "incidents", "label": "Incident command center", "path": "/api/v1/incidents"},
]


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def resolve_catalog_overrides(repo: str) -> dict[str, Any]:
    org = repo.split("/", 1)[0] if "/" in repo else repo
    catalog_json = _parse_json(settings.service_catalog_json)
    org_block = catalog_json.get(org) if isinstance(catalog_json.get(org), dict) else {}
    repo_block = catalog_json.get(repo) if isinstance(catalog_json.get(repo), dict) else {}
    merged: dict[str, Any] = {}
    for block in (org_block, repo_block):
        if block.get("services") and isinstance(block["services"], dict):
            merged.setdefault("services", {}).update(block["services"])
        if block.get("links") and isinstance(block["links"], dict):
            merged.setdefault("links", {}).update(block["links"])
        if block.get("team"):
            merged["team"] = block["team"]
        if block.get("tier"):
            merged["tier"] = block["tier"]
    return merged


def build_idp_portal_catalog() -> dict[str, Any]:
    custom = _parse_json(settings.idp_golden_paths_json)
    paths = custom.get("golden_paths") if isinstance(custom.get("golden_paths"), list) else DEFAULT_GOLDEN_PATHS
    return {
        "golden_paths": paths,
        "self_service_actions": [
            {"id": "onboard_service", "label": "Register service metadata", "api": "POST /api/v1/intelligence/catalog"},
            {"id": "request_deploy", "label": "Request deployment", "api": "POST /api/v1/pipeline/trigger"},
            {"id": "run_security_scan", "label": "Run security scan", "api": "POST /api/v1/pipeline/trigger"},
        ],
        "documentation_links": [
            {"label": "ORION agents reference", "path": "/ui/"},
            {"label": "Policy catalog", "path": "/api/v1/policies/catalog"},
        ],
        "summary": f"IDP portal with {len(paths)} golden path(s).",
    }

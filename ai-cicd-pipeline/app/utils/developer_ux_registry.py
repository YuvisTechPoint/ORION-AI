"""Developer UX registry — CLI parity, VS Code extension catalog, IDE integrations."""

from __future__ import annotations

from typing import Any

from app.config import settings

VSCODE_EXTENSION_ID = "orion.orion-devops"
VSCODE_COMMANDS: list[dict[str, Any]] = [
    {"id": "orion.showRuns", "title": "ORION: Show Recent Pipeline Runs", "api": "GET /api/v1/pipeline/runs"},
    {"id": "orion.triggerScan", "title": "ORION: Trigger Pipeline Scan", "api": "POST /api/v1/pipeline/trigger"},
    {"id": "orion.localRisk", "title": "ORION: Local Change Risk", "api": "local git diff"},
    {"id": "orion.openDashboard", "title": "ORION: Open Dashboard", "api": "GET /ui/"},
    {"id": "orion.openIntelligence", "title": "ORION: Open Intelligence Panel", "api": "GET /api/v1/intelligence/dashboard"},
]

CLI_COMMAND_GROUPS: list[dict[str, Any]] = [
    {
        "group": "pipeline",
        "commands": ["scan", "test", "deploy", "fix", "runs"],
        "description": "Trigger, inspect, and resume pipelines",
    },
    {
        "group": "intelligence",
        "commands": ["risk", "explain", "intelligence", "rag", "release", "finops", "governance", "mesh"],
        "description": "Risk, RAG, release, FinOps, and governance surfaces",
    },
    {
        "group": "platform",
        "commands": ["catalog", "policy", "multimodal", "memory", "health", "workers"],
        "description": "Service catalog, policies, multimodal, and ops",
    },
    {
        "group": "developer",
        "commands": ["dev status", "dev vscode", "dev github-app", "dev catalog"],
        "description": "IDE and GitHub App developer surfaces",
    },
]


def build_vscode_extension_manifest() -> dict[str, Any]:
    api = settings.orion_api_url.rstrip("/")
    return {
        "extension_id": VSCODE_EXTENSION_ID,
        "name": "orion-devops",
        "display_name": "ORION DevOps",
        "version": "0.1.0",
        "publisher": "orion",
        "engines": {"vscode": "^1.85.0"},
        "categories": ["Other", "SCM Providers"],
        "activation_events": ["onStartupFinished"],
        "default_api_url": api,
        "configuration": {
            "orion.apiUrl": {"type": "string", "default": api, "description": "ORION API base URL"},
            "orion.apiKey": {"type": "string", "default": "", "description": "X-ORION-API-Key when auth enabled"},
            "orion.pollIntervalSeconds": {"type": "number", "default": 30, "minimum": 10},
        },
        "commands": VSCODE_COMMANDS,
        "package_path": "developer/vscode-orion",
        "summary": f"ORION DevOps sidebar and commands against {api}.",
    }


def build_developer_catalog() -> dict[str, Any]:
    vscode = build_vscode_extension_manifest()
    return {
        "product": "ORION",
        "cli_entrypoint": "orion",
        "cli_groups": CLI_COMMAND_GROUPS,
        "vscode": vscode,
        "dashboard_url": settings.orion_ui_url,
        "api_docs_url": f"{settings.orion_api_url.rstrip('/')}/docs",
        "hub_url": settings.hub_url,
        "auth_required": settings.api_require_auth,
        "summary": "Developer UX catalog: CLI, VS Code extension, GitHub App, and dashboard links.",
    }

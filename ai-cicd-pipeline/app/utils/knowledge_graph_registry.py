"""Knowledge graph registry — node/relation types and org-scoped policy defaults."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

NODE_TYPES = frozenset(
    {
        "service",
        "api",
        "database",
        "file",
        "dependency",
        "artifact",
        "commit",
        "pipeline_run",
        "incident",
        "test",
        "deployment",
        "owner",
        "framework",
    }
)

RELATION_TYPES = frozenset(
    {
        "depends_on",
        "calls",
        "owns",
        "produced",
        "modified",
        "deployed",
        "triggered",
        "tests",
        "contains",
        "links",
    }
)


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def resolve_knowledge_graph_policy(repo: str = "") -> dict[str, Any]:
    custom = _parse_json(settings.knowledge_graph_policy_json)
    org = repo.split("/", 1)[0] if "/" in repo else repo
    org_block = custom.get(org) if isinstance(custom.get(org), dict) else {}
    repo_block = custom.get(repo) if isinstance(custom.get(repo), dict) else {}

    def _bool(key: str, default: bool) -> bool:
        if key in repo_block:
            return bool(repo_block[key])
        if key in org_block:
            return bool(org_block[key])
        return default

    def _int(key: str, default: int) -> int:
        raw = repo_block.get(key) if key in repo_block else org_block.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    min_nodes = _int("min_nodes", settings.knowledge_graph_min_nodes)
    min_coverage = _int("min_coverage_percent", settings.knowledge_graph_min_coverage_percent)
    return {
        "repository": repo or None,
        "organization": org or None,
        "min_nodes": min_nodes,
        "min_coverage_percent": min_coverage,
        "require_service_graph": _bool("require_service_graph", settings.knowledge_graph_require_service_graph),
        "require_repository_intel": _bool("require_repository_intel", settings.knowledge_graph_require_repository_intel),
        "node_types": sorted(NODE_TYPES),
        "relation_types": sorted(RELATION_TYPES),
        "summary": f"Knowledge graph policy: min {min_nodes} nodes, coverage ≥{min_coverage}%.",
    }

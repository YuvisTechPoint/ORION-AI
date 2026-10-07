"""Service catalog — compose service graph nodes into IDP-ready entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.cloud_target_registry import resolve_cloud_target
from app.utils.environment_registry import build_environment_registry
from app.utils.repository_intelligence import analyze_repository
from app.utils.service_catalog_registry import resolve_catalog_overrides
from app.utils.service_graph import build_service_graph


def _owners_for_service(ownership: dict[str, Any], service_name: str, source: str) -> list[str]:
    rules = ownership.get("rules") or []
    candidates = [source, f"**/{service_name}/**", f"services/{service_name}/**", service_name]
    owners: list[str] = []
    for pattern in candidates:
        for rule in rules:
            pat = str(rule.get("pattern") or "")
            if pat and (pat in pattern or service_name in pat or pattern.endswith(pat.lstrip("/"))):
                owners.extend(rule.get("owners") or [])
    default = ownership.get("default_owners") or []
    if not owners and default:
        owners = list(default)
    return list(dict.fromkeys(owners))[:5]


def _health_hint(node_type: str, repo_intel: dict[str, Any]) -> str | None:
    stack = (repo_intel.get("stack") or {}).get("frameworks") or []
    if any(f.get("name") == "fastapi" for f in stack):
        return "/health"
    if node_type in {"api", "service"}:
        return "/health"
    return None


def build_service_catalog(
    *,
    repo: str,
    repo_path: str | None = None,
    service_graph: dict[str, Any] | None = None,
    repository_intelligence: dict[str, Any] | None = None,
    cloud_intelligence: dict[str, Any] | None = None,
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    repo_intel = repository_intelligence or {}
    if repo_path and not repo_intel:
        repo_intel = analyze_repository(repo_path, repo=repo, changed_files=changed_files or [])

    graph = service_graph
    if not graph:
        hints = (repo_intel.get("dependency_hints") or {}).get("service_graph")
        if isinstance(hints, dict) and hints.get("nodes"):
            graph = hints
    if not graph and repo_path:
        graph = build_service_graph(repo_path, changed_files=changed_files or [])

    graph = graph or {}
    nodes = graph.get("nodes") or {}
    edges = graph.get("edges") or []
    ownership = repo_intel.get("ownership") or {}
    overrides = resolve_catalog_overrides(repo)
    override_services = overrides.get("services") or {}

    deps_by_target: dict[str, list[str]] = {}
    for edge in edges:
        deps_by_target.setdefault(str(edge.get("to")), []).append(str(edge.get("from")))

    services: list[dict[str, Any]] = []
    for name, meta in nodes.items():
        if not isinstance(meta, dict):
            continue
        node_type = str(meta.get("type") or "service")
        source = str(meta.get("source") or "")
        override = override_services.get(name) if isinstance(override_services.get(name), dict) else {}
        owners = override.get("owners") or _owners_for_service(ownership, name, source)
        entry: dict[str, Any] = {
            "id": name,
            "name": override.get("display_name") or name,
            "type": override.get("type") or node_type,
            "owner": owners[0] if owners else overrides.get("team"),
            "owners": owners,
            "tier": override.get("tier") or overrides.get("tier") or ("tier-1" if name == graph.get("root_service") else "tier-2"),
            "source": source,
            "dependencies": sorted(set(deps_by_target.get(name, []))),
            "dependents": sorted({e["from"] for e in edges if e.get("to") == name and e.get("from")}),
            "health_endpoint": override.get("health_endpoint") or _health_hint(node_type, repo_intel),
            "links": {
                **(overrides.get("links") or {}),
                **(override.get("links") or {}),
            },
        }
        if override.get("description"):
            entry["description"] = override["description"]
        services.append(entry)

    services.sort(key=lambda s: (s.get("tier") or "", s.get("name") or ""))

    cloud_target = None
    if cloud_intelligence:
        cloud_target = (cloud_intelligence.get("cloud_target") or {}).get("primary_target")
    elif repo_path:
        cloud_target = resolve_cloud_target(repo_path=repo_path, repo=repo).get("primary_target")

    envs = build_environment_registry()
    environment_names = [e.get("name") for e in envs.get("environments") or [] if e.get("name")]

    completeness_issues: list[str] = []
    for svc in services:
        if not svc.get("owner"):
            completeness_issues.append(f"{svc['name']}: missing owner")
        if svc.get("type") in {"service", "api", "k8s_workload"} and not svc.get("health_endpoint"):
            completeness_issues.append(f"{svc['name']}: missing health endpoint hint")

    complete = max(0, 100 - len(completeness_issues) * 8)
    return {
        "repository": repo,
        "root_service": graph.get("root_service"),
        "services": services,
        "service_count": len(services),
        "edge_count": graph.get("edge_count", len(edges)),
        "cloud_target": cloud_target,
        "environments": environment_names,
        "ownership": {
            "codeowners_found": ownership.get("codeowners_found"),
            "unowned_changed_paths": ownership.get("unowned_changed_paths") or [],
        },
        "catalog_completeness_percent": min(complete, 100),
        "completeness_issues": completeness_issues[:15],
        "monorepo": (repo_intel.get("monorepo") or {}).get("detected", False),
        "summary": (
            f"Catalog: {len(services)} service(s) for {repo or 'repository'}; "
            f"completeness {min(complete, 100)}%."
        ),
    }


def merge_fleet_catalogs(repo_catalogs: list[dict[str, Any]]) -> dict[str, Any]:
    by_repo = {c.get("repository"): c for c in repo_catalogs if c.get("repository")}
    all_services: list[dict[str, Any]] = []
    for repo, catalog in by_repo.items():
        for svc in catalog.get("services") or []:
            all_services.append({**svc, "repository": repo})
    tiers = sorted({s.get("tier") for s in all_services if s.get("tier")})
    return {
        "repositories": list(by_repo.values()),
        "repository_count": len(by_repo),
        "services": all_services,
        "service_count": len(all_services),
        "tiers": tiers,
        "summary": f"Fleet catalog: {len(all_services)} service(s) across {len(by_repo)} repo(s).",
    }

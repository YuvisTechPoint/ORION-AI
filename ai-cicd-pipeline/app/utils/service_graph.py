"""Lightweight service dependency graph from repo structure and IaC hints."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_COMPOSE_SERVICE_RE = re.compile(r"^\s{2,4}([a-zA-Z0-9_-]+):\s*$")
_COMPOSE_DEPENDS_RE = re.compile(r"depends_on:\s*\n((?:\s+-\s+\w+\n)+)", re.MULTILINE)
_K8S_NAME_RE = re.compile(r"^\s*name:\s*(.+)$", re.MULTILINE)
_IMPORT_RE = re.compile(r"^(?:from|import)\s+([\w.]+)", re.MULTILINE)
_OPENAPI_TITLE_RE = re.compile(r'"title"\s*:\s*"([^"]+)"')


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _guess_service_name(repo_path: Path) -> str:
    compose = repo_path / "docker-compose.yml"
    if compose.is_file():
        for line in _read_text(compose, 5000).splitlines():
            m = _COMPOSE_SERVICE_RE.match(line)
            if m and m.group(1) not in {"version", "services", "volumes", "networks"}:
                return m.group(1)
    return repo_path.name.replace("_", "-")


def build_service_graph(repo_path: str, *, changed_files: list[str] | None = None) -> dict[str, Any]:
    """Build a heuristic ORION service graph from compose, K8s, OpenAPI, and Python imports."""
    root = Path(repo_path)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    root_service = _guess_service_name(root)
    nodes[root_service] = {"type": "service", "source": "repository"}

    # Docker Compose services
    for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
        compose = root / compose_name
        if not compose.is_file():
            continue
        text = _read_text(compose)
        services = [m.group(1) for m in _COMPOSE_SERVICE_RE.finditer(text)]
        services = [s for s in services if s not in {"version", "services", "volumes", "networks"}]
        for svc in services:
            nodes.setdefault(svc, {"type": "service", "source": compose_name})
            if svc != root_service:
                edges.append({"from": root_service, "to": svc, "kind": "compose"})
        for block in _COMPOSE_DEPENDS_RE.finditer(text):
            deps = re.findall(r"-\s+(\w+)", block.group(1))
            for dep in deps:
                edges.append({"from": "unknown", "to": dep, "kind": "depends_on"})

    # Kubernetes manifests
    for yaml_path in list(root.glob("**/*.yaml")) + list(root.glob("**/*.yml")):
        rel = yaml_path.relative_to(root).as_posix()
        if "test" in rel.lower() or yaml_path.name.startswith("."):
            continue
        if not any(k in rel.lower() for k in ("k8s", "kubernetes", "deploy", "manifest")):
            if yaml_path.name not in ("deployment.yaml", "service.yaml", "ingress.yaml"):
                continue
        text = _read_text(yaml_path, 8000)
        if "apiVersion:" not in text:
            continue
        name_match = _K8S_NAME_RE.search(text)
        k8s_name = name_match.group(1).strip() if name_match else yaml_path.stem
        nodes.setdefault(k8s_name, {"type": "k8s_workload", "source": rel})
        edges.append({"from": root_service, "to": k8s_name, "kind": "k8s"})

    # OpenAPI / FastAPI hints
    for spec in root.glob("**/openapi*.json"):
        text = _read_text(spec, 4000)
        try:
            data = json.loads(text)
            title = str(data.get("info", {}).get("title") or "")
        except json.JSONDecodeError:
            title = _OPENAPI_TITLE_RE.search(text)
            title = title.group(1) if title else spec.stem
        api_name = title or spec.stem
        nodes.setdefault(api_name, {"type": "api", "source": spec.relative_to(root).as_posix()})
        edges.append({"from": root_service, "to": api_name, "kind": "openapi"})

    # Data stores from compose / env hints
    for store, pattern in (
        ("postgresql", re.compile(r"postgres|5432", re.I)),
        ("redis", re.compile(r"redis|6379", re.I)),
    ):
        compose_text = _read_text(root / "docker-compose.yml")
        if pattern.search(compose_text):
            nodes.setdefault(store, {"type": "database", "source": "compose"})
            edges.append({"from": root_service, "to": store, "kind": "datastore"})

    affected: list[str] = []
    if changed_files:
        for path in changed_files:
            norm = path.replace("\\", "/")
            for name, meta in nodes.items():
                if name in norm or meta.get("source", "") in norm:
                    affected.append(name)
        affected = sorted(set(affected))

    node_count = len(nodes)
    edge_count = len(edges)
    changed_part = f"; touched {', '.join(affected[:4])}" if affected else ""
    if len(affected) > 4:
        changed_part += f" +{len(affected) - 4} more"
    return {
        "root_service": root_service,
        "nodes": nodes,
        "edges": edges,
        "node_count": node_count,
        "edge_count": edge_count,
        "changed_services": affected,
        "downstream_hint": sorted({e["to"] for e in edges if e["from"] in affected or e["from"] == root_service})[:20],
        "summary": f"{node_count} service(s), {edge_count} link(s) from {root_service}{changed_part}.",
    }

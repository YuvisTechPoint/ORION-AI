"""SBOM generation (CycloneDX-compatible subset) from repository manifests."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.utils.external_scanners import run_syft

_REQ_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?)\s*(?:==|>=|<=|~=|!=)\s*([^\s;]+)")
_PKG_JSON_DEP = re.compile(r'"([^"]+)"\s*:\s*"([^"]+)"')


def _components_from_requirements(path: Path) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    if not path.is_file():
        return components
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _REQ_LINE.match(line)
        if m:
            name, version = m.group(1), m.group(2)
        else:
            parts = re.split(r"[=<>!~]", line, maxsplit=1)
            name = parts[0].strip()
            version = parts[1].strip() if len(parts) > 1 else "unknown"
        components.append(
            {
                "type": "library",
                "name": name.split("[", 1)[0],
                "version": version,
                "purl": f"pkg:pypi/{name.split('[')[0]}@{version}",
                "scope": "required",
            }
        )
    return components


def _components_from_package_json(path: Path) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    if not path.is_file():
        return components
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return components
    for section in ("dependencies", "devDependencies"):
        deps = data.get(section) or {}
        if not isinstance(deps, dict):
            continue
        for name, version in deps.items():
            components.append(
                {
                    "type": "library",
                    "name": name,
                    "version": str(version).lstrip("^~"),
                    "purl": f"pkg:npm/{name}@{version}",
                    "scope": "required" if section == "dependencies" else "development",
                }
            )
    return components


def generate_sbom(repo_path: str, *, commit: str = "", repo: str = "") -> dict[str, Any]:
    root = Path(repo_path)
    components: list[dict[str, Any]] = []
    sources: list[str] = []

    req = root / "requirements.txt"
    if req.is_file():
        components.extend(_components_from_requirements(req))
        sources.append("requirements.txt")

    pkg = root / "package.json"
    if pkg.is_file():
        components.extend(_components_from_package_json(pkg))
        sources.append("package.json")

    syft_result = run_syft(repo_path)
    syft_scanner: dict[str, Any] | None = None
    if isinstance(syft_result, dict) and syft_result.get("status") == "ok":
        syft_components = syft_result.get("components") or []
        seen = {(c.get("name"), c.get("version")) for c in components}
        for comp in syft_components:
            if not isinstance(comp, dict):
                continue
            key = (comp.get("name"), comp.get("version"))
            if key in seen:
                continue
            components.append(comp)
            seen.add(key)
        sources.append("syft")
        syft_scanner = {
            "tool": "syft",
            "status": "completed",
            "component_count": syft_result.get("component_count"),
        }
    elif isinstance(syft_result, dict):
        syft_scanner = syft_result

    count = len(components)
    src_label = ", ".join(sources) if sources else "dependency manifests"
    stats = {
        "component_count": count,
        "sources": sources,
        "formats_supported": ["CycloneDX", "SPDX-export-ready"],
    }
    if syft_scanner:
        stats["scanners"] = {"syft": syft_scanner}
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "name": repo or root.name,
                "version": commit[:12] if commit else "unknown",
            },
            "tools": [{"name": "orion-sbom", "version": "1.0.0"}],
        },
        "components": components[:500],
        "stats": stats,
        "summary": f"CycloneDX SBOM: {count} component(s) from {src_label}.",
    }

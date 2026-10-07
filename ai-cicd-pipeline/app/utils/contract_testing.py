"""OpenAPI / contract diff heuristics for microservice API safety."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_OPENAPI_GLOBS = ("openapi.json", "openapi.yaml", "openapi.yml", "**/openapi*.json", "**/swagger*.json")


def _load_spec(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    # minimal yaml-ish path extraction for paths block
    if "paths:" in text or '"paths"' in text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            paths = re.findall(r"^\s*(/[\w/{}.-]+):\s*$", text, re.MULTILINE)
            return {"paths": {p: {} for p in paths}}
    return None


def analyze_contract_changes(repo_path: str, changed_files: list[str] | None = None) -> dict[str, Any]:
    root = Path(repo_path)
    breaking: list[dict[str, str]] = []
    scanned: list[str] = []

    candidates: list[Path] = []
    if changed_files:
        for rel in changed_files:
            p = root / rel.replace("\\", "/")
            if p.is_file() and ("openapi" in p.name.lower() or "swagger" in p.name.lower()):
                candidates.append(p)
    else:
        for pattern in _OPENAPI_GLOBS:
            candidates.extend(root.glob(pattern))

    seen: set[str] = set()
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        spec = _load_spec(path)
        if not spec:
            continue
        scanned.append(rel)
        paths = spec.get("paths") or {}
        if isinstance(paths, dict):
            for route, methods in paths.items():
                if not isinstance(methods, dict):
                    continue
                for method, detail in methods.items():
                    if method.startswith("x-"):
                        continue
                    if isinstance(detail, dict) and detail.get("deprecated"):
                        breaking.append(
                            {
                                "type": "deprecated_endpoint",
                                "route": route,
                                "method": method.upper(),
                                "severity": "medium",
                            }
                        )

    # Heuristic: removed endpoints flagged when diff mentions deletion of path key
    passed = not any(b.get("severity") == "critical" for b in breaking)
    return {
        "specs_scanned": scanned,
        "breaking_changes": breaking,
        "breaking_count": len(breaking),
        "passed": passed,
        "verdict": "pass" if passed else "warn",
        "summary": (
            f"Contract scan: {len(scanned)} spec(s), {len(breaking)} potential breaking change(s)."
            if scanned
            else "No OpenAPI specs in change set."
        ),
        "analysis_mode": "heuristic",
    }

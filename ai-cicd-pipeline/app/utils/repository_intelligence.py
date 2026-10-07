"""Repository fingerprinting, stack detection, monorepo, ownership, and license heuristics."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.utils.change_risk import analyze_changed_paths, compute_change_risk
from app.utils.sbom import generate_sbom
from app.utils.service_graph import build_service_graph
from app.utils.text_analysis import diff_stats, files_in_diff

_MANIFEST_MARKERS: list[tuple[str, str, str]] = [
    ("requirements.txt", "python", "manifest"),
    ("pyproject.toml", "python", "manifest"),
    ("setup.py", "python", "manifest"),
    ("Pipfile", "python", "manifest"),
    ("package.json", "javascript", "manifest"),
    ("pnpm-lock.yaml", "javascript", "lockfile"),
    ("yarn.lock", "javascript", "lockfile"),
    ("go.mod", "go", "manifest"),
    ("Cargo.toml", "rust", "manifest"),
    ("pom.xml", "java", "manifest"),
    ("build.gradle", "java", "manifest"),
    ("Gemfile", "ruby", "manifest"),
    ("composer.json", "php", "manifest"),
    ("Dockerfile", "docker", "container"),
    ("docker-compose.yml", "docker", "compose"),
    ("docker-compose.yaml", "docker", "compose"),
]

_MONOREPO_MARKERS = (
    "pnpm-workspace.yaml",
    "lerna.json",
    "nx.json",
    "turbo.json",
    "rush.json",
)

_FRAMEWORK_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bfastapi\b", re.I), "fastapi", "python"),
    (re.compile(r"\bflask\b", re.I), "flask", "python"),
    (re.compile(r"\bdjango\b", re.I), "django", "python"),
    (re.compile(r"\bcelery\b", re.I), "celery", "python"),
    (re.compile(r"\breact\b", re.I), "react", "javascript"),
    (re.compile(r"\bnext\b", re.I), "nextjs", "javascript"),
    (re.compile(r"\bvue\b", re.I), "vue", "javascript"),
    (re.compile(r"\bexpress\b", re.I), "express", "javascript"),
    (re.compile(r"\bnestjs\b", re.I), "nestjs", "javascript"),
]

_CI_MARKERS = {
    ".github/workflows": "github_actions",
    ".gitlab-ci.yml": "gitlab_ci",
    "azure-pipelines.yml": "azure_pipelines",
    "Jenkinsfile": "jenkins",
    "bitbucket-pipelines.yml": "bitbucket_pipelines",
}

_OPENAPI_NAMES = ("openapi.json", "openapi.yaml", "openapi.yml", "swagger.json", "swagger.yaml")
_REMOVED_API_PATH_RE = re.compile(r'^-\s*["\']?(/[\w/{}\-\.]+)["\']?\s*[,:]?\s*$')

_SPDX_RE = re.compile(
    r"\b(MIT|Apache-2\.0|BSD-2-Clause|BSD-3-Clause|ISC|GPL-2\.0|GPL-3\.0|LGPL-2\.1|LGPL-3\.0|MPL-2\.0)\b",
    re.I,
)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _read_text(path: Path, limit: int = 8192) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _detect_manifests(root: Path) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for name, language, kind in _MANIFEST_MARKERS:
        path = root / name
        if path.is_file():
            found.append({"path": name, "language": language, "kind": kind})
    for rel, ci in _CI_MARKERS.items():
        target = root / rel
        if target.exists():
            found.append({"path": rel, "language": "ci", "kind": ci})
    return found


def _detect_languages(manifests: list[dict[str, str]]) -> list[dict[str, Any]]:
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    for item in manifests:
        lang = item.get("language") or ""
        if lang in {"", "ci", "docker"}:
            continue
        scores[lang] = scores.get(lang, 0) + 2
        evidence.setdefault(lang, []).append(item["path"])
    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    out: list[dict[str, Any]] = []
    for lang, score in ranked:
        conf = "high" if score >= 4 else "medium" if score >= 2 else "low"
        out.append({"name": lang, "confidence": conf, "evidence": evidence.get(lang, [])})
    return out


def _detect_frameworks(root: Path) -> list[dict[str, Any]]:
    blobs: list[str] = []
    for name in ("requirements.txt", "pyproject.toml", "package.json"):
        blobs.append(_read_text(root / name))
    text = "\n".join(blobs)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern, name, stack in _FRAMEWORK_HINTS:
        if pattern.search(text) and name not in seen:
            seen.add(name)
            found.append({"name": name, "stack": stack, "evidence": [f"dependency hint in manifests"]})
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(_read_text(pkg, 65536))
        except json.JSONDecodeError:
            data = {}
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        for dep in ("next", "react", "vue", "express", "@nestjs/core"):
            if dep in deps:
                key = dep.replace("@nestjs/", "nestjs")
                if key not in seen:
                    seen.add(key)
                    found.append({"name": key, "stack": "javascript", "evidence": [f"package.json → {dep}"]})
    return found


def _detect_monorepo(root: Path) -> dict[str, Any]:
    marker = next((m for m in _MONOREPO_MARKERS if (root / m).is_file()), None)
    packages: list[dict[str, str]] = []
    for pattern in ("package.json", "pyproject.toml", "go.mod"):
        for path in root.rglob(pattern):
            rel = _rel(root, path)
            if rel.count("/") >= 1 and not rel.startswith(".") and "node_modules" not in rel:
                packages.append({"path": str(path.parent.relative_to(root).as_posix()), "manifest": pattern})
            if len(packages) >= 20:
                break
    detected = bool(marker) or len(packages) >= 2
    kind = None
    if marker:
        kind = marker.replace(".yaml", "").replace(".json", "")
    elif len(packages) >= 2:
        kind = "multi-package"
    return {
        "detected": detected,
        "kind": kind,
        "workspace_marker": marker,
        "packages": packages[:12],
        "package_count": len(packages),
    }


def _parse_codeowners(root: Path) -> dict[str, Any]:
    for rel in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        path = root / rel
        if not path.is_file():
            continue
        rules: list[dict[str, Any]] = []
        for line in _read_text(path, 65536).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            rules.append({"pattern": parts[0], "owners": parts[1:]})
        owners = sorted({o for r in rules for o in r["owners"]})
        return {
            "codeowners_found": True,
            "path": rel,
            "rules_count": len(rules),
            "owners": owners[:12],
            "rules": rules[:20],
        }
    return {"codeowners_found": False, "rules_count": 0, "owners": [], "rules": []}


def _owners_for_path(rules: list[dict[str, Any]], file_path: str) -> list[str]:
    matched: list[str] = []
    normalized = file_path.replace("\\", "/").lstrip("/")
    for rule in rules:
        pattern = str(rule.get("pattern") or "")
        if pattern.endswith("/"):
            if normalized.startswith(pattern.rstrip("/")):
                matched.extend(rule.get("owners") or [])
        elif pattern.startswith("*"):
            suffix = pattern.lstrip("*")
            if normalized.endswith(suffix):
                matched.extend(rule.get("owners") or [])
        elif normalized == pattern or normalized.endswith("/" + pattern):
            matched.extend(rule.get("owners") or [])
    return list(dict.fromkeys(matched))


def _scan_licenses(root: Path) -> dict[str, Any]:
    licenses: list[dict[str, str]] = []
    issues: list[str] = []
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        path = root / name
        if path.is_file():
            text = _read_text(path, 4096)
            match = _SPDX_RE.search(text)
            spdx = match.group(1) if match else "unknown"
            licenses.append({"source": name, "spdx": spdx})
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(_read_text(pkg, 65536))
        except json.JSONDecodeError:
            data = {}
        lic = data.get("license")
        if isinstance(lic, str) and lic.strip():
            licenses.append({"source": "package.json", "spdx": lic.strip()})
        elif isinstance(lic, dict) and lic.get("type"):
            licenses.append({"source": "package.json", "spdx": str(lic["type"])})
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = _read_text(pyproject, 65536)
        m = re.search(r'^\s*license\s*=\s*["\']([^"\']+)["\']', text, re.M)
        if m:
            licenses.append({"source": "pyproject.toml", "spdx": m.group(1)})
    primary = licenses[0]["spdx"] if licenses else None
    if not licenses:
        issues.append("No LICENSE file or manifest license field detected")
    copyleft = {l["spdx"].upper() for l in licenses if "GPL" in l["spdx"].upper()}
    if copyleft:
        issues.append(f"Copyleft license detected: {', '.join(sorted(copyleft))}")
    return {"primary": primary, "entries": licenses, "issues": issues}


def _find_openapi_files(root: Path) -> list[str]:
    found: list[str] = []
    for name in _OPENAPI_NAMES:
        if (root / name).is_file():
            found.append(name)
    for path in root.rglob("openapi*.y*ml"):
        rel = _rel(root, path)
        if "node_modules" not in rel and rel not in found:
            found.append(rel)
        if len(found) >= 8:
            break
    return found


def _breaking_change_hints(diff_text: str, changed_files: list[str]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    openapi_touched = any(
        f.endswith((".json", ".yaml", ".yml")) and ("openapi" in f.lower() or "swagger" in f.lower())
        for f in changed_files
    )
    if not openapi_touched or not diff_text:
        return hints
    for line in diff_text.splitlines():
        m = _REMOVED_API_PATH_RE.match(line.strip())
        if m:
            hints.append({"kind": "removed_path", "path": m.group(1), "detail": "OpenAPI path removed in diff"})
    for line in diff_text.splitlines():
        if line.startswith("-") and "deprecated" in line.lower():
            hints.append({"kind": "deprecation", "path": "", "detail": line.strip()[:120]})
    return hints[:20]


def _repo_fingerprint(root: Path, manifests: list[dict[str, str]]) -> dict[str, Any]:
    hasher = hashlib.sha256()
    tracked: list[str] = []
    for item in sorted(manifests, key=lambda x: x["path"]):
        path = root / item["path"]
        if not path.is_file():
            continue
        rel = item["path"]
        tracked.append(rel)
        hasher.update(rel.encode("utf-8"))
        hasher.update(_read_text(path, 4096).encode("utf-8"))
    return {"sha256": hasher.hexdigest()[:32], "manifests": tracked}


def _build_summary(report: dict[str, Any]) -> str:
    langs = ", ".join(l["name"] for l in (report.get("stack") or {}).get("languages") or []) or "unknown"
    mono = "monorepo" if (report.get("monorepo") or {}).get("detected") else "single-package"
    lic = (report.get("licenses") or {}).get("primary") or "unknown license"
    nodes = ((report.get("dependency_hints") or {}).get("service_graph") or {}).get("node_count", 0)
    risk = (report.get("change_impact") or {}).get("risk_level")
    parts = [f"{mono} repo", f"languages: {langs}", f"license: {lic}"]
    if nodes:
        parts.append(f"{nodes} service node(s)")
    if risk:
        parts.append(f"change risk: {risk}")
    return "; ".join(parts) + "."


def analyze_repository(
    repo_path: str,
    *,
    repo: str = "",
    commit: str = "",
    changed_files: list[str] | None = None,
    diff_text: str = "",
) -> dict[str, Any]:
    """Deterministic repository intelligence report."""
    root = Path(repo_path)
    if not root.is_dir():
        return {"error": f"repo_path not found: {repo_path}", "analysis_mode": "heuristic"}

    manifests = _detect_manifests(root)
    languages = _detect_languages(manifests)
    frameworks = _detect_frameworks(root)
    monorepo = _detect_monorepo(root)
    ownership = _parse_codeowners(root)
    licenses = _scan_licenses(root)
    openapi_files = _find_openapi_files(root)
    fingerprint = _repo_fingerprint(root, manifests)

    files = changed_files or (files_in_diff(diff_text) if diff_text else [])
    unowned: list[str] = []
    if files and ownership.get("rules"):
        for path in files[:40]:
            if not _owners_for_path(ownership["rules"], path):
                unowned.append(path)
    ownership["unowned_changed_paths"] = unowned[:20]

    breaking = _breaking_change_hints(diff_text, files)
    api_surface = {"openapi_files": openapi_files, "breaking_change_hints": breaking}

    graph = build_service_graph(repo_path, changed_files=files)
    sbom = generate_sbom(repo_path, commit=commit, repo=repo)
    dependency_hints = {
        "service_graph": {
            "node_count": graph.get("node_count"),
            "edge_count": graph.get("edge_count"),
            "changed_services": graph.get("changed_services") or [],
        },
        "sbom": {
            "component_count": (sbom.get("stats") or {}).get("component_count"),
            "sources": (sbom.get("stats") or {}).get("sources") or [],
        },
    }

    change_impact: dict[str, Any] = {}
    if files or diff_text:
        path_analysis = analyze_changed_paths(files)
        change_impact = {
            "path_analysis": path_analysis,
            "diff_stats": diff_stats(diff_text) if diff_text else {},
        }
        if diff_text:
            risk = compute_change_risk(diff_text=diff_text, changed_files=files)
            change_impact["risk_level"] = risk.get("risk_level")
            change_impact["final_risk"] = risk.get("final_risk")

    ci_systems = sorted({m["kind"] for m in manifests if m.get("language") == "ci"})

    report: dict[str, Any] = {
        "repo": repo or root.name,
        "commit": commit,
        "analysis_mode": "heuristic",
        "fingerprint": fingerprint,
        "stack": {
            "languages": languages,
            "frameworks": frameworks,
            "manifests": manifests,
            "ci_systems": ci_systems,
        },
        "monorepo": monorepo,
        "ownership": ownership,
        "licenses": licenses,
        "api_surface": api_surface,
        "dependency_hints": dependency_hints,
        "change_impact": change_impact,
    }
    report["summary"] = _build_summary(report)
    return report

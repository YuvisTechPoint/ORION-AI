"""Container image / Dockerfile security — Trivy when installed, heuristics otherwise."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.utils.external_scanners import run_trivy_config

_DOCKERFILE_NAMES = ("Dockerfile", "dockerfile", "Dockerfile.prod", "Dockerfile.dev")


def _heuristic_container_scan(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path)
    findings: list[dict[str, Any]] = []
    dockerfiles: list[str] = []

    for name in _DOCKERFILE_NAMES:
        path = root / name
        if path.is_file():
            dockerfiles.append(name)
            findings.extend(_scan_dockerfile(path, name))

    for path in root.glob("**/Dockerfile*"):
        rel = path.relative_to(root).as_posix()
        if rel not in dockerfiles:
            dockerfiles.append(rel)
            findings.extend(_scan_dockerfile(path, rel))

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")

    return {
        "dockerfiles_scanned": dockerfiles,
        "finding_count": len(findings),
        "critical_count": critical,
        "high_count": high,
        "passed": critical == 0,
        "findings": findings[:50],
        "summary": (
            f"Scanned {len(dockerfiles)} Dockerfile(s); {len(findings)} findings ({critical} critical)."
            if dockerfiles
            else "No Dockerfile found — container scan skipped."
        ),
        "analysis_mode": "heuristic",
        "scanner": "heuristic",
    }


def scan_container_security(repo_path: str) -> dict[str, Any]:
    external = run_trivy_config(repo_path)
    if isinstance(external, dict) and external.get("analysis_mode") == "trivy":
        return external
    report = _heuristic_container_scan(repo_path)
    if isinstance(external, dict):
        report["external_scanner"] = external
        if external.get("status") == "skipped":
            report["tools_recommended"] = ["trivy"]
    return report


def _scan_dockerfile(path: Path, rel: str) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    findings: list[dict[str, Any]] = []
    has_user = any(line.strip().upper().startswith("USER ") and "root" not in line.lower() for line in lines)

    for idx, line in enumerate(lines, start=1):
        upper = line.upper()
        if upper.strip().startswith("FROM ") and ":latest" in line.lower():
            findings.append(
                {
                    "rule": "unpinned_base_tag",
                    "severity": "medium",
                    "file": rel,
                    "line": idx,
                    "description": "Base image uses :latest tag",
                    "recommendation": "Pin base image to a digest or specific version tag.",
                }
            )
        if " --privileged" in line or upper.strip().startswith("PRIVILEGED"):
            findings.append(
                {
                    "rule": "privileged_container",
                    "severity": "critical",
                    "file": rel,
                    "line": idx,
                    "description": "Privileged container flag detected",
                    "recommendation": "Remove privileged mode unless strictly required.",
                }
            )
        if re.search(r"(?i)(aws_secret|password|api_key)\s*=", line):
            findings.append(
                {
                    "rule": "build_arg_secret",
                    "severity": "high",
                    "file": rel,
                    "line": idx,
                    "description": "Possible secret in Dockerfile instruction",
                    "recommendation": "Use build secrets or runtime env injection, not Dockerfile literals.",
                }
            )

    if lines and not has_user:
        findings.append(
            {
                "rule": "root_user",
                "severity": "high",
                "file": rel,
                "line": len(lines),
                "description": "No non-root USER directive found",
                "recommendation": "Add USER directive with non-root UID.",
            }
        )
    return findings

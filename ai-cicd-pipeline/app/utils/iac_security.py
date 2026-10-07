"""IaC security — Checkov when installed, heuristics otherwise."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.utils.external_scanners import run_checkov

_IAC_GLOBS = ("**/*.tf", "**/*.yaml", "**/*.yml", "**/docker-compose*.yml", "**/docker-compose*.yaml")
_RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    ("public_s3_acl", re.compile(r'acl\s*=\s*"public-read"', re.I), "critical", "Block public S3 ACL; use private buckets with IAM policies."),
    ("open_security_group", re.compile(r"0\.0\.0\.0/0"), "critical", "Restrict ingress to known CIDR ranges."),
    ("privileged_pod", re.compile(r"privileged:\s*true", re.I), "critical", "Disable privileged containers in Kubernetes."),
    ("public_database", re.compile(r"(?i)(publicly_accessible\s*=\s*true|rds.*0\.0\.0\.0/0)"), "critical", "Do not expose databases to the public internet."),
    ("missing_encryption", re.compile(r"(?i)(storage_encrypted\s*=\s*false|encrypt\s*:\s*false)"), "high", "Enable encryption at rest."),
    ("hardcoded_password", re.compile(r"(?i)(password\s*[:=]\s*['\"][^'\"]{4,}['\"])"), "high", "Use secrets manager or sealed secrets, not literals."),
    ("missing_resource_limits", re.compile(r"kind:\s*Deployment"), "medium", "Ensure containers define requests/limits (kube-score recommendation)."),
]


def _heuristic_iac_scan(repo_path: str, *, changed_files: list[str] | None = None) -> dict[str, Any]:
    root = Path(repo_path)
    findings: list[dict[str, Any]] = []
    scanned: list[str] = []

    paths: list[Path] = []
    if changed_files:
        for rel in changed_files:
            p = root / rel.replace("\\", "/")
            if p.is_file() and _is_iac_file(p):
                paths.append(p)
    else:
        for pattern in _IAC_GLOBS:
            paths.extend(root.glob(pattern))

    seen: set[str] = set()
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        if any(x in rel for x in (".git", "node_modules", "test")):
            continue
        scanned.append(rel)
        text = path.read_text(encoding="utf-8", errors="replace")[:150_000]
        for rule_id, pattern, severity, recommendation in _RULES:
            if rule_id == "missing_resource_limits":
                if "resources:" not in text and "kind: Deployment" in text:
                    findings.append(
                        {
                            "rule": rule_id,
                            "severity": severity,
                            "file": rel,
                            "description": "Deployment without resource limits detected",
                            "recommendation": recommendation,
                        }
                    )
                continue
            if pattern.search(text):
                findings.append(
                    {
                        "rule": rule_id,
                        "severity": severity,
                        "file": rel,
                        "description": f"IaC policy violation: {rule_id.replace('_', ' ')}",
                        "recommendation": recommendation,
                    }
                )

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    return {
        "files_scanned": len(scanned),
        "finding_count": len(findings),
        "critical_count": critical,
        "passed": critical == 0,
        "findings": findings[:50],
        "tools_recommended": ["checkov", "tfsec", "kube-score", "trivy", "conftest"],
        "summary": f"Scanned {len(scanned)} IaC file(s); {len(findings)} findings ({critical} critical).",
        "analysis_mode": "heuristic",
        "scanner": "heuristic",
    }


def scan_iac_security(repo_path: str, *, changed_files: list[str] | None = None) -> dict[str, Any]:
    external = run_checkov(repo_path)
    if isinstance(external, dict) and external.get("analysis_mode") == "checkov":
        return external
    report = _heuristic_iac_scan(repo_path, changed_files=changed_files)
    if isinstance(external, dict):
        report["external_scanner"] = external
        if external.get("status") == "skipped":
            report["tools_recommended"] = ["checkov", "tfsec", "kube-score", "trivy", "conftest"]
    return report


def _is_iac_file(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".tf"):
        return True
    if "docker-compose" in name or name.endswith((".yaml", ".yml")):
        return True
    return False

"""Supply chain report — lockfiles, unpinned deps, CVE signals, scanner posture."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.agents.security_agent import split_requirements
from app.utils.epss import enrich_cve_references

_LOCKFILES = (
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "go.sum",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
)


def _file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes()[:65536])
    return digest.hexdigest()[:16]


def build_supply_chain_report(
    repo_path: str,
    *,
    sbom: dict[str, Any] | None = None,
    secrets_scan: dict[str, Any] | None = None,
    container_scan: dict[str, Any] | None = None,
    iac_scan: dict[str, Any] | None = None,
    security_scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_path)
    lockfiles: list[dict[str, str]] = []
    for name in _LOCKFILES:
        path = root / name
        if path.is_file():
            lockfiles.append({"path": name, "fingerprint": _file_fingerprint(path)})

    unpinned: list[str] = []
    req = root / "requirements.txt"
    if req.is_file():
        _, unpinned = split_requirements(req.read_text(encoding="utf-8", errors="replace"))

    cve_findings: list[dict[str, Any]] = []
    if security_scan:
        for vuln in security_scan.get("vulnerabilities") or []:
            cve = vuln.get("cve")
            if cve:
                cve_findings.append(
                    {
                        "cve": cve,
                        "severity": vuln.get("severity"),
                        "package": vuln.get("type"),
                        "file": vuln.get("file"),
                    }
                )

    scanners = {
        "secrets": (secrets_scan or {}).get("scanner") or (secrets_scan or {}).get("analysis_mode"),
        "container": (container_scan or {}).get("scanner") or (container_scan or {}).get("analysis_mode"),
        "iac": (iac_scan or {}).get("scanner") or (iac_scan or {}).get("analysis_mode"),
        "dependencies": ((security_scan or {}).get("scanners") or {}).get("dependencies", {}).get("status"),
    }

    issues: list[str] = []
    if unpinned:
        issues.append(f"{len(unpinned)} unpinned requirement(s) in requirements.txt")
    if not lockfiles and (root / "package.json").is_file():
        issues.append("package.json present without lockfile")
    if (secrets_scan or {}).get("critical_count", 0):
        issues.append("critical secrets detected")
    if (container_scan or {}).get("critical_count", 0):
        issues.append("critical container misconfigurations")
    if (iac_scan or {}).get("critical_count", 0):
        issues.append("critical IaC policy failures")

    cve_enriched, epss_meta = enrich_cve_references(cve_findings[:30])
    if epss_meta.get("high_exploit_probability_count"):
        issues.append(
            f"{epss_meta['high_exploit_probability_count']} CVE(s) with EPSS >= 0.5 exploit probability"
        )

    component_count = int(((sbom or {}).get("stats") or {}).get("component_count") or 0)
    posture = "pass"
    if issues or cve_enriched:
        posture = "warn" if not any("critical" in i for i in issues) else "fail"

    summary = (
        f"Supply chain {posture}: {len(lockfiles)} lockfile(s), "
        f"{component_count} SBOM component(s), {len(cve_enriched)} CVE reference(s)."
    )
    if epss_meta.get("epss_enabled"):
        summary += f" EPSS source={epss_meta.get('epss_source')}."
    if issues:
        summary += f" Issues: {'; '.join(issues[:3])}."

    return {
        "posture": posture,
        "lockfiles": lockfiles,
        "unpinned_requirements": unpinned[:30],
        "sbom_component_count": component_count,
        "cve_references": cve_enriched,
        "scanner_posture": scanners,
        "issues": issues,
        "epss": epss_meta,
        "epss_enabled": bool(epss_meta.get("epss_enabled")),
        "summary": summary,
        "analysis_mode": "heuristic",
    }

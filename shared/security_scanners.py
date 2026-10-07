"""Deterministic SAST/SCA scanners for the canonical stack (bandit + pip-audit)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

_PINNED_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[^\]]*\])?\s*==\s*[^\s;,=]+\s*(;.*)?$")

_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}


def split_requirements(text: str) -> tuple[list[str], list[str]]:
    pinned: list[str] = []
    unpinned: list[str] = []
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-") or not _PINNED_RE.match(line):
            unpinned.append(line)
        else:
            pinned.append(line)
    return pinned, unpinned


def _bandit_severity(value: str) -> str:
    mapping = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    return mapping.get(str(value or "").upper(), "low")


def run_bandit(repo_path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["bandit", "-r", repo_path, "-f", "json", "-ll"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return [], {"tool": "bandit", "status": "failed", "reason": str(exc)}

    raw = proc.stdout or ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        tail = (proc.stderr or raw).strip()[-300:]
        return [], {"tool": "bandit", "status": "failed", "reason": tail}

    issues: list[dict[str, Any]] = []
    for item in data.get("results", []):
        rel = str(item.get("filename", ""))
        try:
            rel = str(Path(rel).resolve().relative_to(Path(repo_path).resolve())).replace("\\", "/")
        except ValueError:
            rel = rel.replace("\\", "/")
        issues.append(
            {
                "type": item.get("test_name") or item.get("test_id") or "bandit",
                "severity": _bandit_severity(str(item.get("issue_severity", "LOW"))),
                "line": str(item.get("line_number") or 0),
                "fix": f"Review bandit rule {item.get('test_id')} and remediate.",
                "snippet": str(item.get("issue_text") or "")[:200],
                "file_path": rel,
                "scanner": "bandit",
            }
        )
    return issues, {"tool": "bandit", "status": "ok", "findings": len(issues)}


def parse_pip_audit(raw: str) -> list[dict[str, Any]] | None:
    try:
        data = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("dependencies"), list):
        return None
    findings: list[dict[str, Any]] = []
    for dep in data["dependencies"]:
        seen: set[str] = set()
        for vuln in dep.get("vulns") or []:
            vid = str(vuln.get("id") or "")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            aliases = vuln.get("aliases") or []
            cve = next((a for a in aliases if str(a).startswith("CVE-")), vid)
            fixes = vuln.get("fix_versions") or []
            findings.append(
                {
                    "package": dep.get("name"),
                    "installed_version": dep.get("version"),
                    "vulnerability_id": cve,
                    "fix_versions": fixes,
                    "description": str(vuln.get("description") or "")[:200],
                }
            )
    return findings


def run_pip_audit(repo_path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    req_path = Path(repo_path) / "requirements.txt"
    if not req_path.is_file():
        return [], {"tool": "pip-audit", "status": "skipped", "reason": "no requirements.txt"}

    pinned, unpinned = split_requirements(req_path.read_text(encoding="utf-8", errors="replace"))
    status: dict[str, Any] = {"tool": "pip-audit", "audited": len(pinned), "not_audited": unpinned[:50]}
    if not pinned:
        return [], {**status, "status": "skipped", "reason": "no exactly pinned (==) requirements"}

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
        tmp.write("\n".join(pinned) + "\n")
        pinned_file = tmp.name

    try:
        proc = subprocess.run(
            [
                "pip-audit",
                "-r",
                pinned_file,
                "-f",
                "json",
                "--no-deps",
                "--disable-pip",
                "--progress-spinner",
                "off",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return [], {**status, "status": "failed", "reason": str(exc)}
    finally:
        Path(pinned_file).unlink(missing_ok=True)

    raw = proc.stdout or ""
    findings = parse_pip_audit(raw)
    if findings is None:
        tail = (proc.stderr or raw).strip()[-300:]
        return [], {**status, "status": "failed", "reason": tail}

    issues: list[dict[str, Any]] = []
    for item in findings:
        fixes = item.get("fix_versions") or []
        issues.append(
            {
                "type": "vulnerable_dependency",
                "severity": "high",
                "line": "0",
                "fix": (
                    f"Upgrade {item.get('package')} to {fixes[-1]} or later."
                    if fixes
                    else f"Upgrade {item.get('package')} to a patched version."
                ),
                "snippet": str(item.get("description") or ""),
                "file_path": "requirements.txt",
                "scanner": "pip-audit",
                "cve": item.get("vulnerability_id"),
            }
        )
    return issues, {**status, "status": "ok", "findings": len(issues)}


def run_security_scanners(repo_path: str) -> dict[str, Any]:
    bandit_issues, bandit_status = run_bandit(repo_path)
    pip_issues, pip_status = run_pip_audit(repo_path)
    issues = bandit_issues + pip_issues
    highest = "none"
    for issue in issues:
        sev = str(issue.get("severity", "low")).lower()
        if _SEVERITY_ORDER.get(sev, 0) > _SEVERITY_ORDER.get(highest, 0):
            highest = sev
    high_count = sum(1 for i in issues if i.get("severity") in {"high", "critical"})
    return {
        "issues": issues,
        "scanners": {"bandit": bandit_status, "dependencies": pip_status},
        "highest_severity": highest,
        "analysis_mode": "scanner",
        "summary": (
            f"Scanner pass: {len(issues)} finding(s) "
            f"({high_count} high/critical) from bandit and pip-audit."
            if issues
            else "Scanner pass: no bandit or pip-audit findings."
        ),
        "blocked": high_count > 0 or highest in {"high", "critical"},
    }


def bandit_available() -> bool:
    return shutil.which("bandit") is not None


def pip_audit_available() -> bool:
    return shutil.which("pip-audit") is not None

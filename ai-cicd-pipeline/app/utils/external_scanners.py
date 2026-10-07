"""External DevSecOps scanner runners — authoritative when installed, heuristic fallback otherwise."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.tools import tool_env

_SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _tool_path(name: str) -> str | None:
    override = {
        "gitleaks": settings.gitleaks_path,
        "trivy": settings.trivy_path,
        "checkov": settings.checkov_path,
        "semgrep": settings.semgrep_path,
        "syft": settings.syft_path,
        "zap": settings.zap_path,
    }.get(name, "")
    if override and override.strip():
        return override.strip()
    return shutil.which(name)


def _run_cmd(cmd: list[str], *, timeout: int = 180, cwd: str | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=tool_env(),
        timeout=timeout,
        cwd=cwd,
        check=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _scanner_status(tool: str, *, status: str, reason: str = "", findings: list | None = None) -> dict[str, Any]:
    return {
        "tool": tool,
        "status": status,
        "reason": reason,
        "finding_count": len(findings or []),
    }


def _gitleaks_severity(rule_id: str) -> str:
    rid = (rule_id or "").lower()
    if any(x in rid for x in ("private-key", "aws", "github", "anthropic", "stripe")):
        return "critical"
    if "generic" in rid or "api" in rid:
        return "high"
    return "medium"


def run_gitleaks(repo_path: str) -> dict[str, Any] | None:
    """Run gitleaks when enabled and on PATH. Returns normalized scan dict or None when disabled."""
    if not settings.security_gitleaks_enabled:
        return None
    binary = _tool_path("gitleaks")
    if not binary:
        return {
            "tool": "gitleaks",
            "status": "skipped",
            "reason": "gitleaks not installed",
            "analysis_mode": "heuristic",
        }
    cmd = [
        binary,
        "detect",
        "--source",
        repo_path,
        "--no-git",
        "--report-format",
        "json",
        "--report-path",
        "-",
        "--exit-code",
        "0",
    ]
    try:
        code, stdout, stderr = _run_cmd(cmd, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"tool": "gitleaks", "status": "failed", "reason": str(exc), "analysis_mode": "heuristic"}

    raw = stdout.strip()
    if not raw:
        if code != 0 and stderr.strip():
            return {"tool": "gitleaks", "status": "failed", "reason": stderr.strip()[:500], "analysis_mode": "heuristic"}
        findings: list[dict[str, Any]] = []
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "tool": "gitleaks",
                "status": "failed",
                "reason": f"invalid JSON (exit {code})",
                "analysis_mode": "heuristic",
            }
        rows = data if isinstance(data, list) else data.get("findings") or data.get("results") or []
        findings = []
        root = Path(repo_path)
        for row in rows:
            if not isinstance(row, dict):
                continue
            file_path = str(row.get("File") or row.get("file") or "")
            try:
                rel = Path(file_path).resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel = file_path.replace("\\", "/")
            rule_id = str(row.get("RuleID") or row.get("rule_id") or "gitleaks")
            severity = _gitleaks_severity(rule_id)
            findings.append(
                {
                    "type": rule_id,
                    "severity": severity,
                    "file": rel,
                    "line_hint": int(row.get("StartLine") or row.get("start_line") or 0),
                    "recommended_action": str(row.get("Description") or row.get("description") or "Rotate secret and purge from Git history."),
                    "remediation_steps": [
                        "Revoke or rotate the exposed credential",
                        "Remove secret from Git history",
                        "Store replacement in vault or CI secrets",
                    ],
                    "scanner": "gitleaks",
                }
            )

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    return {
        "finding_count": len(findings),
        "critical_count": critical,
        "passed": critical == 0,
        "findings": findings[:40],
        "files_scanned": None,
        "summary": (
            f"gitleaks: {len(findings)} secret(s) ({critical} critical)."
            if findings
            else "gitleaks: no secrets detected."
        ),
        "analysis_mode": "gitleaks",
        "scanner": "gitleaks",
        "external_scanner": _scanner_status("gitleaks", status="ok", findings=findings),
    }


def _normalize_trivy_severity(sev: str) -> str:
    mapping = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "UNKNOWN": "medium"}
    return mapping.get(str(sev or "").upper(), "medium")


def run_trivy_config(repo_path: str) -> dict[str, Any] | None:
    """Scan Dockerfiles / IaC misconfigs with trivy config."""
    if not settings.security_trivy_enabled:
        return None
    binary = _tool_path("trivy")
    if not binary:
        return {"tool": "trivy", "status": "skipped", "reason": "trivy not installed", "analysis_mode": "heuristic"}

    cmd = [binary, "config", "--format", "json", "--quiet", repo_path]
    try:
        code, stdout, stderr = _run_cmd(cmd, timeout=180)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"tool": "trivy", "status": "failed", "reason": str(exc), "analysis_mode": "heuristic"}

    if not stdout.strip():
        return {
            "tool": "trivy",
            "status": "failed",
            "reason": (stderr or f"no output (exit {code})")[:500],
            "analysis_mode": "heuristic",
        }
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {"tool": "trivy", "status": "failed", "reason": "invalid JSON", "analysis_mode": "heuristic"}

    findings: list[dict[str, Any]] = []
    root = Path(repo_path)
    for result in data.get("Results") or []:
        target = str(result.get("Target") or "")
        try:
            rel = Path(target).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = target.replace("\\", "/")
        for mis in result.get("Misconfigurations") or []:
            findings.append(
                {
                    "rule": mis.get("ID") or mis.get("Type") or "trivy-misconfig",
                    "severity": _normalize_trivy_severity(str(mis.get("Severity") or "MEDIUM")),
                    "file": rel,
                    "line": int((mis.get("CauseMetadata") or {}).get("StartLine") or 0),
                    "description": str(mis.get("Title") or mis.get("Description") or "Misconfiguration detected"),
                    "recommendation": str(mis.get("Resolution") or "Apply Trivy remediation guidance."),
                    "scanner": "trivy",
                }
            )

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    dockerfiles = sorted({f["file"] for f in findings if "dockerfile" in f["file"].lower() or f["file"].lower().startswith("dockerfile")})
    return {
        "dockerfiles_scanned": dockerfiles or [repo_path],
        "finding_count": len(findings),
        "critical_count": critical,
        "high_count": high,
        "passed": critical == 0,
        "findings": findings[:50],
        "summary": f"trivy config: {len(findings)} finding(s) ({critical} critical).",
        "analysis_mode": "trivy",
        "scanner": "trivy",
        "external_scanner": _scanner_status("trivy", status="ok", findings=findings),
    }


def run_checkov(repo_path: str) -> dict[str, Any] | None:
    if not settings.security_checkov_enabled:
        return None
    binary = _tool_path("checkov")
    if not binary:
        return {"tool": "checkov", "status": "skipped", "reason": "checkov not installed", "analysis_mode": "heuristic"}

    cmd = [
        binary,
        "-d",
        repo_path,
        "--framework",
        "terraform,kubernetes,dockerfile,cloudformation",
        "--output",
        "json",
        "--quiet",
        "--compact",
    ]
    try:
        code, stdout, stderr = _run_cmd(cmd, timeout=240)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"tool": "checkov", "status": "failed", "reason": str(exc), "analysis_mode": "heuristic"}

    if not stdout.strip():
        return {
            "tool": "checkov",
            "status": "failed",
            "reason": (stderr or f"no output (exit {code})")[:500],
            "analysis_mode": "heuristic",
        }
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"tool": "checkov", "status": "failed", "reason": "invalid JSON", "analysis_mode": "heuristic"}

    results = payload[0] if isinstance(payload, list) and payload else payload
    failed = (results.get("results") or {}).get("failed_checks") or results.get("failed_checks") or []
    findings: list[dict[str, Any]] = []
    root = Path(repo_path)
    for check in failed:
        if not isinstance(check, dict):
            continue
        file_path = str(check.get("file_path") or check.get("repo_file_path") or "")
        try:
            rel = Path(file_path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = file_path.replace("\\", "/")
        sev = str(check.get("severity") or "MEDIUM").lower()
        if sev not in _SEVERITY_ORDER:
            sev = "medium"
        findings.append(
            {
                "rule": check.get("check_id") or check.get("check_name") or "checkov",
                "severity": sev if sev in _SEVERITY_ORDER else "medium",
                "file": rel,
                "description": str(check.get("check_name") or check.get("check_id") or "Checkov policy failure"),
                "recommendation": str(check.get("guideline") or "Remediate per Checkov documentation."),
                "scanner": "checkov",
            }
        )

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    scanned = sorted({f["file"] for f in findings})
    return {
        "files_scanned": len(scanned),
        "finding_count": len(findings),
        "critical_count": critical,
        "passed": critical == 0,
        "findings": findings[:50],
        "summary": f"checkov: {len(findings)} failed check(s) ({critical} critical).",
        "analysis_mode": "checkov",
        "scanner": "checkov",
        "external_scanner": _scanner_status("checkov", status="ok", findings=findings),
    }


def _semgrep_severity(raw: str) -> str:
    level = str(raw or "WARNING").upper()
    if level in {"ERROR", "HIGH"}:
        return "high"
    if level in {"WARNING", "MEDIUM"}:
        return "medium"
    return "low"


def run_semgrep(repo_path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (normalized findings, scanner status). Empty findings when skipped/failed."""
    if not settings.security_semgrep_enabled:
        return [], {"tool": "semgrep", "status": "skipped", "reason": "disabled"}
    binary = _tool_path("semgrep")
    if not binary:
        return [], {"tool": "semgrep", "status": "skipped", "reason": "semgrep not installed"}

    cmd = [binary, "scan", "--config", "auto", "--json", "--quiet", repo_path]
    try:
        code, stdout, stderr = _run_cmd(cmd, timeout=240)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [], {"tool": "semgrep", "status": "failed", "reason": str(exc)}

    if not stdout.strip():
        return [], {"tool": "semgrep", "status": "failed", "reason": (stderr or f"exit {code}")[:500]}

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return [], {"tool": "semgrep", "status": "failed", "reason": "invalid JSON"}

    findings: list[dict[str, Any]] = []
    root = Path(repo_path)
    for row in data.get("results") or []:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "")
        try:
            rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = path.replace("\\", "/")
        extra = row.get("extra") or {}
        start = row.get("start") or {}
        findings.append(
            {
                "check_id": row.get("check_id") or "semgrep",
                "severity": _semgrep_severity(str(extra.get("severity") or "WARNING")),
                "file": rel,
                "line": int(start.get("line") or 0),
                "message": str(extra.get("message") or row.get("check_id") or "Semgrep finding"),
                "scanner": "semgrep",
            }
        )
    return findings[:100], {"tool": "semgrep", "status": "ok", "finding_count": len(findings)}


def run_syft(repo_path: str) -> dict[str, Any] | None:
    """Run Syft CycloneDX export when enabled and installed."""
    if not settings.sbom_syft_enabled:
        return None
    binary = _tool_path("syft")
    if not binary:
        return {
            "tool": "syft",
            "status": "skipped",
            "reason": "syft not installed",
            "analysis_mode": "heuristic",
        }

    cmd = [binary, "packages", repo_path, "-o", "cyclonedx-json", "-q"]
    try:
        code, stdout, stderr = _run_cmd(cmd, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"tool": "syft", "status": "failed", "reason": str(exc), "analysis_mode": "heuristic"}

    if not stdout.strip():
        return {
            "tool": "syft",
            "status": "failed",
            "reason": (stderr or f"exit {code}")[:500],
            "analysis_mode": "heuristic",
        }

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {"tool": "syft", "status": "failed", "reason": "invalid CycloneDX JSON", "analysis_mode": "heuristic"}

    components = data.get("components") or []
    normalized: list[dict[str, Any]] = []
    for row in components:
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "type": row.get("type") or "library",
                "name": row.get("name") or "unknown",
                "version": row.get("version") or "unknown",
                "purl": row.get("purl"),
                "scope": "required",
            }
        )

    return {
        "tool": "syft",
        "status": "ok",
        "analysis_mode": "scanner",
        "component_count": len(normalized),
        "components": normalized[:500],
        "bomFormat": data.get("bomFormat") or "CycloneDX",
        "specVersion": data.get("specVersion") or "1.5",
    }


def _resolve_zap_baseline() -> str | None:
    override = (settings.zap_path or "").strip()
    if override:
        return override
    for candidate in ("zap-baseline.py", "zap-baseline", "zap.sh"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def run_zap_baseline(target_url: str) -> dict[str, Any] | None:
    """Run OWASP ZAP baseline scan against staging URL when enabled."""
    if not settings.security_zap_enabled:
        return None
    binary = _resolve_zap_baseline()
    if not binary:
        return {
            "tool": "zap",
            "status": "skipped",
            "reason": "zap-baseline not installed",
            "analysis_mode": "heuristic",
        }

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        report_path = tmp.name

    cmd = [binary, "-t", target_url, "-J", report_path, "-I"]
    try:
        code, stdout, stderr = _run_cmd(cmd, timeout=settings.zap_timeout_seconds)
    except (subprocess.TimeoutExpired, OSError) as exc:
        Path(report_path).unlink(missing_ok=True)
        return {"tool": "zap", "status": "failed", "reason": str(exc), "analysis_mode": "heuristic"}

    raw = ""
    try:
        raw = Path(report_path).read_text(encoding="utf-8", errors="replace")
    finally:
        Path(report_path).unlink(missing_ok=True)

    if not raw.strip():
        return {
            "tool": "zap",
            "status": "failed",
            "reason": (stderr or stdout or f"exit {code}")[:500],
            "analysis_mode": "heuristic",
        }

    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        return {"tool": "zap", "status": "failed", "reason": "invalid ZAP JSON report", "analysis_mode": "heuristic"}

    return {
        "tool": "zap",
        "status": "ok",
        "analysis_mode": "zap",
        "report": report,
        "exit_code": code,
    }

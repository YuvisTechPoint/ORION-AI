"""Secret detection with remediation guidance (SecretGuardian)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.utils.external_scanners import run_gitleaks
from app.utils.text_analysis import redact_secrets

_SECRET_RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    ("AWS Access Key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "critical", "Revoke in IAM, rotate keys, remove from Git history."),
    ("AWS Secret Key", re.compile(r"(?i)(aws_secret_access_key|aws_secret_key)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{30,})"), "critical", "Rotate immediately and store in a secrets manager."),
    ("GitHub Token", re.compile(r"\b(ghp_[A-Za-z0-9]{20,})\b"), "critical", "Revoke token in GitHub settings and regenerate."),
    ("Anthropic API Key", re.compile(r"\b(sk-ant-[A-Za-z0-9\-_]{20,})\b"), "critical", "Rotate API key in Anthropic console."),
    ("Generic API Key", re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([^\s'\"]{12,})"), "high", "Remove from source, rotate credential, use vault/env injection."),
    ("Private Key", re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"), "critical", "Revoke certificate/key pair and remove from repository history."),
    ("Database URL", re.compile(r"(?i)(postgres|mysql|mongodb)(\+[a-z]+)?://[^\s'\"]+"), "high", "Rotate DB credentials and use managed secrets."),
]

_TEXT_EXTENSIONS = {".py", ".js", ".ts", ".json", ".yaml", ".yml", ".env", ".toml", ".cfg", ".ini", ".md", ".txt", ".sh"}


def _heuristic_scan(repo_path: str, *, changed_files: list[str] | None = None, max_files: int = 200) -> dict[str, Any]:
    root = Path(repo_path)
    targets: list[Path] = []

    if changed_files:
        for rel in changed_files[:max_files]:
            path = root / rel.replace("\\", "/")
            if path.is_file():
                targets.append(path)
    else:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            if any(part in {".git", "node_modules", ".venv", "venv", "__pycache__"} for part in path.parts):
                continue
            targets.append(path)
            if len(targets) >= max_files:
                break

    findings: list[dict[str, Any]] = []
    for path in targets:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")[:100_000]
        if redact_secrets(text) != text:
            pass  # redaction changed text — patterns below add structured findings
        for secret_type, pattern, severity, action in _SECRET_RULES:
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "type": secret_type,
                        "severity": severity,
                        "file": rel,
                        "line_hint": text[: match.start()].count("\n") + 1,
                        "recommended_action": action,
                        "remediation_steps": [
                            "Revoke or rotate the exposed credential",
                            "Remove secret from Git history (BFG/git filter-repo)",
                            "Store replacement in vault or CI secrets",
                            "Re-run pipeline after remediation",
                        ],
                    }
                )

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    return {
        "finding_count": len(findings),
        "critical_count": critical,
        "passed": critical == 0,
        "findings": findings[:40],
        "files_scanned": len(targets),
        "summary": (
            f"{len(findings)} secret pattern(s) detected ({critical} critical)."
            if findings
            else f"No secrets detected in {len(targets)} scanned file(s)."
        ),
        "analysis_mode": "heuristic",
        "scanner": "heuristic",
    }


def scan_secrets(repo_path: str, *, changed_files: list[str] | None = None, max_files: int = 200) -> dict[str, Any]:
    external = run_gitleaks(repo_path)
    if isinstance(external, dict) and external.get("analysis_mode") == "gitleaks":
        external.setdefault("files_scanned", external.get("files_scanned") or 0)
        return external

    report = _heuristic_scan(repo_path, changed_files=changed_files, max_files=max_files)
    if isinstance(external, dict):
        report["external_scanner"] = external
        if external.get("status") == "skipped":
            report["tools_recommended"] = ["gitleaks"]
    return report

"""Prompt injection firewall — classify and sanitize untrusted repository content."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from typing import Any, Iterator

from app.config import settings

# Adversarial patterns only — avoid blocking benign ed-tech / docs ("act as a tutor", "LLM system prompt").
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "ignore_instructions",
        re.compile(r"ignore (all )?(previous|prior|above) (instructions|prompts)", re.I),
        "high",
        "Remove adversarial LLM override phrasing from commit messages and source comments.",
    ),
    (
        "system_override",
        re.compile(
            r"(disregard (your|the) rules"
            r"|you are now (?:a |an )?(?:DAN|unrestricted|jailbroken|without rules)"
            r"|(?:reveal|show|print|ignore|disregard|dump).{0,40}system prompt"
            r"|act as (?:a |an )?(?:DAN|unrestricted|evil|malicious|admin|root|hacker))",
            re.I,
        ),
        "high",
        "Replace adversarial role-override language; benign tutor/docs wording is allowed.",
    ),
    (
        "exfiltration",
        re.compile(r"(reveal|print|dump).{0,40}(secret|api[_ -]?key|token|password)", re.I),
        "critical",
        "Remove instructions that ask models to leak secrets; rotate any exposed credentials.",
    ),
    (
        "delimiter_injection",
        re.compile(r"<\s*/?\s*(system|assistant|human|instruction)\s*>", re.I),
        "medium",
        "Escape or remove pseudo chat-role XML/markup from user-controlled text.",
    ),
    (
        "jailbreak",
        re.compile(r"\b(DAN|do anything now|jailbreak)\b", re.I),
        "high",
        "Remove jailbreak keywords from production code paths (tests may be excluded via globs).",
    ),
]

_SEVERITY_RANK = {"medium": 1, "high": 2, "critical": 3}

_RULE_REMEDIATION = {rule_id: action for rule_id, _, _, action in _INJECTION_PATTERNS}


def _snippet(text: str, start: int, end: int, radius: int = 48) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    excerpt = (text[lo:hi] or "").replace("\n", " ").strip()
    if lo > 0:
        excerpt = "…" + excerpt
    if hi < len(text):
        excerpt = excerpt + "…"
    return excerpt


def _path_excluded(path: str, patterns: list[str]) -> bool:
    norm = path.replace("\\", "/").lstrip("./")
    for pat in patterns:
        p = pat.replace("\\", "/").lstrip("./")
        if p.startswith("**/"):
            suffix = p[3:]
            if fnmatch(norm, suffix) or fnmatch(norm, f"*/{suffix}"):
                return True
            if any(fnmatch(part, suffix) for part in norm.split("/")):
                return True
        elif fnmatch(norm, p):
            return True
    return False


def iter_diff_added_chunks(diff_text: str) -> Iterator[tuple[str, str]]:
    """Yield (file_path, added_lines_text) from a unified diff — scans only new content."""
    current = ""
    buf: list[str] = []
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ b/"):
            if buf and current:
                yield current, "\n".join(buf)
            current = line[6:].strip()
            if current == "/dev/null":
                current = ""
            buf = []
        elif line.startswith("+") and not line.startswith("+++"):
            buf.append(line[1:])
        elif line.startswith("diff --git ") and buf and current:
            yield current, "\n".join(buf)
            buf = []
    if buf and current:
        yield current, "\n".join(buf)


def scan_untrusted_content(text: str, *, source: str = "content", file: str | None = None) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    body = text or ""
    for rule_id, pattern, severity, remediation in _INJECTION_PATTERNS:
        for match in pattern.finditer(body):
            finding: dict[str, Any] = {
                "rule_id": rule_id,
                "severity": severity,
                "source": source,
                "line": body[: match.start()].count("\n") + 1,
                "snippet": _snippet(body, match.start(), match.end()),
                "recommended_action": remediation,
                "pattern": pattern.pattern[:80],
            }
            if file:
                finding["file"] = file
            findings.append(finding)

    max_rank = max((_SEVERITY_RANK.get(f["severity"], 0) for f in findings), default=0)
    max_severity = (
        "critical"
        if max_rank >= 3
        else "high"
        if max_rank >= 2
        else "medium"
        if max_rank >= 1
        else "none"
    )
    blocked = max_rank >= _SEVERITY_RANK["high"]
    return {
        "findings": findings,
        "finding_count": len(findings),
        "max_severity": max_severity,
        "blocked": blocked,
        "scanned_chars": len(body),
        "source": source,
        "summary": (
            f"Prompt injection scan: {len(findings)} finding(s), max={max_severity}."
            if findings
            else "Prompt injection scan: clean."
        ),
    }


def scan_repository_submission(
    commit_message: str,
    diff_text: str,
    *,
    exclude_globs: list[str] | None = None,
    max_diff_chars: int | None = None,
) -> dict[str, Any]:
    """Scan commit message + per-file added diff hunks (skips tests and security fixtures)."""
    excludes = exclude_globs if exclude_globs is not None else settings.prompt_injection_exclude_glob_list
    limit = max_diff_chars if max_diff_chars is not None else settings.prompt_injection_max_diff_chars
    body = (diff_text or "")[:limit]

    reports = [scan_untrusted_content(commit_message, source="commit_message")]
    files_scanned = 0
    files_skipped = 0

    for path, added in iter_diff_added_chunks(body):
        if _path_excluded(path, excludes):
            files_skipped += 1
            continue
        if not added.strip():
            continue
        files_scanned += 1
        reports.append(scan_untrusted_content(added, source=f"diff:{path}", file=path))

    merged = merge_injection_scans(*reports)
    merged["files_scanned"] = files_scanned
    merged["files_skipped"] = files_skipped
    merged["exclude_globs"] = excludes
    return merged


def merge_injection_scans(*reports: dict[str, Any]) -> dict[str, Any]:
    """Combine per-source scans (commit message, diff, etc.) into one gate artifact."""
    findings: list[dict[str, Any]] = []
    scanned_chars = 0
    for report in reports:
        scanned_chars += int(report.get("scanned_chars") or 0)
        findings.extend(report.get("findings") or [])

    max_rank = max((_SEVERITY_RANK.get(f.get("severity", ""), 0) for f in findings), default=0)
    max_severity = (
        "critical"
        if max_rank >= 3
        else "high"
        if max_rank >= 2
        else "medium"
        if max_rank >= 1
        else "none"
    )
    blocked = max_rank >= _SEVERITY_RANK["high"]
    remediation_steps = list(
        dict.fromkeys(
            f.get("recommended_action") or _RULE_REMEDIATION.get(f.get("rule_id", ""), "")
            for f in findings
            if f.get("recommended_action") or f.get("rule_id") in _RULE_REMEDIATION
        )
    )
    return {
        "findings": findings[:20],
        "finding_count": len(findings),
        "max_severity": max_severity,
        "blocked": blocked,
        "scanned_chars": scanned_chars,
        "sources_scanned": [r.get("source") for r in reports if r.get("source")],
        "remediation_steps": remediation_steps
        or [
            "Inspect the prompt_injection_scan artifact for matched snippets and file paths.",
            "Edit the flagged file or commit message, push a new commit, then Retry.",
            "Re-run the pipeline after the repository content is safe for LLM agents.",
        ],
        "summary": (
            f"Prompt injection scan: {len(findings)} finding(s), max={max_severity}."
            if findings
            else "Prompt injection scan: clean."
        ),
    }


def sanitize_untrusted_input(text: str) -> str:
    """Neutralize common injection delimiters before LLM prompts."""
    cleaned = text or ""
    for _, pattern, _, _ in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[REDACTED-INJECTION-PATTERN]", cleaned)
    return cleaned

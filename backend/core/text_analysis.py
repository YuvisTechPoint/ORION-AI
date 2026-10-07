"""Advanced string and log text utilities shared by ORION agents and APIs."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

# --- Patterns -----------------------------------------------------------------

_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)
_DIFF_ADDED_RE = re.compile(r"^\+(?!\+\+)(.*)$", re.MULTILINE)
_DIFF_REMOVED_RE = re.compile(r"^-+(?!-)(.*)$", re.MULTILINE)

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|authorization)\s*[:=]\s*['\"]?([^\s'\"]{8,})"), r"\1=***REDACTED***"),
    (re.compile(r"\b(sk-ant-[A-Za-z0-9\-_]{20,})\b"), "sk-ant-***REDACTED***"),
    (re.compile(r"\b(ghp_[A-Za-z0-9]{20,})\b"), "ghp_***REDACTED***"),
    (re.compile(r"\b(gho_[A-Za-z0-9]{20,})\b"), "gho_***REDACTED***"),
    (re.compile(r"\b(xox[baprs]-[A-Za-z0-9\-]{10,})\b"), "xox***REDACTED***"),
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+ PRIVATE KEY-----"), "***PRIVATE_KEY_REDACTED***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer ***REDACTED***"),
]

_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "***@***.***"),
    (re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "***-***-****"),
]

_ERROR_LINE_RE = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|Exception|Traceback|panic|AssertionError|failed)\b",
    re.IGNORECASE,
)
_WARN_LINE_RE = re.compile(r"\b(WARN|WARNING)\b", re.IGNORECASE)
_TS_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
_STACK_FRAME_RE = re.compile(r'^\s*File "([^"]+)", line (\d+)', re.MULTILINE)

_LOG_TYPE_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("server_timeout", re.compile(r"timeout|timed out|deadline exceeded|504 gateway", re.I)),
    ("build_error", re.compile(r"build failed|npm ERR!|ModuleNotFoundError|compilation error", re.I)),
    ("git_operation", re.compile(r"merge conflict|detached HEAD|fatal: .*(git|ref)", re.I)),
    ("deployment_crash", re.compile(r"OOMKilled|exit code 137|CrashLoopBackOff|segfault", re.I)),
    ("memory_leak", re.compile(r"memory leak|OutOfMemory|cannot allocate memory", re.I)),
    ("database", re.compile(r"psycopg|sqlalchemy|deadlock|connection refused.*5432", re.I)),
    ("network", re.compile(r"connection reset|ECONNREFUSED|DNS|certificate verify failed", re.I)),
]


def redact_secrets(text: str) -> str:
    """Mask common secret/token patterns before logging or LLM prompts."""
    out = text or ""
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def mask_pii(text: str) -> str:
    out = text or ""
    for pattern, repl in _PII_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def sanitize_for_agent(text: str, *, redact: bool = True, mask_personal: bool = False) -> str:
    """Prepare arbitrary user/repo text for safe agent consumption."""
    out = normalize_whitespace(text or "")
    if redact:
        out = redact_secrets(out)
    if mask_personal:
        out = mask_pii(out)
    return out


def normalize_whitespace(text: str) -> str:
    """Normalize unicode and collapse excessive blank lines."""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    return normalized.strip()


def truncate_with_context(text: str, max_chars: int, *, marker: str = "\n…[truncated]…\n") -> str:
    """Keep head and tail when truncating long strings for LLM context windows."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars < len(marker) + 20:
        return text[:max_chars]
    head = max_chars // 2
    tail = max_chars - head - len(marker)
    return text[:head] + marker + text[-tail:]


def tail_lines(text: str, limit: int = 10_000) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-limit:]) if len(lines) > limit else (text or "")


def head_lines(text: str, limit: int = 200) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[:limit])


def files_in_diff(diff_text: str) -> list[str]:
    return [m.strip() for m in _DIFF_FILE_RE.findall(diff_text or "") if m.strip() != "/dev/null"]


def diff_stats(diff_text: str) -> dict[str, Any]:
    """Summarize a unified diff without loading the full repo."""
    files = files_in_diff(diff_text)
    added = len(_DIFF_ADDED_RE.findall(diff_text or ""))
    removed = len(_DIFF_REMOVED_RE.findall(diff_text or ""))
    return {
        "files_changed": len(files),
        "files": files[:50],
        "lines_added": added,
        "lines_removed": removed,
        "net_change": added - removed,
    }


def extract_stack_traces(text: str, *, max_traces: int = 5) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    blocks = re.split(r"(?=Traceback \(most recent call last\):)", text or "")
    for block in blocks:
        if "Traceback" not in block:
            continue
        frames = [
            {"file": m.group(1), "line": int(m.group(2))}
            for m in _STACK_FRAME_RE.finditer(block)
        ]
        exc_match = re.search(r"(\w+(?:Error|Exception)): (.+)$", block.strip(), re.MULTILINE)
        traces.append(
            {
                "exception": exc_match.group(1) if exc_match else "Exception",
                "message": (exc_match.group(2) if exc_match else block.strip().splitlines()[-1])[:500],
                "frames": frames[-8:],
            }
        )
        if len(traces) >= max_traces:
            break
    return traces


def extract_error_signatures(text: str, *, limit: int = 20) -> list[str]:
    seen: set[str] = set()
    signatures: list[str] = []
    for line in (text or "").splitlines():
        if not _ERROR_LINE_RE.search(line):
            continue
        sig = re.sub(r"\d+", "N", line.strip())[:240]
        if sig not in seen:
            seen.add(sig)
            signatures.append(sig)
        if len(signatures) >= limit:
            break
    return signatures


def classify_log_type(text: str) -> str:
    sample = (text or "")[:20_000]
    for name, pattern in _LOG_TYPE_HINTS:
        if pattern.search(sample):
            return name
    if _ERROR_LINE_RE.search(sample):
        return "generic_error"
    if _WARN_LINE_RE.search(sample):
        return "generic_warning"
    return "unknown"


def extract_log_timeline(text: str, *, limit: int = 50) -> list[dict[str, str]]:
    timeline: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        ts = _TS_RE.search(line)
        if not ts and not _ERROR_LINE_RE.search(line) and not _WARN_LINE_RE.search(line):
            continue
        severity = "error" if _ERROR_LINE_RE.search(line) else "warn" if _WARN_LINE_RE.search(line) else "info"
        timeline.append(
            {
                "timestamp": ts.group(1) if ts else "",
                "severity": severity,
                "event": line.strip()[:300],
            }
        )
        if len(timeline) >= limit:
            break
    return timeline


def similarity_ratio(left: str, right: str) -> float:
    return round(SequenceMatcher(None, left or "", right or "").ratio(), 4)


def text_fingerprint(text: str) -> str:
    digest = hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()
    return digest[:16]


def string_metrics(text: str) -> dict[str, Any]:
    lines = (text or "").splitlines()
    words = re.findall(r"\w+", text or "")
    return {
        "characters": len(text or ""),
        "lines": len(lines),
        "words": len(words),
        "error_lines": sum(1 for ln in lines if _ERROR_LINE_RE.search(ln)),
        "warning_lines": sum(1 for ln in lines if _WARN_LINE_RE.search(ln)),
        "fingerprint": text_fingerprint(text or ""),
    }


def parse_commit_message(message: str) -> dict[str, Any]:
    """Lightweight conventional-commit parser for agent context."""
    msg = (message or "").strip()
    first_line = msg.splitlines()[0] if msg else ""
    match = re.match(
        r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?: (?P<summary>.+)$",
        first_line,
        re.I,
    )
    body_parts = msg.split("\n\n", 1)
    body = body_parts[1].strip() if len(body_parts) > 1 else ""
    if match:
        return {
            "conventional": True,
            "type": match.group("type").lower(),
            "scope": match.group("scope"),
            "breaking": bool(match.group("breaking")),
            "summary": match.group("summary").strip(),
            "body": body,
        }
    return {"conventional": False, "summary": first_line, "body": body}


def run_text_operations(text: str, operations: list[str]) -> dict[str, Any]:
    """Execute named string analysis operations (used by /tools/text-analyze)."""
    ops = {op.strip().lower() for op in operations if op.strip()}
    result: dict[str, Any] = {"operations": sorted(ops)}
    if "metrics" in ops:
        result["metrics"] = string_metrics(text)
    if "redact" in ops or "redact_secrets" in ops:
        result["redacted"] = redact_secrets(text)
    if "sanitize" in ops:
        result["sanitized"] = sanitize_for_agent(text)
    if "classify_log" in ops:
        result["log_type"] = classify_log_type(text)
    if "timeline" in ops:
        result["timeline"] = extract_log_timeline(text)
    if "errors" in ops or "error_signatures" in ops:
        result["error_signatures"] = extract_error_signatures(text)
    if "stack_traces" in ops:
        result["stack_traces"] = extract_stack_traces(text)
    if "truncate" in ops:
        result["truncated"] = truncate_with_context(text, 8000)
    if "fingerprint" in ops:
        result["fingerprint"] = text_fingerprint(text)
    if "diff_stats" in ops and ("+++" in (text or "") or "---" in (text or "")):
        result["diff_stats"] = diff_stats(text)
    if "commit" in ops:
        result["commit"] = parse_commit_message(text)
    return result

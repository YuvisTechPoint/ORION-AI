"""MEM-03: redact secrets before any memory write; fail closed on redaction errors."""

from __future__ import annotations

import re

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-api03-[A-Za-z0-9_-]{20,}", re.I),
    re.compile(r"ghp_[A-Za-z0-9]{20,}", re.I),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+-]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
]

_INSTRUCTION_PATTERNS = [
    re.compile(r"(?i)\bignore (?:all )?(?:previous|prior) instructions\b"),
    re.compile(r"(?i)\byou are now\b"),
    re.compile(r"(?i)\bsystem:\s*override\b"),
]


def redact_secrets(text: str) -> str:
    out = text or ""
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def contains_secrets(text: str) -> bool:
    sample = text or ""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(sample):
            return True
    return False


def looks_like_injection(text: str) -> bool:
    sample = text or ""
    return any(p.search(sample) for p in _INSTRUCTION_PATTERNS)


def prepare_memory_body(text: str, *, fail_closed: bool = True) -> str:
    if not text:
        return ""
    if contains_secrets(text) and fail_closed:
        redacted = redact_secrets(text)
        if contains_secrets(redacted):
            raise ValueError("Memory write blocked: secret redaction failed")
        return redacted
    return redact_secrets(text)

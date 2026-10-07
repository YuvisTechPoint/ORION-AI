"""Correlation helpers for devops-platform."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

CORRELATION_HEADER = "X-Correlation-ID"
TRACE_HEADER = "X-Trace-ID"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def resolve_correlation_id(header_value: str | None) -> str:
    value = (header_value or "").strip() or _correlation_id.get()
    if not value:
        value = uuid.uuid4().hex
    _correlation_id.set(value)
    return value


def resolve_trace_id(header_value: str | None) -> str:
    value = (header_value or "").strip()
    if not value:
        value = uuid.uuid4().hex
    return value

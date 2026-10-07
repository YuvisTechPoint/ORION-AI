"""Correlation and trace identifiers for cross-service tracing."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

CORRELATION_HEADER = "X-Correlation-ID"
TRACE_HEADER = "X-Trace-ID"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def new_trace_id() -> str:
    return uuid.uuid4().hex


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_trace_id(value: str | None) -> None:
    _trace_id.set(value)


def get_trace_id() -> str | None:
    return _trace_id.get()


def resolve_correlation_id(header_value: str | None) -> str:
    value = (header_value or "").strip() or get_correlation_id()
    if not value:
        value = new_correlation_id()
    set_correlation_id(value)
    return value


def resolve_trace_id(header_value: str | None) -> str:
    value = (header_value or "").strip() or get_trace_id()
    if not value:
        value = new_trace_id()
    set_trace_id(value)
    return value

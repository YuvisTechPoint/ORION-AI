"""Lightweight Prometheus metrics for canonical backend."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class _Counter:
    __slots__ = ("name", "help_text", "values")

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self.values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        self.values[key] += amount


_lock = threading.Lock()
http_requests_total = _Counter("canonical_http_requests_total", "Total HTTP requests")
pipeline_submissions_total = _Counter("canonical_pipeline_submissions_total", "Pipeline submissions")


def _label_str(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + inner + "}"


def render_prometheus() -> str:
    lines: list[str] = []
    with _lock:
        for counter in (http_requests_total, pipeline_submissions_total):
            lines.append(f"# HELP {counter.name} {counter.help_text}")
            lines.append(f"# TYPE {counter.name} counter")
            for labels, value in sorted(counter.values.items()):
                lines.append(f"{counter.name}{_label_str(labels)} {value}")
    return "\n".join(lines) + "\n"


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        response = await call_next(request)
        route = request.url.path.split("?")[0]
        with _lock:
            http_requests_total.inc(
                method=request.method,
                route=route,
                status=str(response.status_code),
            )
        return response

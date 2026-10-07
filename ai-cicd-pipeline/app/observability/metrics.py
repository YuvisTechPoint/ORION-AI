"""Lightweight Prometheus exposition format (no external dependency)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


class _Counter:
    __slots__ = ("name", "help_text", "values")

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self.values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        self.values[key] += amount


class _Histogram:
    __slots__ = ("name", "help_text", "buckets", "counts", "sum")

    def __init__(self, name: str, help_text: str, buckets: tuple[float, ...]) -> None:
        self.name = name
        self.help_text = help_text
        self.buckets = buckets
        self.counts: dict[tuple[tuple[str, str], ...], dict[float, float]] = defaultdict(
            lambda: {b: 0.0 for b in buckets}
        )
        self.sum: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        for bucket in self.buckets:
            if value <= bucket:
                self.counts[key][bucket] += 1
        self.sum[key] += value


_lock = threading.Lock()

http_requests_total = _Counter("orion_http_requests_total", "Total HTTP requests")
http_request_duration_seconds = _Histogram(
    "orion_http_request_duration_seconds",
    "HTTP request latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
pipeline_runs_total = _Counter("orion_pipeline_runs_total", "Pipeline runs by terminal status")
webhook_deliveries_total = _Counter("orion_webhook_deliveries_total", "GitHub webhook deliveries")


def _label_str(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + inner + "}"


def render_prometheus() -> str:
    lines: list[str] = []
    with _lock:
        for counter in (http_requests_total, pipeline_runs_total, webhook_deliveries_total):
            lines.append(f"# HELP {counter.name} {counter.help_text}")
            lines.append(f"# TYPE {counter.name} counter")
            for labels, value in sorted(counter.values.items()):
                lines.append(f"{counter.name}{_label_str(labels)} {value}")

        hist = http_request_duration_seconds
        lines.append(f"# HELP {hist.name} {hist.help_text}")
        lines.append(f"# TYPE {hist.name} histogram")
        for labels, bucket_counts in sorted(hist.counts.items()):
            cumulative = 0.0
            for bucket in hist.buckets:
                cumulative += bucket_counts[bucket]
                lines.append(
                    f'{hist.name}_bucket{_label_str(labels + (("le", str(bucket)),))} {cumulative}'
                )
            lines.append(f'{hist.name}_bucket{_label_str(labels + (("le", "+Inf"),))} {cumulative}')
            lines.append(f"{hist.name}_sum{_label_str(labels)} {hist.sum[labels]}")
            lines.append(f"{hist.name}_count{_label_str(labels)} {cumulative}")
    return "\n".join(lines) + "\n"


class RequestMetricsMiddleware:
    """Record request counts and latency for /metrics scraping."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        path = scope.get("path") or ""
        method = scope.get("method") or "GET"
        status_holder: dict[str, int] = {"code": 500}

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status_holder["code"] = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            route = path.split("?")[0]
            with _lock:
                http_requests_total.inc(method=method, route=route, status=str(status_holder["code"]))
                http_request_duration_seconds.observe(elapsed, method=method, route=route)

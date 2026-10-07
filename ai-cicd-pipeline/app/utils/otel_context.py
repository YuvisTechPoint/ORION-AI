"""OpenTelemetry-compatible trace context export (heuristic, no collector required)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def build_otel_trace_context(
    *,
    run_id: str,
    commit: str,
    repo: str,
    environment: str,
    service_name: str = "orion-app",
) -> dict[str, Any]:
    trace_id = uuid4().hex
    root_span_id = uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()

    return {
        "trace_id": trace_id,
        "spans": [
            {
                "span_id": root_span_id,
                "name": "pipeline.run",
                "service": service_name,
                "environment": environment,
                "attributes": {
                    "run_id": run_id,
                    "commit": commit,
                    "repository": repo,
                    "deployment.environment": environment,
                },
                "start_time": now,
            },
            {
                "span_id": uuid4().hex[:16],
                "parent_span_id": root_span_id,
                "name": "pipeline.deploy",
                "service": service_name,
                "attributes": {"commit": commit},
            },
            {
                "span_id": uuid4().hex[:16],
                "parent_span_id": root_span_id,
                "name": "pipeline.monitor",
                "service": service_name,
                "attributes": {"run_id": run_id},
            },
        ],
        "resource": {
            "service.name": service_name,
            "service.namespace": repo,
            "deployment.environment": environment,
        },
        "format": "otel-like-json",
        "summary": f"Trace {trace_id[:16]}… exported for run {run_id[:8]}",
    }

"""OpenTelemetry-compatible trace context export with optional OTLP HTTP push."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("otel")


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

    ctx = {
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

    export_result = _export_otlp_http(ctx, run_id=run_id, commit=commit, repo=repo, environment=environment)
    if export_result:
        ctx["otlp_export"] = export_result
    return ctx


def _export_otlp_http(
    ctx: dict[str, Any],
    *,
    run_id: str,
    commit: str,
    repo: str,
    environment: str,
) -> dict[str, Any] | None:
    if not settings.otel_export_enabled:
        return None
    endpoint = (settings.otel_exporter_otlp_endpoint or "").strip().rstrip("/")
    if not endpoint:
        return {"status": "skipped", "reason": "OTEL_EXPORTER_OTLP_ENDPOINT not configured"}

    service = settings.otel_service_name or settings.app_name
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service}},
                        {"key": "deployment.environment", "value": {"stringValue": environment}},
                        {"key": "repository", "value": {"stringValue": repo}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "orion.pipeline"},
                        "spans": [
                            {
                                "traceId": ctx["trace_id"],
                                "spanId": span.get("span_id"),
                                "parentSpanId": span.get("parent_span_id"),
                                "name": span.get("name"),
                                "kind": 1,
                                "attributes": [
                                    {"key": k, "value": {"stringValue": str(v)}}
                                    for k, v in (span.get("attributes") or {}).items()
                                ],
                            }
                            for span in ctx.get("spans") or []
                        ],
                    }
                ],
            }
        ]
    }

    url = endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(url, content=json.dumps(payload), headers={"Content-Type": "application/json"})
        if resp.status_code >= 400:
            logger.warning("OTLP export failed: %s %s", resp.status_code, resp.text[:200])
            return {"status": "error", "http_status": resp.status_code, "run_id": run_id, "commit": commit}
        return {"status": "exported", "endpoint": url, "trace_id": ctx["trace_id"]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("OTLP export exception: %s", exc)
        return {"status": "error", "detail": str(exc)[:200]}

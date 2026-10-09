"""Command Hub FastAPI — static UI + unified control-plane API."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from hub.federation.adapters import (
    TERMINAL_STATUSES,
    control_action,
    federated_list_pipelines,
    get_artifact,
    get_run,
    health_matrix,
    list_artifacts,
    list_audit,
)
from hub.federation.client import CORRELATION_HEADER
from hub.federation.intelligence_fanout import fanout_intelligence, fetch_orion_fleet
from hub.federation.platform_events import fetch_orion_platform_events
from hub.federation.operations_center import build_operations_center
from hub.federation.timeline import build_timeline

HUB_DIR = Path(__file__).resolve().parent
ROOT = HUB_DIR.parent

app = FastAPI(
    title="ORION Command Hub",
    version="2.0.0",
    description="Unified control plane BFF for Binary-v2 stacks",
)

def _hub_cors_origins() -> list[str]:
    raw = os.getenv(
        "HUB_CORS_ORIGINS",
        "http://127.0.0.1:5180,http://localhost:5180,http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000",
    )
    origins = [part.strip() for part in raw.split(",") if part.strip()]
    return origins or ["http://127.0.0.1:5180"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_hub_cors_origins(),
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


def _correlation_id(request: Request) -> str:
    incoming = (request.headers.get(CORRELATION_HEADER) or "").strip()
    return incoming or uuid.uuid4().hex


@app.middleware("http")
async def attach_correlation(request: Request, call_next):
    cid = _correlation_id(request)
    request.state.correlation_id = cid
    response = await call_next(request)
    response.headers[CORRELATION_HEADER] = cid
    return response


@app.get("/health")
async def hub_health() -> dict[str, str]:
    return {"status": "ok", "api": "ok", "service": "orion-command-hub"}


@app.get("/ready")
async def hub_ready() -> dict[str, bool]:
    return {"ready": True, "service": "orion-command-hub"}


@app.get("/api/v1/control-plane/health")
async def control_plane_health(request: Request) -> dict[str, Any]:
    matrix = await health_matrix(correlation_id=request.state.correlation_id)
    return matrix.model_dump()


@app.get("/api/v1/control-plane/pipelines")
async def control_plane_pipelines(
    request: Request,
    limit: int = Query(30, ge=1, le=200),
    stack: str | None = None,
    status: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    result = await federated_list_pipelines(
        limit=limit,
        stack_filter=stack,
        status=status,
        repo=repo,
        branch=branch,
        correlation_id=request.state.correlation_id,
    )
    return result.model_dump()


@app.get("/api/v1/control-plane/pipelines/{run_id:path}/timeline")
async def control_plane_timeline(run_id: str, request: Request) -> dict[str, Any]:
    if ":" not in run_id:
        raise HTTPException(status_code=400, detail="run_id must be stack:native_id")
    stack, native = run_id.split(":", 1)
    row = await get_run(stack, native, correlation_id=request.state.correlation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    timeline = build_timeline(
        stack=stack,
        run_id=run_id,
        native_run_id=native,
        status=row.status,
        correlation_id=row.correlation_id or request.state.correlation_id,
    )
    return timeline.model_dump()


@app.get("/api/v1/control-plane/pipelines/{run_id:path}/artifacts")
async def control_plane_artifacts(run_id: str, request: Request) -> dict[str, Any]:
    items = await list_artifacts(run_id, correlation_id=request.state.correlation_id)
    return {"run_id": run_id, "artifacts": [a.model_dump() for a in items]}


@app.get("/api/v1/control-plane/pipelines/{run_id:path}/artifacts/{artifact_type}")
async def control_plane_artifact(run_id: str, artifact_type: str, request: Request) -> dict[str, Any]:
    body = await get_artifact(run_id, artifact_type, correlation_id=request.state.correlation_id)
    if not body:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return body


@app.get("/api/v1/control-plane/audit")
async def control_plane_audit(
    request: Request,
    run_id: str | None = None,
    stack: str | None = None,
    action: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    events = await list_audit(
        run_id=run_id,
        stack_filter=stack,
        action=action,
        correlation_id=request.state.correlation_id,
        limit=limit,
    )
    return {
        "correlation_id": request.state.correlation_id,
        "events": [e.model_dump() for e in events],
        "total": len(events),
    }


@app.get("/api/v1/control-plane/catalog")
async def control_plane_catalog() -> dict[str, Any]:
    from hub.federation.catalog import load_catalog

    return load_catalog()


@app.get("/api/v1/control-plane/intelligence")
async def control_plane_intelligence(request: Request) -> dict[str, Any]:
    snapshots = await fanout_intelligence(correlation_id=request.state.correlation_id)
    return {
        "correlation_id": request.state.correlation_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stacks": [s.model_dump() for s in snapshots],
    }


@app.get("/api/v1/control-plane/fleet")
async def control_plane_fleet(request: Request) -> dict[str, Any]:
    fleet = await fetch_orion_fleet(correlation_id=request.state.correlation_id)
    return {
        "correlation_id": request.state.correlation_id,
        **fleet,
    }


@app.get("/api/v1/control-plane/operations")
async def control_plane_operations(request: Request) -> dict[str, Any]:
    report = await build_operations_center(correlation_id=request.state.correlation_id)
    return report.model_dump()


@app.get("/api/v1/control-plane/platform-events")
async def control_plane_platform_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = None,
) -> dict[str, Any]:
    return await fetch_orion_platform_events(
        correlation_id=request.state.correlation_id,
        limit=limit,
        event_type=event_type,
    )


def _event_identity(event: dict[str, Any]) -> str:
    eid = str(event.get("event_id") or "").strip()
    if eid:
        return eid
    return json.dumps(event, sort_keys=True, default=str)


async def _platform_event_stream(
    correlation_id: str,
    *,
    event_type: str | None,
    max_ticks: int,
    poll_seconds: float = 3.0,
    snapshot_limit: int = 10,
):
    seen: set[str] = set()
    for tick in range(max_ticks):
        data = await fetch_orion_platform_events(
            correlation_id=correlation_id,
            limit=50,
            event_type=event_type,
        )
        if not data.get("available"):
            payload = {"kind": "error", "message": data.get("error") or "platform_events_unavailable"}
            yield f"data: {json.dumps(payload)}\n\n"
            break
        events = list(data.get("events") or [])
        new_events: list[dict[str, Any]] = []
        for event in events:
            key = _event_identity(event)
            if key in seen:
                continue
            seen.add(key)
            new_events.append(event)
        if tick == 0:
            for event in new_events[-snapshot_limit:]:
                yield f"data: {json.dumps({'kind': 'platform_event', 'event': event})}\n\n"
        else:
            for event in new_events:
                yield f"data: {json.dumps({'kind': 'platform_event', 'event': event})}\n\n"
        await asyncio.sleep(poll_seconds)
    yield f"data: {json.dumps({'kind': 'complete'})}\n\n"


@app.get("/api/v1/control-plane/platform-events/stream")
async def control_plane_platform_events_stream(
    request: Request,
    event_type: str | None = None,
    max_ticks: int = Query(default=120, ge=1, le=600),
) -> StreamingResponse:
    return StreamingResponse(
        _platform_event_stream(
            request.state.correlation_id,
            event_type=event_type,
            max_ticks=max_ticks,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _pipeline_event_stream(run_id: str, correlation_id: str):
    last_status: str | None = None
    for _ in range(120):
        if ":" not in run_id:
            yield f"data: {json.dumps({'error': 'invalid run_id'})}\n\n"
            break
        stack, native = run_id.split(":", 1)
        row = await get_run(stack, native, correlation_id=correlation_id)
        if row is None:
            yield f"data: {json.dumps({'error': 'not_found', 'run_id': run_id})}\n\n"
            break
        if row.status != last_status:
            payload = {
                "run_id": run_id,
                "status": row.status,
                "correlation_id": row.correlation_id or correlation_id,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            last_status = row.status
        if row.status in TERMINAL_STATUSES:
            break
        await asyncio.sleep(3)
    yield f"data: {json.dumps({'kind': 'complete', 'run_id': run_id})}\n\n"


@app.get("/api/v1/control-plane/pipelines/{run_id:path}/events")
async def control_plane_events(run_id: str, request: Request) -> StreamingResponse:
    if ":" not in run_id:
        raise HTTPException(status_code=400, detail="run_id must be stack:native_id")
    return StreamingResponse(
        _pipeline_event_stream(run_id, request.state.correlation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/control-plane/pipelines/{run_id:path}/retry")
async def control_plane_retry(run_id: str, request: Request) -> dict[str, Any]:
    code, body = await control_action(run_id, "retry", correlation_id=request.state.correlation_id)
    if code not in (200, 202):
        raise HTTPException(status_code=code or 502, detail=body)
    return {"ok": True, "action": "retry", "run_id": run_id, "response": body}


@app.post("/api/v1/control-plane/pipelines/{run_id:path}/resume")
async def control_plane_resume(run_id: str, request: Request) -> dict[str, Any]:
    code, body = await control_action(run_id, "resume", correlation_id=request.state.correlation_id)
    if code not in (200, 202):
        raise HTTPException(status_code=code or 502, detail=body)
    return {"ok": True, "action": "resume", "run_id": run_id, "response": body}


@app.post("/api/v1/control-plane/pipelines/{run_id:path}/cancel")
async def control_plane_cancel(run_id: str, request: Request) -> dict[str, Any]:
    code, body = await control_action(run_id, "cancel", correlation_id=request.state.correlation_id)
    if code not in (200, 202):
        raise HTTPException(status_code=code or 502, detail=body)
    return {"ok": True, "action": "cancel", "run_id": run_id, "response": body}


@app.get("/api/v1/control-plane/pipelines/{run_id:path}")
async def control_plane_pipeline(run_id: str, request: Request) -> dict[str, Any]:
    if ":" not in run_id:
        raise HTTPException(status_code=400, detail="run_id must be stack:native_id")
    stack, native = run_id.split(":", 1)
    row = await get_run(stack, native, correlation_id=request.state.correlation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return row.model_dump()


app.mount("/", StaticFiles(directory=str(HUB_DIR), html=True), name="static")


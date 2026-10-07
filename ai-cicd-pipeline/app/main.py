import asyncio
import contextlib
import json
import time
import traceback
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

import app.models.pipeline_artifact  # noqa: F401
import app.models.pipeline_run  # noqa: F401
import app.models.webhook_delivery  # noqa: F401
from app.api.routes import (
    approvals,
    auth,
    autopilot,
    developer,
    dr,
    iam,
    incidents,
    knowledge,
    unified_risk,
    reliability,
    intelligence,
    multimodal,
    pipeline,
    policies,
    production,
    remediation,
    runtime,
    text_tools,
    webhook,
)
from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.models.pipeline_run import PipelineRun
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.correlation import CorrelationMiddleware
from app.observability.metrics import render_prometheus
from app.services.readiness import readiness_report
from app.services.events import channel_for, event_bus, redis_available
from app.utils.logger import get_logger

logger = get_logger("http")

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
REAPER_INTERVAL_SECONDS = 600
WS_HEARTBEAT_SECONDS = 15
STARTED_AT = time.monotonic()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from app.observability.metrics import http_request_duration_seconds, http_requests_total

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request failed: %s %s", request.method, request.url.path)
            raise
        duration = (time.perf_counter() - start) * 1000
        elapsed_s = duration / 1000.0
        route = request.url.path.split("?")[0]
        status_code = str(getattr(response, "status_code", 500))
        http_requests_total.inc(method=request.method, route=route, status=status_code)
        http_request_duration_seconds.observe(elapsed_s, method=request.method, route=route)
        logger.info(
            "%s %s -> %s in %.2fms",
            request.method,
            request.url.path,
            status_code,
            duration,
        )
        return response


async def _reaper_loop() -> None:
    from app.tasks.pipeline_tasks import reap_stale_runs
    from app.services.workdir_manager import sweep_stale_workdirs

    while True:
        await asyncio.sleep(REAPER_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(reap_stale_runs)
            active = await _active_pipeline_run_ids()
            removed = await asyncio.to_thread(sweep_stale_workdirs, active)
            if removed:
                logger.info("stale workspace reaper removed %d director(ies)", removed)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            logger.warning("stale-run reaper failed: %s", exc)


async def _active_pipeline_run_ids() -> set[str]:
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.pipeline_run import TERMINAL_STATUSES, PipelineRun

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(PipelineRun.id).where(PipelineRun.status.not_in(TERMINAL_STATUSES))
            )
        ).scalars().all()
    return {str(run_id) for run_id in rows}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from app.tasks.dispatch import dispatch_pipeline, executor_mode, recover_interrupted_runs

    logger.info("Starting AI CI/CD Pipeline server (APP_ENV=%s)", settings.app_env)
    settings.validate_startup()
    db_ready = False
    try:
        await init_db()
        db_ready = True
    except Exception as exc:
        logger.error("Database init failed: %s", exc)
        if settings.is_production:
            raise
        logger.warning(
            "Continuing without DB (development only). Start PostgreSQL and align "
            "DATABASE_URL in .env, or use DATABASE_URL=sqlite+aiosqlite:///./orion.db"
        )

    reaper: asyncio.Task[None] | None = None
    mode = executor_mode()
    logger.info("pipeline executor: %s", mode)
    if db_ready:
        from app.services.workdir_manager import recover_pipeline_workdirs_at_startup

        await recover_pipeline_workdirs_at_startup()
    if mode == "inline" and db_ready:
        # No Celery worker or beat in this mode: this process owns recovery and stale-run reaping.
        for run_id in await recover_interrupted_runs():
            dispatch_pipeline(run_id)
        reaper = asyncio.create_task(_reaper_loop(), name="stale-run-reaper")
    yield
    if reaper is not None:
        reaper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper
    logger.info("Shutting down")


app = FastAPI(
    title="ORION AI CI/CD Pipeline",
    version="1.0.0",
    description="Autonomous AI-powered CI/CD pipeline with multi-agent orchestration",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    max_age=settings.oauth_token_expiry_hours * 3600,
    same_site="none" if settings.use_secure_session_cookies else "lax",
    https_only=settings.use_secure_session_cookies,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_OAUTH_HOST_REDIRECT_PREFIXES = ("/api/v1/auth", "/ui")


@app.middleware("http")
async def normalize_oauth_host(request: Request, call_next):
    """Redirect 127.0.0.1 → localhost for OAuth/UI only (session cookies + GitHub callback parity)."""
    redirect_uri = (settings.github_redirect_uri or "").lower()
    frontend = (settings.frontend_url or "").lower()
    if "localhost" not in redirect_uri and "localhost" not in frontend:
        return await call_next(request)
    path = request.url.path
    if not any(path == prefix or path.startswith(f"{prefix}/") for prefix in _OAUTH_HOST_REDIRECT_PREFIXES):
        return await call_next(request)
    host = (request.headers.get("host") or "").lower()
    if not host.startswith("127.0.0.1:"):
        return await call_next(request)
    port = host.split(":", 1)[1]
    query = request.url.query
    target = f"http://localhost:{port}{path}"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(url=target, status_code=307)


app.add_middleware(CorrelationMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    max_requests=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window_seconds,
    redis_url=settings.redis_url,
    backend=settings.rate_limit_backend,
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(webhook.router, prefix="/api/v1")
app.include_router(pipeline.router, prefix="/api/v1")
app.include_router(text_tools.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")
app.include_router(incidents.router, prefix="/api/v1")
app.include_router(remediation.router, prefix="/api/v1")
app.include_router(policies.router, prefix="/api/v1")
app.include_router(approvals.router, prefix="/api/v1")
app.include_router(runtime.router, prefix="/api/v1")
app.include_router(developer.router, prefix="/api/v1")
app.include_router(iam.router, prefix="/api/v1")
app.include_router(reliability.router, prefix="/api/v1")
app.include_router(dr.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(autopilot.router, prefix="/api/v1")
app.include_router(unified_risk.router, prefix="/api/v1")
app.include_router(production.router, prefix="/api/v1")
app.include_router(multimodal.router, prefix="/api/v1")

if FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")


@app.get("/")
async def root(request: Request) -> Any:
    if FRONTEND_DIR.is_dir() and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/ui/")
    return {"name": "ORION AI CI/CD Pipeline API", "version": "1.0.0", "docs": "/docs", "dashboard": "/ui/"}


@app.get("/health")
async def health() -> dict[str, Any]:
    from app.agents.base_agent import llm_status
    from app.agents.deployment_agent import resolved_deploy_mode
    from app.services.events import redis_available
    from app.tasks.dispatch import executor_mode

    redis_ok = await asyncio.to_thread(redis_available)
    payload: dict[str, Any] = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(time.monotonic() - STARTED_AT),
        "environment": settings.app_env,
    }
    if not settings.is_production:
        missing_settings = settings.validate_settings_integrity()
        payload.update(
            llm_mode="live" if settings.llm_enabled else "heuristic",
            llm=llm_status(),
            github_integration=settings.github_enabled,
            slack_integration=settings.slack_enabled,
            executor=executor_mode(),
            redis=redis_ok,
            deploy_mode=await asyncio.to_thread(resolved_deploy_mode),
            api_require_auth=settings.api_require_auth,
            settings_schema_ok=len(missing_settings) == 0,
            settings_schema_missing=missing_settings,
        )
    return payload


@app.get("/ready")
async def ready() -> JSONResponse:
    report = await readiness_report()
    status_code = 200 if report.get("ready") else 503
    return JSONResponse(report, status_code=status_code)


@app.get("/metrics")
async def metrics() -> Any:
    from starlette.responses import PlainTextResponse

    return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")


async def _relay_redis(channel: str, websocket: WebSocket) -> None:
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(channel)
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message" and isinstance(message.get("data"), str):
                await websocket.send_text(message["data"])
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await client.aclose()


@app.websocket("/ws/pipeline/{pipeline_id}")
async def pipeline_ws(websocket: WebSocket, pipeline_id: str) -> None:
    if not await auth.ws_require_auth(websocket):
        await websocket.close(code=4401, reason="Authentication required")
        return
    await websocket.accept()
    try:
        run_uuid = uuid.UUID(pipeline_id)
    except ValueError:
        await websocket.close(code=4400)
        return

    channel = channel_for(run_uuid)
    queue, history = event_bus.subscribe(channel)
    relay: asyncio.Task[None] | None = None
    try:
        snapshot: dict[str, Any] = {"kind": "snapshot", "run_id": pipeline_id, "status": None}
        with contextlib.suppress(Exception):
            async with AsyncSessionLocal() as db:
                run = await db.get(PipelineRun, run_uuid)
                if run is not None:
                    snapshot.update(status=run.status, error_message=run.error_message)
        await websocket.send_text(json.dumps(snapshot))
        for message in history:
            await websocket.send_text(message)

        if await asyncio.to_thread(redis_available):
            relay = asyncio.create_task(_relay_redis(channel, websocket))
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=WS_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                message = json.dumps({"kind": "heartbeat", "run_id": pipeline_id})
            await websocket.send_text(message)
    except WebSocketDisconnect:
        logger.info("websocket disconnected pipeline=%s", pipeline_id)
    except Exception as exc:  # noqa: BLE001 - sends to a closed socket raise transport-specific errors
        logger.info("websocket closed pipeline=%s (%s)", pipeline_id, type(exc).__name__)
    finally:
        event_bus.unsubscribe(channel, queue)
        if relay is not None:
            relay.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await relay


@app.exception_handler(Exception)
async def global_exc(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled: %s\n%s", exc, traceback.format_exc())
    content: dict[str, Any] = {"detail": "Internal server error"}
    if not settings.is_production:
        content["error"] = str(exc)
    return JSONResponse(status_code=500, content=content)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.app_port, reload=True)

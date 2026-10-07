import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import create_engine, text

from app.middleware.rate_limit import RateLimitMiddleware
from app.config import get_settings
from app.database import Base
import app.models  # noqa: F401 — register ORM metadata
from app.database import async_session_factory, engine
from app.redis_events import spawn_redis_subscriber
from app.routers import intelligence, multimodal_proxy, pipelines, runtime, text_tools, webhooks, ws
from app.ws_manager import ws_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

subscriber_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global subscriber_task
    settings = get_settings()
    settings.validate_startup()
    sync_eng = create_engine(settings.sync_database_url, pool_pre_ping=True)
    Base.metadata.create_all(bind=sync_eng)
    sync_eng.dispose()
    subscriber_task = spawn_redis_subscriber(ws_manager)
    yield
    if subscriber_task:
        subscriber_task.cancel()
        try:
            await subscriber_task
        except asyncio.CancelledError:
            pass
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Multi-Agent DevOps Platform", lifespan=lifespan)

    app.add_middleware(
        RateLimitMiddleware,
        max_requests=settings.rate_limit_requests,
        window_seconds=60,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5180",
            "http://127.0.0.1:5180",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    from app.middleware.correlation import CorrelationMiddleware

    app.add_middleware(CorrelationMiddleware)

    app.include_router(webhooks.router)
    app.include_router(pipelines.router)
    app.include_router(text_tools.router)
    app.include_router(multimodal_proxy.router)
    app.include_router(intelligence.router)
    app.include_router(runtime.router, prefix="/api")
    app.include_router(ws.router)

    @app.get("/health")
    async def health() -> dict:
        from app.agents.deployment import resolved_deploy_mode
        from app.auth import expected_api_key
        from app.orchestrator.dispatch import executor_mode, redis_available

        db_ok = "ok"
        redis_ok = "ok"
        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as e:
            logger.warning("db health: %s", e)
            db_ok = "error"
        try:
            r = aioredis.from_url(settings.redis_url)
            await r.ping()
            await r.aclose()
        except Exception as e:
            logger.warning("redis health: %s", e)
            redis_ok = "error"

        return {
            "api": "ok",
            "db": db_ok,
            "redis": redis_ok,
            "deploy_mode": resolved_deploy_mode(),
            "executor": executor_mode(),
            "redis_available": redis_available(),
            "api_require_auth": settings.api_require_auth,
            "api_key_configured": bool(expected_api_key()),
        }

    @app.get("/ready")
    async def ready() -> JSONResponse:
        db_ok = True
        redis_ok = True
        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        try:
            r = aioredis.from_url(settings.redis_url)
            await r.ping()
            await r.aclose()
        except Exception:
            redis_ok = False
        ready_flag = db_ok
        return JSONResponse(
            {
                "ready": ready_flag,
                "checks": {
                    "database": {"ok": db_ok},
                    "redis": {"ok": redis_ok},
                },
            },
            status_code=200 if ready_flag else 503,
        )

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            "# HELP devops_platform_up Platform process is running\n"
            "# TYPE devops_platform_up gauge\n"
            "devops_platform_up 1\n",
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


app = create_app()

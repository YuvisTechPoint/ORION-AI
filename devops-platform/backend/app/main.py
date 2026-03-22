import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.database import Base
import app.models  # noqa: F401 — register ORM metadata
from app.database import async_session_factory, engine
from app.redis_events import spawn_redis_subscriber
from app.routers import pipelines, webhooks, ws
from app.ws_manager import ws_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

subscriber_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global subscriber_task
    settings = get_settings()
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
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhooks.router)
    app.include_router(pipelines.router)
    app.include_router(ws.router)

    @app.get("/health")
    async def health() -> dict:
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

        return {"api": "ok", "db": db_ok, "redis": redis_ok}

    return app


app = create_app()

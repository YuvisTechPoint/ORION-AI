import asyncio
import time
import traceback
import uuid

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import auth, multimodal, pipeline, webhook
from app.config import settings
from app.database import init_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request failed: %s %s", request.method, request.url.path)
            raise
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s in %.2fms",
            request.method,
            request.url.path,
            getattr(response, "status_code", "?"),
            duration,
        )
        return response


app = FastAPI(title="ORION AI Pipeline", version="1.0.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    max_age=settings.oauth_token_expiry_hours * 3600,
    same_site="none",
    https_only=False,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(webhook.router, prefix="/api/v1")
app.include_router(pipeline.router, prefix="/api/v1")
app.include_router(multimodal.router, prefix="/api/v1")


@app.on_event("startup")
async def on_startup() -> None:
    try:
        await init_db()
    except Exception as exc:
        logger.error("Database init failed: %s", exc)
        if settings.is_production:
            raise
        logger.warning(
            "Continuing without DB (development only). Start PostgreSQL and align "
            "DATABASE_URL in .env, or run: docker compose up -d postgres redis"
        )


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "ORION AI Pipeline", "version": "1.0.0", "docs": "/docs"}


@app.websocket("/ws/pipeline/{pipeline_id}")
async def pipeline_ws(websocket: WebSocket, pipeline_id: str) -> None:
    await websocket.accept()
    try:
        uuid.UUID(pipeline_id)
    except ValueError:
        await websocket.close(code=4400)
        return

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(f"pipeline:{pipeline_id}")
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message.get("type") == "message":
                data = message.get("data")
                if isinstance(data, str):
                    await websocket.send_text(data)
            await asyncio.sleep(0.02)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(f"pipeline:{pipeline_id}")
        await pubsub.close()
        await r.aclose()


@app.exception_handler(Exception)
async def global_exc(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

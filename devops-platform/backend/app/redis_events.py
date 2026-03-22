"""Async Redis subscriber — forwards Celery-published events to WebSocket clients."""

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import redis.asyncio as aioredis

from app.config import get_settings

if TYPE_CHECKING:
    from app.ws_manager import WebSocketManager

logger = logging.getLogger(__name__)

CHANNEL = "pipeline_events"


async def _redis_loop(ws_manager: "WebSocketManager") -> None:
    settings = get_settings()
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
                pid = data["pipeline_id"]
                ev = data["event"]
                for ws in list(ws_manager._connections.get(pid, [])):
                    try:
                        await ws.send_text(json.dumps(ev, default=str))
                    except Exception:
                        continue
            except Exception as e:
                logger.warning("redis subscriber: %s", e)
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await r.aclose()


def spawn_redis_subscriber(ws_manager: "WebSocketManager") -> asyncio.Task:
    return asyncio.create_task(_redis_loop(ws_manager))

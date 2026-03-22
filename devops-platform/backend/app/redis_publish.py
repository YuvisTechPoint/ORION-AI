"""Sync Redis publish — safe to call from Celery workers and via asyncio.to_thread in FastAPI."""

import json
import logging

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL = "pipeline_events"


def publish_pipeline_event(pipeline_id: str, event: dict) -> None:
    settings = get_settings()
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        payload = json.dumps({"pipeline_id": pipeline_id, "event": event}, default=str)
        r.publish(CHANNEL, payload)
    except Exception as e:
        logger.warning("redis publish failed: %s", e)
    finally:
        r.close()

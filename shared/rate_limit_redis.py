"""Redis-backed fixed-window rate limiter for multi-worker HTTP abuse protection."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_CLIENT: Any | None = None
_REDIS_URL: str | None = None
_REDIS_AVAILABLE: bool | None = None


def redis_rate_limit_available(redis_url: str | None) -> bool:
    global _REDIS_AVAILABLE, _REDIS_URL
    url = (redis_url or "").strip()
    if not url:
        _REDIS_AVAILABLE = False
        return False
    if _REDIS_AVAILABLE is not None and _REDIS_URL == url:
        return _REDIS_AVAILABLE
    _REDIS_URL = url
    try:
        import redis

        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=1.0)
        client.ping()
        _REDIS_AVAILABLE = True
    except Exception as exc:  # noqa: BLE001
        logger.debug("redis rate limit unavailable: %s", exc)
        _REDIS_AVAILABLE = False
    return _REDIS_AVAILABLE


def _client(redis_url: str) -> Any:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        import redis

        _REDIS_CLIENT = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1.0)
    return _REDIS_CLIENT


def redis_rate_limit_allow(
    redis_url: str,
    key: str,
    *,
    max_requests: int,
    window_seconds: int,
    namespace: str = "orion:rate",
) -> bool | None:
    """Return True/False when Redis is used; None when Redis is unavailable."""
    if not redis_rate_limit_available(redis_url):
        return None
    try:
        client = _client(redis_url)
        now = int(time.time())
        bucket = f"{namespace}:{key}:{now // window_seconds}"
        count = client.incr(bucket)
        if count == 1:
            client.expire(bucket, window_seconds + 1)
        return count <= max_requests
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis rate limit error, falling back to memory: %s", exc)
        return None

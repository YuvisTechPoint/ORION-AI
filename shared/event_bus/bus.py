"""Event bus with in-memory and Redis Streams backends."""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Protocol

from shared.event_bus.models import PlatformEvent

logger = logging.getLogger(__name__)

STREAM_KEY = "orion:platform:events"
_HISTORY_MAX = 500


class PlatformEventBus(Protocol):
    def publish(self, event: PlatformEvent) -> str: ...

    def recent(self, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]: ...


class InMemoryPlatformEventBus:
    def __init__(self) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=_HISTORY_MAX)

    def publish(self, event: PlatformEvent) -> str:
        data = event.to_dict()
        self._events.append(data)
        return event.event_id

    def recent(self, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
        items = list(self._events)
        if event_type:
            items = [e for e in items if e.get("event_type") == event_type]
        return items[-limit:]


class RedisStreamPlatformEventBus:
    def __init__(self, redis_url: str) -> None:
        import redis

        self._client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1.0)
        self._fallback = InMemoryPlatformEventBus()

    def publish(self, event: PlatformEvent) -> str:
        data = event.to_dict()
        try:
            self._client.xadd(STREAM_KEY, {"json": json.dumps(data, default=str)}, maxlen=10000, approximate=True)
            return event.event_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis stream publish failed, using in-memory fallback: %s", exc)
            return self._fallback.publish(event)

    def recent(self, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
        try:
            rows = self._client.xrevrange(STREAM_KEY, count=limit * 2)
            out: list[dict[str, Any]] = []
            for _id, fields in rows:
                raw = fields.get("json")
                if not raw:
                    continue
                item = json.loads(raw)
                if event_type and item.get("event_type") != event_type:
                    continue
                out.append(item)
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return self._fallback.recent(limit=limit, event_type=event_type)


def build_platform_event_bus(redis_url: str | None, backend: str = "auto") -> PlatformEventBus:
    mode = (backend or "auto").strip().lower()
    url = (redis_url or "").strip()
    if mode == "memory":
        return InMemoryPlatformEventBus()
    if mode in {"redis", "auto"} and url:
        try:
            return RedisStreamPlatformEventBus(url)
        except Exception:
            pass
    return InMemoryPlatformEventBus()

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Protocol

LOGGER = logging.getLogger(__name__)

try:
    from redis.asyncio import Redis
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import RedisError
except Exception:  # noqa: BLE001
    Redis = None
    RedisConnectionError = Exception
    RedisError = Exception


class EventBus(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        ...

    async def consume(self, topic: str, timeout: float | None = None) -> dict[str, Any]:
        ...


class InMemoryEventBus:
    """Simple event bus for local MVP; replaceable with Redis pub/sub later."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Any]] = defaultdict(asyncio.Queue)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        await self._queues[topic].put(payload)

    async def consume(self, topic: str, timeout: float | None = None) -> dict[str, Any]:
        if timeout is None:
            payload = await self._queues[topic].get()
            return payload
        try:
            payload = await asyncio.wait_for(self._queues[topic].get(), timeout=timeout)
            return payload
        except asyncio.TimeoutError:
            return {}


class RedisEventBus:
    """Redis-backed queue abstraction using list push/pop semantics."""

    def __init__(self, redis_url: str) -> None:
        if Redis is None:
            raise RuntimeError("redis package is not installed")
        self._client = Redis.from_url(redis_url, decode_responses=True)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        try:
            await self._client.rpush(topic, json.dumps(payload))
        except (RedisConnectionError, RedisError) as exc:
            LOGGER.warning("Redis publish failed topic=%s error=%s", topic, exc)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Redis publish failed topic=%s error=%s", topic, exc)

    async def consume(self, topic: str, timeout: float | None = None) -> dict[str, Any]:
        redis_timeout = 0 if timeout is None else max(1, int(timeout))
        try:
            item = await self._client.blpop(topic, timeout=redis_timeout)
        except (RedisConnectionError, RedisError) as exc:
            LOGGER.warning("Redis consume failed topic=%s error=%s", topic, exc)
            return {}
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Redis consume failed topic=%s error=%s", topic, exc)
            return {}
        if not item:
            return {}
        _, raw = item
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("Invalid JSON payload in Redis queue topic=%s", topic)
            return {"raw": raw}


def build_event_bus(backend: str, redis_url: str) -> EventBus:
    normalized = backend.strip().lower()
    if normalized == "redis":
        try:
            return RedisEventBus(redis_url=redis_url)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Falling back to memory queue because Redis init failed: %s", exc)
    return InMemoryEventBus()

"""Live pipeline events.

Events always go to an in-process bus (consumed by the WebSocket endpoint of the same API process).
Celery workers run in separate processes, so when publishing from a worker the event is also sent
over Redis pub/sub; the API's WebSocket endpoint relays both sources.
"""

import asyncio
import json
import threading
import time
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any

import redis

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("events")

HISTORY_PER_RUN = 200
MAX_TRACKED_RUNS = 200
_REDIS_OK_TTL = 30.0
_REDIS_DOWN_TTL = 60.0

_redis_state: dict[str, Any] = {"ok": False, "checked": None}
_redis_lock = threading.Lock()
_in_worker = False


def mark_celery_worker() -> None:
    global _in_worker
    _in_worker = True


def redis_available(force: bool = False) -> bool:
    """Cached Redis reachability check (a refused connection can take seconds on Windows)."""
    with _redis_lock:
        checked = _redis_state["checked"]
        ttl = _REDIS_OK_TTL if _redis_state["ok"] else _REDIS_DOWN_TTL
        if not force and checked is not None and time.monotonic() - checked < ttl:
            return bool(_redis_state["ok"])
    ok = False
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        ok = bool(client.ping())
        client.close()
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        ok = False
    with _redis_lock:
        if ok != _redis_state["ok"] or _redis_state["checked"] is None:
            logger.info("redis at %s is %s", settings.redis_url, "reachable" if ok else "unreachable")
        _redis_state.update(ok=ok, checked=time.monotonic())
    return ok


def channel_for(run_id: uuid.UUID | str) -> str:
    return f"pipeline:{run_id}"


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str]]]] = {}
        self._history: OrderedDict[str, deque[str]] = OrderedDict()

    def subscribe(self, channel: str) -> tuple[asyncio.Queue[str], list[str]]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers.setdefault(channel, set()).add((loop, queue))
            history = list(self._history.get(channel, ()))
        return queue, history

    def unsubscribe(self, channel: str, queue: asyncio.Queue[str]) -> None:
        with self._lock:
            subs = self._subscribers.get(channel, set())
            for entry in [e for e in subs if e[1] is queue]:
                subs.discard(entry)
            if not subs:
                self._subscribers.pop(channel, None)

    def publish(self, channel: str, message: str) -> None:
        with self._lock:
            history = self._history.setdefault(channel, deque(maxlen=HISTORY_PER_RUN))
            history.append(message)
            self._history.move_to_end(channel)
            while len(self._history) > MAX_TRACKED_RUNS:
                self._history.popitem(last=False)
            subscribers = list(self._subscribers.get(channel, ()))
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_offer, queue, message)
            except RuntimeError:
                self.unsubscribe(channel, queue)


def _offer(queue: asyncio.Queue[str], message: str) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(message)


event_bus = EventBus()


def publish_event(run_id: uuid.UUID | str, message: dict[str, Any]) -> None:
    payload = json.dumps(
        {"run_id": str(run_id), "ts": datetime.now(timezone.utc).isoformat(), **message}, default=str
    )
    channel = channel_for(run_id)
    event_bus.publish(channel, payload)
    if _in_worker and redis_available():
        try:
            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
            client.publish(channel, payload)
            client.close()
        except Exception as exc:  # noqa: BLE001 - live updates are best-effort
            logger.debug("redis publish failed: %s", exc)

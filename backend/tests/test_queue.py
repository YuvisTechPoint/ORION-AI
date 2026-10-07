import pytest

from core.queue import InMemoryEventBus, RedisEventBus, build_event_bus


@pytest.mark.asyncio
async def test_in_memory_event_bus_publish_consume() -> None:
    bus = InMemoryEventBus()
    payload = {"pipeline_id": "p-1", "stage": "qa"}

    await bus.publish("pipeline:p-1", payload)
    received = await bus.consume("pipeline:p-1", timeout=0.1)

    assert received == payload


@pytest.mark.asyncio
async def test_redis_event_bus_publish_consume(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRedisClient:
        def __init__(self) -> None:
            self.storage: dict[str, list[str]] = {}

        async def rpush(self, topic: str, value: str) -> None:
            self.storage.setdefault(topic, []).append(value)

        async def blpop(self, topic: str, timeout: int = 0):
            values = self.storage.get(topic, [])
            if not values:
                return None
            return (topic, values.pop(0))

    class FakeRedisFactory:
        @staticmethod
        def from_url(redis_url: str, decode_responses: bool = True) -> FakeRedisClient:
            assert redis_url.startswith("redis://")
            assert decode_responses is True
            return FakeRedisClient()

    monkeypatch.setattr("core.queue.Redis", FakeRedisFactory)

    bus = RedisEventBus("redis://redis:6379/0")
    await bus.publish("pipeline:p-2", {"pipeline_id": "p-2", "stage": "deployment"})
    received = await bus.consume("pipeline:p-2", timeout=1.0)

    assert received["pipeline_id"] == "p-2"
    assert received["stage"] == "deployment"


def test_build_event_bus_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenRedisFactory:
        @staticmethod
        def from_url(redis_url: str, decode_responses: bool = True):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr("core.queue.Redis", BrokenRedisFactory)

    bus = build_event_bus("redis", "redis://redis:6379/0")
    assert isinstance(bus, InMemoryEventBus)

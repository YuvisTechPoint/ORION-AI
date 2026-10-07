"""Platform event backbone — ORION-ARCH-001 §5.3."""

from __future__ import annotations

from shared.event_bus.bus import InMemoryPlatformEventBus
from shared.event_bus.models import PlatformEvent


def test_publish_and_recent():
    bus = InMemoryPlatformEventBus()
    event_id = bus.publish(
        PlatformEvent(
            event_type="pipeline.completed",
            correlation_id="corr-1",
            tenant_id="acme",
            payload={"run_id": "abc", "status": "deployed"},
        )
    )
    assert event_id
    items = bus.recent(limit=10, event_type="pipeline.completed")
    assert len(items) == 1
    assert items[0]["event_type"] == "pipeline.completed"
    assert items[0]["payload"]["status"] == "deployed"


def test_recent_filter_by_type():
    bus = InMemoryPlatformEventBus()
    bus.publish(PlatformEvent(event_type="pipeline.started", correlation_id="c1", payload={}))
    bus.publish(PlatformEvent(event_type="pipeline.completed", correlation_id="c1", payload={}))
    started = bus.recent(limit=10, event_type="pipeline.started")
    assert len(started) == 1
    assert started[0]["event_type"] == "pipeline.started"

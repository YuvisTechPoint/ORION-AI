"""Platform event backbone publisher (ORION-ARCH-001 §5.3)."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import settings

from shared.event_bus.bus import build_platform_event_bus
from shared.event_bus.models import PlatformEvent


@lru_cache
def get_platform_event_bus():
    return build_platform_event_bus(settings.redis_url, settings.event_bus_backend)


def publish_platform_event(
    event_type: str,
    *,
    correlation_id: str,
    payload: dict[str, Any],
    tenant_id: str = "default",
    trace_id: str | None = None,
    source_stack: str = "orion",
) -> str:
    if not settings.event_bus_enabled:
        return ""
    event = PlatformEvent(
        event_type=event_type,
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        trace_id=trace_id,
        source_stack=source_stack,
        payload=payload,
    )
    return get_platform_event_bus().publish(event)

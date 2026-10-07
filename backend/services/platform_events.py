"""Canonical platform event publisher — ORION-ARCH-001 §5.3."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.event_bus.bus import build_platform_event_bus
from shared.event_bus.models import PlatformEvent


def _enabled() -> bool:
    return os.getenv("EVENT_BUS_ENABLED", "true").lower() in {"1", "true", "yes"}


@lru_cache
def get_platform_event_bus():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    backend = os.getenv("EVENT_BUS_BACKEND", "auto")
    return build_platform_event_bus(redis_url, backend)


def publish_platform_event(
    event_type: str,
    *,
    correlation_id: str,
    payload: dict[str, Any],
    tenant_id: str = "default",
    trace_id: str | None = None,
    source_stack: str = "canonical",
) -> str:
    if not _enabled():
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

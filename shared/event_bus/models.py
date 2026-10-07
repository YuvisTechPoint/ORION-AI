"""Canonical platform events — Table 7 ORION-ARCH-001."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class PlatformEvent:
    event_type: str
    correlation_id: str
    tenant_id: str = "default"
    trace_id: str | None = None
    source_stack: str = "orion"
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "source_stack": self.source_stack,
            "occurred_at": self.occurred_at,
            "schema_version": self.schema_version,
            "payload": self.payload,
        }

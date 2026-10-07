"""Canonical stack Memory Gateway client — ORION-ARCH-001 §6.11."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.memory_gateway.gateway import MemoryGateway, MemoryGatewayConfig
from shared.memory_gateway.models import MemoryReadRequest, MemoryWriteRequest


def _enabled() -> bool:
    return os.getenv("MEMORY_GATEWAY_ENABLED", "true").lower() in {"1", "true", "yes"}


@lru_cache
def get_memory_gateway() -> MemoryGateway:
    cfg = MemoryGatewayConfig(
        enabled=_enabled(),
        backend=os.getenv("MEMORY_BACKEND", "sqlite"),
        sqlite_path=os.getenv("MEMORY_SQLITE_PATH", ".local/orion-memory.db"),
        min_confidence=float(os.getenv("MEMORY_MIN_CONFIDENCE", "0.5")),
        quarantine_enabled=os.getenv("MEMORY_QUARANTINE_ENABLED", "true").lower() in {"1", "true", "yes"},
        context_token_budget=int(os.getenv("MEMORY_CONTEXT_TOKEN_BUDGET", "3000")),
    )
    return MemoryGateway(cfg)


def write_memory_record(request: MemoryWriteRequest) -> dict[str, Any]:
    return get_memory_gateway().write(request)


def read_memory_context(
    *,
    tenant_id: str,
    namespace_prefix: str,
    query: str = "",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    req = MemoryReadRequest(
        tenant_id=tenant_id,
        namespace_prefix=namespace_prefix,
        query=query,
        correlation_id=correlation_id,
        actor="canonical_runtime",
        purpose="context_injection",
    )
    return get_memory_gateway().read(req)

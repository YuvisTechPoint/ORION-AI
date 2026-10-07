"""Memory record models per ORION-ARCH-001 Table 11."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class MemoryLayer(str, Enum):
    L1_WORKING = "L1"
    L2_EPISODIC = "L2"
    L3_SEMANTIC = "L3"
    L4_PROCEDURAL = "L4"
    L5_ORGANIZATIONAL = "L5"
    L6_DECISION = "L6"


class TrustLevel(str, Enum):
    VERIFIED = "verified"
    DERIVED = "derived"
    UNVERIFIED = "unverified"


class RecordStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"
    EXPIRED = "expired"
    DELETED = "deleted"


@dataclass
class MemoryRecord:
    record_id: str
    tenant_id: str
    namespace: str
    layer: str
    kind: str
    title: str
    body: str
    structured: dict[str, Any] = field(default_factory=dict)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    trust_level: str = TrustLevel.DERIVED.value
    confidence: float = 0.7
    content_hash: str = ""
    created_at: str = ""
    updated_at: str = ""
    expires_at: str | None = None
    status: str = RecordStatus.ACTIVE.value
    correlation_id: str | None = None
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "tenant_id": self.tenant_id,
            "namespace": self.namespace,
            "layer": self.layer,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "structured": self.structured,
            "source_refs": self.source_refs,
            "provenance": self.provenance,
            "trust_level": self.trust_level,
            "confidence": self.confidence,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
        }


@dataclass
class MemoryWriteRequest:
    tenant_id: str
    namespace: str
    layer: str
    kind: str
    title: str
    body: str
    structured: dict[str, Any] = field(default_factory=dict)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    trust_level: str = TrustLevel.DERIVED.value
    confidence: float = 0.7
    actor: str = "system"
    purpose: str = "pipeline_extract"
    correlation_id: str | None = None
    trace_id: str | None = None
    ttl_days: int | None = None


@dataclass
class MemoryReadRequest:
    tenant_id: str
    namespace_prefix: str
    query: str = ""
    layers: list[str] | None = None
    min_confidence: float = 0.5
    top_k: int = 8
    actor: str = "agent"
    purpose: str = "context_injection"
    correlation_id: str | None = None
    include_unverified: bool = False


def new_record_id() -> str:
    return str(uuid4())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

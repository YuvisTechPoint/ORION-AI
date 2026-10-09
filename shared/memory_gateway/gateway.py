"""Memory Gateway — single governed interface (MEM-01)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.memory_gateway.config import MemoryGatewayConfig
from shared.memory_gateway.models import (
    MemoryReadRequest,
    MemoryRecord,
    MemoryWriteRequest,
    RecordStatus,
    TrustLevel,
    new_record_id,
    utc_now_iso,
)
from shared.memory_gateway.redaction import looks_like_injection, prepare_memory_body
from shared.memory_gateway.factory import build_memory_store


class MemoryGateway:
    """All memory reads and writes MUST pass through this gateway (MEM-01)."""

    def __init__(
        self,
        config: MemoryGatewayConfig,
        store: object | None = None,
        *,
        fallback_database_url: str | None = None,
    ) -> None:
        self.config = config
        self._store = store or build_memory_store(config, fallback_database_url)

    @property
    def store(self) -> object:
        return self._store

    def write(self, request: MemoryWriteRequest) -> dict[str, Any]:
        if not self.config.enabled:
            return {"written": False, "reason": "memory_disabled"}

        body = prepare_memory_body(request.body, fail_closed=True)
        title = prepare_memory_body(request.title, fail_closed=True)
        content_hash = self._store.content_hash(body, request.structured)

        if self.config.quarantine_enabled and (looks_like_injection(body) or looks_like_injection(title)):
            record_id = new_record_id()
            self._store.quarantine(
                record_id,
                request.tenant_id,
                "injection_signature",
                {"title": title, "namespace": request.namespace, "kind": request.kind},
            )
            self._store.audit(
                action="write_quarantined",
                tenant_id=request.tenant_id,
                actor=request.actor,
                purpose=request.purpose,
                record_id=record_id,
                correlation_id=request.correlation_id,
                detail={"reason": "injection_signature"},
            )
            return {"written": False, "quarantined": True, "record_id": record_id}

        existing = self._store.find_by_hash(request.tenant_id, content_hash)
        if existing:
            self._store.audit(
                action="write_deduplicated",
                tenant_id=request.tenant_id,
                actor=request.actor,
                purpose=request.purpose,
                record_id=existing.record_id,
                correlation_id=request.correlation_id,
            )
            return {"written": False, "deduplicated": True, "record_id": existing.record_id}

        now = utc_now_iso()
        expires = None
        if request.ttl_days:
            expires = (datetime.now(timezone.utc) + timedelta(days=request.ttl_days)).isoformat()
        elif request.layer == "L2":
            expires = (datetime.now(timezone.utc) + timedelta(days=self.config.episodic_ttl_days)).isoformat()

        record = MemoryRecord(
            record_id=new_record_id(),
            tenant_id=request.tenant_id,
            namespace=request.namespace,
            layer=request.layer,
            kind=request.kind,
            title=title[:500],
            body=body[:20000],
            structured=request.structured,
            source_refs=request.source_refs,
            provenance=request.provenance,
            trust_level=request.trust_level,
            confidence=max(0.0, min(1.0, request.confidence)),
            content_hash=content_hash,
            created_at=now,
            updated_at=now,
            expires_at=expires,
            status=RecordStatus.ACTIVE.value,
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
        )
        self._store.insert(record)
        self._store.audit(
            action="write",
            tenant_id=request.tenant_id,
            actor=request.actor,
            purpose=request.purpose,
            record_id=record.record_id,
            correlation_id=request.correlation_id,
            detail={"namespace": record.namespace, "kind": record.kind, "layer": record.layer},
        )
        return {"written": True, "record_id": record.record_id, "event": "memory.written"}

    def read(self, request: MemoryReadRequest) -> dict[str, Any]:
        if not self.config.enabled:
            return {"records": [], "degraded": False, "reason": "memory_disabled"}

        records = self._store.search(
            tenant_id=request.tenant_id,
            namespace_prefix=request.namespace_prefix,
            query=request.query,
            layers=request.layers,
            min_confidence=max(request.min_confidence, self.config.min_confidence),
            top_k=request.top_k,
            include_unverified=request.include_unverified,
        )
        packed = self._pack_context(records)
        self._store.audit(
            action="read",
            tenant_id=request.tenant_id,
            actor=request.actor,
            purpose=request.purpose,
            correlation_id=request.correlation_id,
            detail={"hits": len(records), "query": request.query[:120]},
        )
        return {
            "records": [r.to_dict() for r in records],
            "context": packed,
            "degraded": False,
            "advisory_only": True,
            "summary": f"Retrieved {len(records)} memory record(s) for {request.namespace_prefix}",
        }

    def _pack_context(self, records: list[MemoryRecord]) -> str:
        """MEM-04: wrap as untrusted reference data for agent injection."""
        blocks: list[str] = []
        budget = self.config.context_token_budget
        used = 0
        for rec in records:
            block = (
                f"[MEMORY_REF layer={rec.layer} trust={rec.trust_level} confidence={rec.confidence}]\n"
                f"Title: {rec.title}\n"
                f"Namespace: {rec.namespace}\n"
                f"Provenance: {json.dumps(rec.provenance, default=str)[:400]}\n"
                f"Body: {rec.body[:1200]}\n"
                f"[/MEMORY_REF]"
            )
            est = len(block) // 4
            if used + est > budget:
                break
            blocks.append(block)
            used += est
        return "\n\n".join(blocks)

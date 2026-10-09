"""Postgres + pgvector memory store — Wave 4 semantic retrieval (L3)."""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2
import psycopg2.extras

from shared.memory_gateway.embeddings import embed_text
from shared.memory_gateway.models import MemoryRecord, utc_now_iso
from shared.memory_gateway.store import MemorySqliteStore

logger = logging.getLogger(__name__)


class MemoryPgStore:
    """Postgres-backed store with optional pgvector semantic ranking."""

    def __init__(self, database_url: str, *, embedding_dims: int = 384) -> None:
        self._dsn = database_url
        self._embedding_dims = max(32, min(int(embedding_dims), 4096))
        self._vector_enabled = False
        self._conn = psycopg2.connect(self._dsn)
        self._conn.autocommit = True
        self._ensure_schema()

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    def _ensure_schema(self) -> None:
        with self._conn.cursor() as cur:
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                from pgvector.psycopg2 import register_vector

                register_vector(self._conn)
                self._vector_enabled = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("pgvector unavailable; semantic ranking disabled: %s", exc)
                self._vector_enabled = False

            dim = self._embedding_dims
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS memory_records (
                    record_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    structured_json JSONB NOT NULL DEFAULT '{{}}',
                    source_refs_json JSONB NOT NULL DEFAULT '[]',
                    provenance_json JSONB NOT NULL DEFAULT '{{}}',
                    trust_level TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ,
                    status TEXT NOT NULL DEFAULT 'active',
                    correlation_id TEXT,
                    trace_id TEXT,
                    embedding vector({dim})
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_tenant_ns ON memory_records(tenant_id, namespace)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory_records(content_hash)")
            if self._vector_enabled:
                try:
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_memory_embedding
                        ON memory_records USING ivfflat (embedding vector_cosine_ops)
                        WITH (lists = 32)
                        """
                    )
                except Exception:  # noqa: BLE001
                    pass
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_access_log (
                    id BIGSERIAL PRIMARY KEY,
                    action TEXT NOT NULL,
                    record_id TEXT,
                    tenant_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    correlation_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    detail_json JSONB NOT NULL DEFAULT '{}'
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_quarantine (
                    record_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )

    @staticmethod
    def content_hash(body: str, structured: dict[str, Any]) -> str:
        return MemorySqliteStore.content_hash(body, structured)

    def find_by_hash(self, tenant_id: str, content_hash: str) -> MemoryRecord | None:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM memory_records
                WHERE tenant_id = %s AND content_hash = %s AND status = 'active'
                LIMIT 1
                """,
                (tenant_id, content_hash),
            )
            row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def insert(self, record: MemoryRecord) -> None:
        embedding = None
        if record.layer == "L3":
            embedding = embed_text(f"{record.title}\n{record.body}", dimensions=self._embedding_dims)
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_records (
                    record_id, tenant_id, namespace, layer, kind, title, body,
                    structured_json, source_refs_json, provenance_json,
                    trust_level, confidence, content_hash,
                    created_at, updated_at, expires_at, status,
                    correlation_id, trace_id, embedding
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s
                )
                """,
                (
                    record.record_id,
                    record.tenant_id,
                    record.namespace,
                    record.layer,
                    record.kind,
                    record.title,
                    record.body,
                    json.dumps(record.structured, default=str),
                    json.dumps(record.source_refs, default=str),
                    json.dumps(record.provenance, default=str),
                    record.trust_level,
                    record.confidence,
                    record.content_hash,
                    record.created_at,
                    record.updated_at,
                    record.expires_at,
                    record.status,
                    record.correlation_id,
                    record.trace_id,
                    embedding,
                ),
            )

    def quarantine(self, record_id: str, tenant_id: str, reason: str, payload: dict[str, Any]) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_quarantine (record_id, tenant_id, reason, payload_json, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (record_id) DO UPDATE SET
                    reason = EXCLUDED.reason,
                    payload_json = EXCLUDED.payload_json,
                    created_at = EXCLUDED.created_at
                """,
                (record_id, tenant_id, reason, json.dumps(payload, default=str), utc_now_iso()),
            )

    def audit(
        self,
        *,
        action: str,
        tenant_id: str,
        actor: str,
        purpose: str,
        record_id: str | None = None,
        correlation_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_access_log (
                    action, record_id, tenant_id, actor, purpose, correlation_id, created_at, detail_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    action,
                    record_id,
                    tenant_id,
                    actor,
                    purpose,
                    correlation_id,
                    utc_now_iso(),
                    json.dumps(detail or {}, default=str),
                ),
            )

    def search(
        self,
        *,
        tenant_id: str,
        namespace_prefix: str,
        query: str,
        layers: list[str] | None,
        min_confidence: float,
        top_k: int,
        include_unverified: bool,
    ) -> list[MemoryRecord]:
        if query.strip() and self._vector_enabled:
            vector_hits = self._search_vector(
                tenant_id=tenant_id,
                namespace_prefix=namespace_prefix,
                query=query,
                layers=layers,
                min_confidence=min_confidence,
                top_k=top_k,
                include_unverified=include_unverified,
            )
            if vector_hits:
                return vector_hits

        clauses = ["tenant_id = %s", "namespace LIKE %s", "status = 'active'", "confidence >= %s"]
        params: list[Any] = [tenant_id, f"{namespace_prefix}%", min_confidence]
        if not include_unverified:
            clauses.append("trust_level != 'unverified'")
        if layers:
            clauses.append(f"layer IN ({','.join('%s' for _ in layers)})")
            params.extend(layers)
        sql = f"""
            SELECT * FROM memory_records
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC
            LIMIT %s
        """
        params.append(max(top_k * 3, top_k))
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        records = [self._row_to_record(r) for r in rows]
        if query.strip():
            q = query.lower()
            records = [
                r
                for r in records
                if q in r.body.lower() or q in r.title.lower() or q in r.namespace.lower()
            ]
        return records[:top_k]

    def _search_vector(
        self,
        *,
        tenant_id: str,
        namespace_prefix: str,
        query: str,
        layers: list[str] | None,
        min_confidence: float,
        top_k: int,
        include_unverified: bool,
    ) -> list[MemoryRecord]:
        qvec = embed_text(query, dimensions=self._embedding_dims)
        clauses = [
            "tenant_id = %s",
            "namespace LIKE %s",
            "status = 'active'",
            "confidence >= %s",
            "embedding IS NOT NULL",
        ]
        params: list[Any] = [tenant_id, f"{namespace_prefix}%", min_confidence]
        if not include_unverified:
            clauses.append("trust_level != 'unverified'")
        layer_filter = layers or ["L3"]
        clauses.append(f"layer IN ({','.join('%s' for _ in layer_filter)})")
        params.extend(layer_filter)
        sql = f"""
            SELECT *, (embedding <=> %s::vector) AS distance
            FROM memory_records
            WHERE {' AND '.join(clauses)}
            ORDER BY distance ASC
            LIMIT %s
        """
        params = [qvec, *params, top_k]
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            return [self._row_to_record(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("vector search failed, falling back to keyword: %s", exc)
            return []

    @property
    def vector_enabled(self) -> bool:
        return self._vector_enabled

    def _row_to_record(self, row: dict[str, Any]) -> MemoryRecord:
        structured = row.get("structured_json") or {}
        if isinstance(structured, str):
            structured = json.loads(structured or "{}")
        source_refs = row.get("source_refs_json") or []
        if isinstance(source_refs, str):
            source_refs = json.loads(source_refs or "[]")
        provenance = row.get("provenance_json") or {}
        if isinstance(provenance, str):
            provenance = json.loads(provenance or "{}")
        created = row.get("created_at")
        updated = row.get("updated_at")
        expires = row.get("expires_at")
        return MemoryRecord(
            record_id=row["record_id"],
            tenant_id=row["tenant_id"],
            namespace=row["namespace"],
            layer=row["layer"],
            kind=row["kind"],
            title=row["title"],
            body=row["body"],
            structured=structured,
            source_refs=source_refs,
            provenance=provenance,
            trust_level=row["trust_level"],
            confidence=float(row["confidence"]),
            content_hash=row["content_hash"],
            created_at=created.isoformat() if hasattr(created, "isoformat") else str(created),
            updated_at=updated.isoformat() if hasattr(updated, "isoformat") else str(updated),
            expires_at=expires.isoformat() if expires and hasattr(expires, "isoformat") else expires,
            status=row["status"],
            correlation_id=row.get("correlation_id"),
            trace_id=row.get("trace_id"),
        )

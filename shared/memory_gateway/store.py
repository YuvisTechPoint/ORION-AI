"""SQLite memory store — development and local-sim backend."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from shared.memory_gateway.models import MemoryRecord, RecordStatus, utc_now_iso


class MemorySqliteStore:
    def __init__(self, database_path: str) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_records (
                record_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                layer TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                structured_json TEXT NOT NULL DEFAULT '{}',
                source_refs_json TEXT NOT NULL DEFAULT '[]',
                provenance_json TEXT NOT NULL DEFAULT '{}',
                trust_level TEXT NOT NULL,
                confidence REAL NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                correlation_id TEXT,
                trace_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_memory_tenant_ns ON memory_records(tenant_id, namespace);
            CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory_records(content_hash);
            CREATE TABLE IF NOT EXISTS memory_access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                record_id TEXT,
                tenant_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                purpose TEXT NOT NULL,
                correlation_id TEXT,
                created_at TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS memory_quarantine (
                record_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    @staticmethod
    def content_hash(body: str, structured: dict[str, Any]) -> str:
        payload = json.dumps({"body": body, "structured": structured}, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def find_by_hash(self, tenant_id: str, content_hash: str) -> MemoryRecord | None:
        row = self._conn.execute(
            "SELECT * FROM memory_records WHERE tenant_id = ? AND content_hash = ? AND status = 'active' LIMIT 1",
            (tenant_id, content_hash),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def insert(self, record: MemoryRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO memory_records (
                record_id, tenant_id, namespace, layer, kind, title, body,
                structured_json, source_refs_json, provenance_json,
                trust_level, confidence, content_hash,
                created_at, updated_at, expires_at, status,
                correlation_id, trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self._conn.commit()

    def quarantine(self, record_id: str, tenant_id: str, reason: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_quarantine (record_id, tenant_id, reason, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (record_id, tenant_id, reason, json.dumps(payload, default=str), utc_now_iso()),
        )
        self._conn.commit()

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
        self._conn.execute(
            """
            INSERT INTO memory_access_log (action, record_id, tenant_id, actor, purpose, correlation_id, created_at, detail_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        self._conn.commit()

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
        clauses = ["tenant_id = ?", "namespace LIKE ?", "status = 'active'", "confidence >= ?"]
        params: list[Any] = [tenant_id, f"{namespace_prefix}%", min_confidence]
        if not include_unverified:
            clauses.append("trust_level != 'unverified'")
        if layers:
            placeholders = ",".join("?" for _ in layers)
            clauses.append(f"layer IN ({placeholders})")
            params.extend(layers)
        sql = f"SELECT * FROM memory_records WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?"
        params.append(max(top_k * 3, top_k))
        rows = self._conn.execute(sql, params).fetchall()
        records = [self._row_to_record(r) for r in rows]
        if query.strip():
            q = query.lower()
            records = [r for r in records if q in r.body.lower() or q in r.title.lower() or q in r.namespace.lower()]
        return records[:top_k]

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            record_id=row["record_id"],
            tenant_id=row["tenant_id"],
            namespace=row["namespace"],
            layer=row["layer"],
            kind=row["kind"],
            title=row["title"],
            body=row["body"],
            structured=json.loads(row["structured_json"] or "{}"),
            source_refs=json.loads(row["source_refs_json"] or "[]"),
            provenance=json.loads(row["provenance_json"] or "{}"),
            trust_level=row["trust_level"],
            confidence=float(row["confidence"]),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            status=row["status"],
            correlation_id=row["correlation_id"],
            trace_id=row["trace_id"],
        )

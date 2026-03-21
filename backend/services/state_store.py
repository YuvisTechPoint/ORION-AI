import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from models.schemas import PipelineState

LOGGER = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import Json
except Exception:  # noqa: BLE001
    psycopg2 = None
    Json = None


class BaseStateStore(ABC):
    @abstractmethod
    def upsert(self, state: PipelineState) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, pipeline_id: str) -> PipelineState | None:
        raise NotImplementedError

    @abstractmethod
    def list_states(self) -> list[PipelineState]:
        raise NotImplementedError


class SQLiteStateStore(BaseStateStore):
    def __init__(self, database_url: str) -> None:
        db_path = self._extract_sqlite_path(database_url)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def _extract_sqlite_path(self, database_url: str) -> str:
        if database_url.startswith("sqlite:///"):
            return database_url.replace("sqlite:///", "", 1)
        return "devops_platform.db"

    def _initialize(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pipelines (
                pipeline_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def upsert(self, state: PipelineState) -> None:
        serialized = state.model_dump_json()
        now = datetime.utcnow().isoformat()
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO pipelines (pipeline_id, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(pipeline_id) DO UPDATE SET
                payload=excluded.payload,
                updated_at=excluded.updated_at
            """,
            (state.pipeline_id, serialized, now),
        )
        self._conn.commit()

    def get(self, pipeline_id: str) -> PipelineState | None:
        cursor = self._conn.cursor()
        cursor.execute("SELECT payload FROM pipelines WHERE pipeline_id = ?", (pipeline_id,))
        row = cursor.fetchone()
        if not row:
            return None
        data: dict[str, Any] = json.loads(row["payload"])
        return PipelineState.model_validate(data)

    def list_states(self) -> list[PipelineState]:
        cursor = self._conn.cursor()
        cursor.execute("SELECT payload FROM pipelines")
        rows = cursor.fetchall()
        states: list[PipelineState] = []
        for row in rows:
            payload = json.loads(row["payload"])
            states.append(PipelineState.model_validate(payload))
        return states


class PostgresStateStore(BaseStateStore):
    def __init__(self, database_url: str) -> None:
        if psycopg2 is None or Json is None:
            raise RuntimeError("psycopg2 is required for PostgreSQL state store")
        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = True
        self._initialize()

    def _initialize(self) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pipelines (
                    pipeline_id TEXT PRIMARY KEY,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )

    def upsert(self, state: PipelineState) -> None:
        payload = state.model_dump(mode="json")
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO pipelines (pipeline_id, payload, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT(pipeline_id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                """,
                (state.pipeline_id, Json(payload)),
            )

    def get(self, pipeline_id: str) -> PipelineState | None:
        with self._conn.cursor() as cursor:
            cursor.execute("SELECT payload FROM pipelines WHERE pipeline_id = %s", (pipeline_id,))
            row = cursor.fetchone()
        if not row:
            return None
        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return PipelineState.model_validate(payload)

    def list_states(self) -> list[PipelineState]:
        with self._conn.cursor() as cursor:
            cursor.execute("SELECT payload FROM pipelines")
            rows = cursor.fetchall()

        states: list[PipelineState] = []
        for row in rows:
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            states.append(PipelineState.model_validate(payload))
        return states


def build_state_store(database_url: str) -> BaseStateStore:
    normalized = database_url.lower()
    if normalized.startswith("postgresql://") or normalized.startswith("postgres://"):
        try:
            return PostgresStateStore(database_url)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Falling back to SQLite state store because PostgreSQL init failed: %s", exc)
    return SQLiteStateStore(database_url)

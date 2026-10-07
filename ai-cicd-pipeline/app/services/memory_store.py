"""Agent memory store — SQLite or in-process context per agent + pipeline scope."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from app.config import settings


class MemoryStore(Protocol):
    def get_context(self, agent_name: str, scope_id: str, limit: int = 5) -> list[dict[str, Any]]:
        ...

    def append_interaction(
        self,
        agent_name: str,
        scope_id: str,
        prompt_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> None:
        ...

    def list_scopes(self, agent_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        ...


class SQLiteAgentMemoryStore:
    """Persistent agent memory keyed by pipeline scope (SQLite file)."""

    def __init__(self, database_url: str) -> None:
        import sqlite3

        url = database_url.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
        self._path = Path(url)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                prompt_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_memory_scope ON agent_memory(agent_name, scope_id)"
        )
        self._conn.commit()

    def get_context(self, agent_name: str, scope_id: str, limit: int = 5) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            """
            SELECT prompt_json, response_json FROM agent_memory
            WHERE agent_name = ? AND scope_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (agent_name, scope_id, limit),
        )
        rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for prompt_json, response_json in reversed(rows):
            out.append(
                {
                    "prompt_payload": json.loads(prompt_json),
                    "response_payload": json.loads(response_json),
                }
            )
        return out

    def append_interaction(
        self,
        agent_name: str,
        scope_id: str,
        prompt_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_memory (agent_name, scope_id, prompt_json, response_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                agent_name,
                scope_id,
                json.dumps(prompt_payload, default=str),
                json.dumps(response_payload, default=str),
            ),
        )
        self._conn.commit()

    def list_scopes(self, agent_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if agent_name:
            cur = self._conn.execute(
                """
                SELECT scope_id, agent_name, MAX(created_at) AS last_at, COUNT(*) AS turns
                FROM agent_memory
                WHERE agent_name = ?
                GROUP BY scope_id, agent_name
                ORDER BY last_at DESC
                LIMIT ?
                """,
                (agent_name, limit),
            )
        else:
            cur = self._conn.execute(
                """
                SELECT scope_id, agent_name, MAX(created_at) AS last_at, COUNT(*) AS turns
                FROM agent_memory
                GROUP BY scope_id, agent_name
                ORDER BY last_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [
            {"scope_id": row[0], "agent_name": row[1], "last_at": row[2], "turns": row[3]}
            for row in cur.fetchall()
        ]


class InMemoryAgentMemoryStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def get_context(self, agent_name: str, scope_id: str, limit: int = 5) -> list[dict[str, Any]]:
        items = self._data.get((agent_name, scope_id), [])
        return items[-limit:]

    def append_interaction(
        self,
        agent_name: str,
        scope_id: str,
        prompt_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> None:
        key = (agent_name, scope_id)
        self._data.setdefault(key, []).append(
            {"prompt_payload": prompt_payload, "response_payload": response_payload}
        )
        max_entries = settings.agent_memory_max_entries_per_scope
        if len(self._data[key]) > max_entries:
            self._data[key] = self._data[key][-max_entries:]

    def list_scopes(self, agent_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        scopes: list[dict[str, Any]] = []
        for (name, scope_id), items in self._data.items():
            if agent_name and name != agent_name:
                continue
            scopes.append({"scope_id": scope_id, "agent_name": name, "turns": len(items)})
        scopes.sort(key=lambda s: s["turns"], reverse=True)
        return scopes[:limit]


def build_memory_store() -> MemoryStore:
    if not settings.agent_memory_enabled:
        return InMemoryAgentMemoryStore()
    path = (settings.agent_memory_sqlite_path or "").strip()
    if path:
        return SQLiteAgentMemoryStore(f"sqlite:///{path}")
    url = (settings.database_url or "").strip()
    if url.startswith("sqlite"):
        return SQLiteAgentMemoryStore(url.replace("+aiosqlite", ""))
    return InMemoryAgentMemoryStore()


def build_memory_snapshot(
    store: MemoryStore,
    *,
    scope_id: str,
    agents: list[str] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    agent_names = agents or []
    entries: list[dict[str, Any]] = []
    for agent in agent_names:
        ctx = store.get_context(agent, scope_id, limit=limit)
        if ctx:
            entries.append({"agent_name": agent, "turns": len(ctx), "latest": ctx[-1]})
    return {
        "scope_id": scope_id,
        "memory_enabled": settings.agent_memory_enabled,
        "backend": "sqlite" if settings.agent_memory_enabled and settings.agent_memory_sqlite_path else "in_memory",
        "agents_with_context": len(entries),
        "entries": entries,
        "summary": f"Agent memory: {len(entries)} agent(s) with prior context for scope {scope_id[:8]}.",
    }

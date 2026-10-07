from typing import Any, Protocol


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


class SQLiteAgentMemoryStore:
    """Persistent agent memory keyed by pipeline scope (SQLite)."""

    def __init__(self, database_url: str) -> None:
        import sqlite3
        from pathlib import Path

        url = database_url.replace("sqlite:///", "")
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
        self._conn.commit()

    def get_context(self, agent_name: str, scope_id: str, limit: int = 5) -> list[dict[str, Any]]:
        import json

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
        import json

        self._conn.execute(
            """
            INSERT INTO agent_memory (agent_name, scope_id, prompt_json, response_json)
            VALUES (?, ?, ?, ?)
            """,
            (agent_name, scope_id, json.dumps(prompt_payload, default=str), json.dumps(response_payload, default=str)),
        )
        self._conn.commit()


class InMemoryAgentMemoryStore:
    """Simple per-agent in-memory context store for future persistent memory adapters."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def get_context(self, agent_name: str, scope_id: str, limit: int = 5) -> list[dict[str, Any]]:
        key = (agent_name, scope_id)
        items = self._data.get(key, [])
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
            {
                "prompt_payload": prompt_payload,
                "response_payload": response_payload,
            }
        )


def build_memory_store(settings: Any) -> MemoryStore:
    if not getattr(settings, "agent_memory_enabled", False):
        return InMemoryAgentMemoryStore()
    url = (getattr(settings, "database_url", "") or "").strip()
    if url.startswith("sqlite"):
        return SQLiteAgentMemoryStore(url)
    return InMemoryAgentMemoryStore()

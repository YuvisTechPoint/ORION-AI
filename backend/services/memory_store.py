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

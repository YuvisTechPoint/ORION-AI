import json
from abc import ABC, abstractmethod
from typing import Any

from core.llm_client import LLMClient
from services.memory_store import MemoryStore
from services.retriever import Retriever


class BaseAgent(ABC):
    def __init__(
        self,
        llm_client: LLMClient,
        name: str,
        memory_store: MemoryStore | None = None,
        retriever: Retriever | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.name = name
        self.memory_enabled = False
        self.tools: list[str] = []
        self.memory_store = memory_store
        self.retriever = retriever

    @abstractmethod
    def build_prompt(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt_payload = self._prepare_payload(payload)
        prompt = self.build_prompt(prompt_payload)
        raw = self.llm_client.generate(prompt)
        # LLM client may return a dict (structured) or a JSON string — handle both.
        if isinstance(raw, dict):
            parsed = raw
        else:
            parsed = self._parse_json(raw)
        self._record_memory(prompt_payload=prompt_payload, response_payload=parsed)
        return parsed

    def _prepare_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        enriched = payload.copy()

        modality_hints = [item.get("modality", "") for item in enriched.get("multimodal_inputs", []) if isinstance(item, dict)]
        query = self._build_retrieval_query(enriched)
        if self.retriever is not None and query:
            enriched["retrieval_context"] = self.retriever.retrieve(query=query, modality_hints=modality_hints, top_k=3)
        else:
            enriched["retrieval_context"] = []

        if self.memory_enabled and self.memory_store is not None:
            scope_id = self._scope_id(enriched)
            enriched["memory_context"] = self.memory_store.get_context(self.name, scope_id, limit=5)
        else:
            enriched["memory_context"] = []
        return enriched

    def _build_retrieval_query(self, payload: dict[str, Any]) -> str:
        return str(payload.get("diff") or payload.get("code") or payload.get("logs") or payload.get("config_text") or "")

    def _scope_id(self, payload: dict[str, Any]) -> str:
        return str(payload.get("pipeline_id") or payload.get("repo_name") or "global")

    def _record_memory(self, prompt_payload: dict[str, Any], response_payload: dict[str, Any]) -> None:
        if not self.memory_enabled or self.memory_store is None:
            return
        self.memory_store.append_interaction(
            agent_name=self.name,
            scope_id=self._scope_id(prompt_payload),
            prompt_payload=prompt_payload,
            response_payload=response_payload,
        )

    def _parse_json(self, raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "", 1).replace("```", "").strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            return {"raw": parsed}
        except json.JSONDecodeError:
            return {
                "summary": "Invalid JSON returned by LLM.",
                "issues": [
                    {
                        "type": "invalid_json",
                        "severity": "high",
                        "line": "n/a",
                        "fix": "Adjust prompt to enforce strict JSON output.",
                    }
                ],
                "raw": raw,
            }

import json

from agents.base import BaseAgent
from services.memory_store import InMemoryAgentMemoryStore


class DummyLLM:
    def generate(self, prompt: str) -> str:
        _ = prompt
        return json.dumps({"summary": "ok", "issues": []})


class DummyRetriever:
    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3):
        return [{"id": "doc-1", "snippet": query[:20], "modalities": modality_hints or [], "top_k": top_k}]


class DummyAgent(BaseAgent):
    def build_prompt(self, payload: dict[str, object]) -> str:
        return json.dumps(payload)


def test_agent_payload_enrichment_and_memory() -> None:
    memory = InMemoryAgentMemoryStore()
    agent = DummyAgent(llm_client=DummyLLM(), name="dummy", memory_store=memory, retriever=DummyRetriever())
    agent.memory_enabled = True

    payload = {
        "pipeline_id": "p-1",
        "repo_name": "svc",
        "code": "print('hello')",
        "multimodal_inputs": [{"modality": "code", "content": "print('hello')"}],
    }

    result = agent.run(payload)

    assert result["summary"] == "ok"
    context = memory.get_context("dummy", "p-1")
    assert len(context) == 1
    assert "retrieval_context" in context[0]["prompt_payload"]

from typing import Any, Protocol


class Retriever(Protocol):
    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        ...


class NoOpRetriever:
    """Default retriever that returns no documents; placeholder for vector DB adapters."""

    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        _ = (query, modality_hints, top_k)
        return []


def build_retriever(backend: str) -> Retriever:
    normalized = backend.strip().lower()
    if normalized in {"none", "noop", "disabled"}:
        return NoOpRetriever()
    # Future adapters: faiss, pinecone, pgvector.
    return NoOpRetriever()

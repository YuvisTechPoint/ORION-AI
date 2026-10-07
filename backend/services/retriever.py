from typing import Any, Protocol


class Retriever(Protocol):
    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        ...

    def index_files(self, repo_files: dict[str, str] | None) -> None:
        ...


class NoOpRetriever:
    """Default retriever that returns no documents; placeholder for vector DB adapters."""

    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        _ = (query, modality_hints, top_k)
        return []

    def index_files(self, repo_files: dict[str, str] | None) -> None:
        _ = repo_files


class FileChunkRetriever:
    """In-process keyword retriever over indexed source files."""

    def __init__(self, chunk_size: int = 800) -> None:
        self.chunk_size = max(200, chunk_size)
        self._chunks: list[dict[str, str]] = []

    def index_files(self, repo_files: dict[str, str] | None) -> None:
        self._chunks = []
        if not repo_files:
            return
        for path, content in repo_files.items():
            text = content or ""
            if not text.strip():
                continue
            for start in range(0, len(text), self.chunk_size):
                piece = text[start : start + self.chunk_size]
                self._chunks.append({"path": path, "content": piece})

    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        _ = modality_hints
        tokens = {tok.lower() for tok in (query or "").split() if len(tok) > 2}
        if not tokens or not self._chunks:
            return []
        scored: list[tuple[int, dict[str, str]]] = []
        for chunk in self._chunks:
            hay = f"{chunk['path']}\n{chunk['content']}".lower()
            score = sum(1 for tok in tokens if tok in hay)
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{"path": item[1]["path"], "content": item[1]["content"][:500], "score": item[0]} for item in scored[:top_k]]


class HybridFileRetriever(FileChunkRetriever):
    """Keyword + fuzzy sequence scoring for richer agent context."""

    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        from difflib import SequenceMatcher

        _ = modality_hints
        tokens = {tok.lower() for tok in (query or "").split() if len(tok) > 2}
        if not tokens and not (query or "").strip():
            return []
        query_lower = (query or "").lower()
        scored: list[tuple[float, dict[str, str]]] = []
        for chunk in self._chunks:
            hay = f"{chunk['path']}\n{chunk['content']}"
            hay_lower = hay.lower()
            token_score = sum(2 for tok in tokens if tok in hay_lower)
            fuzzy = SequenceMatcher(None, query_lower[:400], hay_lower[:800]).ratio() * 5
            path_boost = 1.5 if any(tok in chunk["path"].lower() for tok in tokens) else 0
            total = token_score + fuzzy + path_boost
            if total > 0.5:
                scored.append((total, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {"path": item[1]["path"], "content": item[1]["content"][:500], "score": round(item[0], 2)}
            for item in scored[:top_k]
        ]


def build_retriever(backend: str) -> Retriever:
    normalized = backend.strip().lower()
    if normalized in {"hybrid", "smart", "advanced"}:
        return HybridFileRetriever()
    if normalized in {"file", "files", "chunk", "chunks"}:
        return FileChunkRetriever()
    if normalized in {"none", "noop", "disabled"}:
        return NoOpRetriever()
    return HybridFileRetriever()

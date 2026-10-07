"""Hybrid file retriever — keyword + fuzzy scoring over indexed repo files."""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

from app.config import settings

_TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".tf",
    ".sh",
    ".ps1",
    ".dockerfile",
}
_SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".pytest_cache"}


class Retriever(Protocol):
    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        ...

    def index_files(self, repo_files: dict[str, str] | None) -> None:
        ...

    def chunk_count(self) -> int:
        ...


class NoOpRetriever:
    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        _ = (query, modality_hints, top_k)
        return []

    def index_files(self, repo_files: dict[str, str] | None) -> None:
        _ = repo_files

    def chunk_count(self) -> int:
        return 0


class FileChunkRetriever:
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
        return [
            {"path": item[1]["path"], "content": item[1]["content"][:500], "score": item[0], "source": "file"}
            for item in scored[:top_k]
        ]

    def chunk_count(self) -> int:
        return len(self._chunks)


class HybridFileRetriever(FileChunkRetriever):
    def retrieve(self, query: str, modality_hints: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
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
            {
                "path": item[1]["path"],
                "content": item[1]["content"][:500],
                "score": round(item[0], 2),
                "source": "file",
            }
            for item in scored[:top_k]
        ]


def build_retriever(backend: str | None = None) -> Retriever:
    normalized = (backend or settings.retriever_backend or "hybrid").strip().lower()
    if normalized in {"hybrid", "smart", "advanced"}:
        return HybridFileRetriever(chunk_size=settings.retriever_chunk_size)
    if normalized in {"file", "files", "chunk", "chunks"}:
        return FileChunkRetriever(chunk_size=settings.retriever_chunk_size)
    if normalized in {"none", "noop", "disabled"}:
        return NoOpRetriever()
    return HybridFileRetriever(chunk_size=settings.retriever_chunk_size)


def collect_repo_files(repo_path: str, *, max_files: int | None = None) -> dict[str, str]:
    root = Path(repo_path)
    if not root.is_dir():
        return {}
    limit = max_files or settings.rag_index_max_files
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _TEXT_EXTENSIONS and path.name not in ("Dockerfile", "Makefile"):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > settings.rag_index_max_file_bytes:
            text = text[: settings.rag_index_max_file_bytes]
        files[rel] = text
        if len(files) >= limit:
            break
    return files


def index_repository(retriever: Retriever, repo_path: str) -> dict[str, Any]:
    if not settings.rag_index_enabled:
        return {"indexed_files": 0, "chunks": 0, "skipped": True}
    files = collect_repo_files(repo_path)
    retriever.index_files(files)
    return {
        "indexed_files": len(files),
        "chunks": retriever.chunk_count(),
        "skipped": False,
        "summary": f"Indexed {len(files)} file(s) into {retriever.chunk_count()} chunk(s).",
    }

"""Lightweight text embeddings for L3 semantic memory (no external API required)."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)


def embed_text(text: str, *, dimensions: int = 384) -> list[float]:
    """
    Deterministic bag-of-tokens embedding for local/pgvector search.
    Production may swap in an API-backed embedder without changing store contracts.
    """
    dim = max(32, min(int(dimensions), 4096))
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for i in range(0, min(len(digest), dim), 2):
            idx = digest[i] % dim
            sign = 1.0 if digest[i + 1] % 2 == 0 else -1.0
            vec[idx] += sign
    return _normalize(vec)


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    la = list(a)
    lb = list(b)
    if len(la) != len(lb) or not la:
        return 0.0
    dot = sum(x * y for x, y in zip(la, lb))
    na = math.sqrt(sum(x * x for x in la))
    nb = math.sqrt(sum(y * y for y in lb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())[:512]


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]

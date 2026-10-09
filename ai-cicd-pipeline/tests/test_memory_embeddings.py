"""Memory embedding utilities."""

from __future__ import annotations

from shared.memory_gateway.embeddings import cosine_similarity, embed_text


def test_embed_text_dimension_and_normalized():
    vec = embed_text("pipeline blocked on security scan", dimensions=384)
    assert len(vec) == 384
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 0.01 or norm == 0.0


def test_similar_texts_higher_cosine():
    a = embed_text("security vulnerability bandit high severity", dimensions=128)
    b = embed_text("security scan bandit critical finding", dimensions=128)
    c = embed_text("unrelated kubernetes helm chart", dimensions=128)
    assert cosine_similarity(a, b) > cosine_similarity(a, c)

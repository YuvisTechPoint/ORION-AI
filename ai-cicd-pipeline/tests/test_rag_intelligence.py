"""Tests for Phase 17 RAG + agent memory."""

from __future__ import annotations

from pathlib import Path

from app.services.hybrid_retriever import HybridFileRetriever, build_retriever, collect_repo_files, index_repository
from app.services.memory_store import InMemoryAgentMemoryStore, build_memory_snapshot
from app.utils.devops_rag import query_devops_rag
from app.utils.rag_intelligence import build_rag_intelligence_report


def test_memory_store_roundtrip():
    store = InMemoryAgentMemoryStore()
    store.append_interaction(
        "SecurityAgent",
        "run-1",
        {"text": "scan repo"},
        {"summary": "critical vulnerability in auth", "passed": False},
    )
    ctx = store.get_context("SecurityAgent", "run-1", limit=3)
    assert len(ctx) == 1
    assert "vulnerability" in str(ctx[0]["response_payload"])


def test_hybrid_retriever_scores_path_boost(tmp_path: Path):
    src = tmp_path / "auth" / "middleware.py"
    src.parent.mkdir()
    src.write_text("def authenticate(token):\n    return verify_jwt(token)\n", encoding="utf-8")
    retriever = HybridFileRetriever()
    index_repository(retriever, str(tmp_path))
    hits = retriever.retrieve("authenticate jwt middleware", top_k=2)
    assert hits
    assert hits[0]["path"].endswith("middleware.py")


def test_collect_repo_files_skips_venv(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".venv" / "lib.py").parent.mkdir(parents=True)
    (tmp_path / ".venv" / "lib.py").write_text("secret\n", encoding="utf-8")
    files = collect_repo_files(str(tmp_path), max_files=10)
    assert "app.py" in files
    assert not any(".venv" in path for path in files)


def test_devops_rag_hybrid_scoring():
    result = query_devops_rag(
        "security vulnerability auth",
        {
            "security_scan": {"summary": "critical vulnerability in auth module", "passed": False},
            "qa_report": {"summary": "all tests passed", "verdict": "pass"},
        },
    )
    assert result["grounded"] is True
    assert result["chunks"][0]["artifact_type"] == "security_scan"
    assert result["chunks"][0]["score"] >= result["chunks"][-1]["score"]


def test_devops_rag_includes_file_chunks():
    result = query_devops_rag(
        "payment refund",
        {},
        file_chunks=[{"path": "payments/service.py", "content": "def refund(): pass", "score": 4.0}],
    )
    assert any(c["source"] == "file" for c in result["chunks"])


def test_build_rag_intelligence_report():
    store = InMemoryAgentMemoryStore()
    store.append_interaction(
        "QAAgent",
        "scope-abc",
        {"text": "run tests"},
        {"summary": "QA failed on payment tests", "verdict": "fail"},
    )
    retriever = build_retriever("hybrid")
    retriever.index_files({"tests/test_pay.py": "def test_refund(): assert False"})
    report = build_rag_intelligence_report(
        query="payment test failure",
        artifacts={"qa_report": {"summary": "payment tests failed", "verdict": "fail"}},
        memory_store=store,
        retriever=retriever,
        scope_id="scope-abc",
    )
    assert report["grounded"] is True
    assert report["memory_snapshot"]["agents_with_context"] >= 1
    assert report["index"]["chunks_indexed"] >= 1


def test_build_memory_snapshot():
    store = InMemoryAgentMemoryStore()
    store.append_interaction("ApprovalAgent", "run-x", {}, {"decision": "approved"})
    snap = build_memory_snapshot(store, scope_id="run-x", agents=["ApprovalAgent"])
    assert snap["agents_with_context"] == 1

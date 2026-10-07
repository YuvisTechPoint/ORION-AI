"""Canonical memory gateway episodic extractor tests."""

from __future__ import annotations

import os

import pytest

from models.schemas import PipelineState
from services.memory_extractor import extract_canonical_episodic_memory
from services.memory_gateway_client import get_memory_gateway
from services.pipeline_terminal_hooks import run_terminal_hooks


@pytest.fixture(autouse=True)
def memory_env(tmp_path, monkeypatch):
    db_path = tmp_path / "canonical-memory.db"
    monkeypatch.setenv("MEMORY_GATEWAY_ENABLED", "true")
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("EVENT_BUS_BACKEND", "memory")
    get_memory_gateway.cache_clear()
    yield


def test_extract_canonical_episodic_memory_writes_record():
    state = PipelineState(
        repo_name="demo",
        status="completed",
        correlation_id="corr-abc",
        artifacts={
            "submit_request": {"repo_full_name": "acme/demo", "repo_name": "demo"},
            "security": {"summary": "No critical issues"},
        },
    )
    result = extract_canonical_episodic_memory(state)
    assert result.get("written") is True
    assert result.get("record_id")


def test_terminal_hooks_idempotent():
    state = PipelineState(
        repo_name="demo",
        status="blocked",
        correlation_id="corr-xyz",
        artifacts={"submit_request": {"repo_full_name": "acme/demo"}},
    )
    first = run_terminal_hooks(state)
    second = run_terminal_hooks(state)
    assert first.get("skipped") is not True
    assert first.get("memory", {}).get("written") is True
    assert second.get("skipped") is True

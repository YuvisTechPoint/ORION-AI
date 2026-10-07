"""Tests for pipeline dispatch (Celery vs inline executor)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.orchestrator import dispatch as dispatch_mod


def test_executor_mode_forced_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_EXECUTOR", "inline")
    dispatch_mod.get_settings.cache_clear()
    assert dispatch_mod.executor_mode() == "inline"


def test_dispatch_inline_runs_in_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_EXECUTOR", "inline")
    dispatch_mod.get_settings.cache_clear()
    called: list[str] = []

    def fake_impl(pid: str) -> None:
        called.append(pid)

    monkeypatch.setattr(dispatch_mod, "_run_pipeline_impl", fake_impl)
    mode = dispatch_mod.dispatch_pipeline("00000000-0000-0000-0000-000000000001")
    assert mode == "inline"
    import time

    deadline = time.time() + 3
    while not called and time.time() < deadline:
        time.sleep(0.05)
    assert called == ["00000000-0000-0000-0000-000000000001"]


def test_dispatch_celery_uses_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_EXECUTOR", "celery")
    dispatch_mod.get_settings.cache_clear()
    mock_task = MagicMock()
    mock_task.delay = MagicMock(return_value=None)
    monkeypatch.setattr(dispatch_mod, "run_pipeline", mock_task)
    mode = dispatch_mod.dispatch_pipeline("abc")
    assert mode == "celery"
    mock_task.delay.assert_called_once_with("abc")

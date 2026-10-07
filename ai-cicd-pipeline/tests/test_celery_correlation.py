from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.tasks.pipeline_tasks import _load_correlation_context
from app.utils.correlation import get_correlation_id, set_correlation_id


def test_load_correlation_context_sets_contextvar(monkeypatch) -> None:
    from app.utils.correlation import set_trace_id

    set_correlation_id(None)
    set_trace_id(None)
    run_id = uuid.uuid4()
    fake_run = SimpleNamespace(
        correlation_id="corr-worker-abc",
        trace_id="trace-worker-def",
    )

    class _FakeSession:
        def get(self, _model, _id):
            return fake_run

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_engine = SimpleNamespace(dispose=lambda: None)
    monkeypatch.setattr("app.tasks.pipeline_tasks.create_engine", lambda *_a, **_k: fake_engine)
    monkeypatch.setattr("app.tasks.pipeline_tasks.Session", lambda *_a, **_k: _FakeSession())

    loaded = _load_correlation_context(str(run_id))
    assert loaded == "corr-worker-abc"
    assert get_correlation_id() == "corr-worker-abc"
    set_correlation_id(None)
    set_trace_id(None)

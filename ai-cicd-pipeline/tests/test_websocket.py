"""ORION pipeline WebSocket integration tests (H-003)."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.services.events import channel_for, event_bus, publish_event


@pytest.mark.asyncio
async def test_pipeline_websocket_snapshot_and_live_event(pipeline_run, monkeypatch) -> None:
    async def _no_interrupted_runs() -> list:
        return []

    async def _noop_workdir_recovery() -> None:
        return None

    monkeypatch.setattr("app.tasks.dispatch.recover_interrupted_runs", _no_interrupted_runs)
    monkeypatch.setattr("app.services.workdir_manager.recover_pipeline_workdirs_at_startup", _noop_workdir_recovery)
    monkeypatch.setattr("app.tasks.dispatch.dispatch_pipeline", lambda *a, **k: None)

    run_id = pipeline_run.id
    channel = channel_for(run_id)
    publish_event(
        run_id,
        {
            "kind": "stage-update",
            "stage": "analyzing_code",
            "status": "analyzing_code",
        },
    )

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/pipeline/{run_id}") as ws:
            snapshot = json.loads(ws.receive_text())
            assert snapshot["kind"] == "snapshot"
            assert snapshot["run_id"] == str(run_id)

            seen_stage = False
            for _ in range(6):
                message = json.loads(ws.receive_text())
                if message.get("kind") == "stage-update":
                    assert message["stage"] == "analyzing_code"
                    seen_stage = True
                    break
            assert seen_stage

    event_bus._history.pop(channel, None)  # noqa: SLF001 — test cleanup

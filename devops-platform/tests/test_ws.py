"""WebSocket endpoint smoke tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_websocket_accepts_connection() -> None:
    client = TestClient(app)
    pipeline_id = str(uuid4())
    with client.websocket_connect(f"/ws/{pipeline_id}") as ws:
        ws.send_json({"type": "ping"})
        # Server may not echo; connection staying open is enough for smoke coverage.

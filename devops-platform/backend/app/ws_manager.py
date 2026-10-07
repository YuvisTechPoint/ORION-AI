import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import WebSocket

from app.redis_publish import publish_pipeline_event


class WebSocketManager:
    """Tracks WebSocket connections; all events go through Redis for Celery compatibility."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, pipeline_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(pipeline_id, []).append(websocket)

    def disconnect(self, pipeline_id: str, websocket: WebSocket) -> None:
        conns = self._connections.get(pipeline_id)
        if not conns:
            return
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            del self._connections[pipeline_id]

    async def broadcast(self, pipeline_id: str | UUID, event: dict[str, Any]) -> None:
        """Publish to Redis; subscriber forwards to local WebSocket clients."""
        pid = str(pipeline_id)
        await asyncio.to_thread(publish_pipeline_event, pid, event)
        for ws in list(self._connections.get(pid, [])):
            try:
                await ws.send_text(json.dumps(event, default=str))
            except Exception:
                continue


ws_manager = WebSocketManager()

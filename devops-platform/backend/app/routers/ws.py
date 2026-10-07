import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import ws_require_auth
from app.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/{pipeline_id}")
async def pipeline_ws(websocket: WebSocket, pipeline_id: str) -> None:
    if not await ws_require_auth(websocket):
        await websocket.close(code=4401, reason="Unauthorized")
        return
    await ws_manager.connect(pipeline_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(pipeline_id, websocket)

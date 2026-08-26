"""Controller: WebSocket push sự kiện UI realtime."""
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger("ws_controller")
router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    hub = ws.app.state.hub
    manager = ws.app.state.manager
    await ws.accept()
    hub.connect(ws)
    log.debug("ws connected (%d)", hub.count)
    await ws.send_json({"type": "hello", "sessions": manager.states()})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)
        log.debug("ws disconnected (%d)", hub.count)

"""Event hub + UI event emitter.

- `EventHub`: quản lý các WebSocket client đang kết nối, broadcast JSON.
- `UIEventEmitter`: đóng vai trò "Presenter" — biến sự kiện nội bộ (opened,
  closed, browser_installing...) thành message gửi tới UI + ghi log.
"""
import asyncio
import logging

log = logging.getLogger("events")


class EventHub:
    def __init__(self):
        self.connections = set()

    def connect(self, ws):
        self.connections.add(ws)

    def disconnect(self, ws):
        self.connections.discard(ws)

    @property
    def count(self) -> int:
        return len(self.connections)

    async def broadcast(self, event):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


class UIEventEmitter:
    """Gửi sự kiện UI qua EventHub và ghi log để dễ debug."""

    def __init__(self, hub: EventHub | None = None, get_states=None):
        self.hub = hub
        self.get_states = get_states

    def publish(self, event: dict):
        """Publish một event dict đã hoàn chỉnh (không thêm sessions)."""
        log.debug("UI event -> %s", event.get("type"))
        if not self.hub:
            return
        try:
            loop = asyncio.get_running_loop()
            if loop.is_closed():
                return
            loop.create_task(self.hub.broadcast(event))
        except RuntimeError:
            pass

    def emit(self, kind: str, **data) -> dict:
        """Tạo event {type, **data, sessions} rồi publish."""
        event = {"type": kind, **data}
        if self.get_states:
            try:
                event["sessions"] = self.get_states()
            except Exception:
                pass
        self.publish(event)
        return event

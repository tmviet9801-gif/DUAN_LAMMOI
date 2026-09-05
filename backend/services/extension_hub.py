"""ExtensionHubManager — Quản lý kết nối WebSocket và điều phối 2 chiều với Chrome Extension.

Kiến trúc V3:
- Mỗi Chrome Profile mở 1 kết nối WebSocket riêng về: ws://127.0.0.1:17832/ws/bridge?profile=<Tên_Profile>
- ExtensionHubManager lưu trữ kết nối, định tuyến gói tin hai chiều không độ trễ (<2ms).
- Gửi lệnh tức thời: JOIN_ROOM, LEAVE_ROOM, READY, START, DISCARD_CARDS.
- Lưu cache trạng thái phòng, người chơi và bài của từng profile.
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, Optional
from fastapi import WebSocket

log = logging.getLogger("extension_hub")


class ExtensionHubManager:
    """Hub trung tâm điều phối kết nối Chrome Extension đa profile."""

    def __init__(self, on_event: Optional[Callable[[dict], Any]] = None):
        self.active_sockets: Dict[str, WebSocket] = {}
        self.profile_states: Dict[str, dict] = {}
        self.on_event = on_event
        self._lock = asyncio.Lock()

    def set_event_sink(self, on_event: Callable[[dict], Any]):
        self.on_event = on_event

    def _emit(self, event: dict):
        if self.on_event:
            try:
                self.on_event(event)
            except Exception as e:
                log.warning("ExtensionHub emit error: %s", e)

    async def register(self, profile_name: str, ws: WebSocket):
        """Đăng ký kết nối WebSocket mới từ Extension của một Profile."""
        async with self._lock:
            # Nếu profile cũ đang có socket tồn tại thì đóng socket cũ
            old_ws = self.active_sockets.get(profile_name)
            if old_ws and old_ws != ws:
                try:
                    await old_ws.close()
                except Exception:
                    pass

            self.active_sockets[profile_name] = ws
            now = time.time()
            self.profile_states[profile_name] = {
                "profile_name": profile_name,
                "connected": True,
                "connected_at": now,
                "last_seen": now,
                "room_info": None,
                "players": [],
                "room_state": 0,
                "cards": [],
            }

        log.info("ExtensionHub V3: >>> Profile '%s' đã kết nối thành công! (Tổng: %d) <<<", 
                 profile_name, len(self.active_sockets))

        self._emit({
            "type": "extension_connected",
            "profile_name": profile_name,
            "count": len(self.active_sockets),
            "timestamp": now,
        })

    async def unregister(self, profile_name: str, ws: Optional[WebSocket] = None):
        """Hủy đăng ký khi Extension ngắt kết nối."""
        async with self._lock:
            cur_ws = self.active_sockets.get(profile_name)
            if ws is None or cur_ws == ws:
                self.active_sockets.pop(profile_name, None)
                if profile_name in self.profile_states:
                    self.profile_states[profile_name]["connected"] = False
                    self.profile_states[profile_name]["disconnected_at"] = time.time()

        log.info("ExtensionHub V3: Profile '%s' đã ngắt kết nối (Còn lại: %d)", 
                 profile_name, len(self.active_sockets))

        self._emit({
            "type": "extension_disconnected",
            "profile_name": profile_name,
            "count": len(self.active_sockets),
            "timestamp": time.time(),
        })

    def is_connected(self, profile_name: str) -> bool:
        """Kiểm tra xem profile có đang kết nối Extension không."""
        return profile_name in self.active_sockets

    async def send_command(self, profile_name: str, action: str, data: Optional[dict] = None) -> bool:
        """Bắn lệnh tức thời xuống tab của profile qua Extension Bridge (Độ trễ <2ms)."""
        ws = self.active_sockets.get(profile_name)
        if not ws:
            log.warning("send_command: Profile '%s' chưa kết nối Extension!", profile_name)
            return False

        payload = {
            "action": action,
            "profile_name": profile_name,
            "data": data or {},
            "timestamp": time.time(),
        }

        try:
            await ws.send_text(json.dumps(payload))
            log.info("ExtensionHub V3 -> [%s] Lệnh '%s' gửi thành công: %s", profile_name, action, data)
            return True
        except Exception as e:
            log.warning("ExtensionHub V3 -> [%s] Lỗi gửi lệnh '%s': %s", profile_name, action, e)
            await self.unregister(profile_name, ws)
            return False

    async def broadcast_command(self, action: str, data: Optional[dict] = None) -> int:
        """Gửi lệnh đồng loạt tới tất cả các profile đang kết nối."""
        sent_count = 0
        for name in list(self.active_sockets.keys()):
            ok = await self.send_command(name, action, data)
            if ok:
                sent_count += 1
        return sent_count

    def handle_message(self, profile_name: str, raw_data: Any):
        """Xử lý dữ liệu gửi từ Extension lên Hub (Packet phòng, người chơi, bài)."""
        if not profile_name:
            return

        state = self.profile_states.setdefault(profile_name, {
            "profile_name": profile_name,
            "connected": True,
            "room_info": None,
            "players": [],
            "cards": [],
        })
        state["last_seen"] = time.time()

        if isinstance(raw_data, str):
            try:
                msg = json.loads(raw_data)
            except Exception:
                return
        elif isinstance(raw_data, dict):
            msg = raw_data
        else:
            return

        msg_type = msg.get("type") or msg.get("action")

        # Cập nhật thông tin bàn cược
        if msg_type in ("ROOM_INFO", "ROOM_UPDATE"):
            ri = msg.get("room_info") or msg.get("data")
            if ri:
                state["room_info"] = ri
                self._emit({
                    "type": "room_info_updated",
                    "profile_name": profile_name,
                    "room_info": ri,
                })

        # Cập nhật danh sách người chơi
        elif msg_type in ("PLAYER_LIST", "PLAYERS"):
            pls = msg.get("players") or msg.get("ps") or msg.get("data")
            if isinstance(pls, list):
                state["players"] = pls

        # Cập nhật bài được chia
        elif msg_type in ("CARDS_DEALT", "HAND_INFO"):
            cards = msg.get("cards") or msg.get("data")
            if isinstance(cards, list):
                state["cards"] = cards
                self._emit({
                    "type": "cards_updated",
                    "profile_name": profile_name,
                    "cards": cards,
                })

        # Trạng thái rời bàn
        elif msg_type in ("ROOM_LEFT", "LEAVE_ROOM"):
            state["room_info"] = None
            state["players"] = []
            state["cards"] = []
            self._emit({
                "type": "room_left",
                "profile_name": profile_name,
            })

    def get_profile_state(self, profile_name: str) -> dict:
        """Lấy thông tin trạng thái mới nhất của profile."""
        return self.profile_states.get(profile_name, {
            "profile_name": profile_name,
            "connected": False,
            "room_info": None,
            "players": [],
            "cards": [],
        })

    def get_status(self) -> dict:
        """Báo cáo tổng thể toàn bộ kết nối Extension Hub."""
        return {
            "version": "3.0.0",
            "hub_name": "Multi-Profile Extension Bridge Hub",
            "connected_count": len(self.active_sockets),
            "connected_profiles": list(self.active_sockets.keys()),
            "states": self.profile_states,
        }

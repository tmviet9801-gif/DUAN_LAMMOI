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

        # Đồng bộ danh sách đồng đội (Partners) tức thời cho tất cả các tab
        active_names = list(self.active_sockets.keys())
        for name in active_names:
            partners = [p for p in active_names if p != name]
            asyncio.create_task(self.send_command(name, "SYNC_PARTNERS", {
                "partners": partners,
                "all_profiles": active_names,
            }))

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

        # 1. Cập nhật Số Dư (Balance) Realtime từ Extension
        if msg_type in ("BALANCE_UPDATE", "AUTOTOOL_BALANCE_UPDATE"):
            bal = msg.get("balance")
            if bal is None and isinstance(msg.get("data"), dict):
                bal = msg.get("data", {}).get("balance")
            if bal is not None:
                try:
                    bal_val = int(float(str(bal).replace(",", "").replace(".", "").strip()))
                except Exception:
                    bal_val = bal

                state["balance"] = bal_val
                log.info("ExtensionHub V3: Profile '%s' cập nhật số dư mới: %s", profile_name, bal_val)

                # Cập nhật và lưu vào accounts.json
                try:
                    from models.config_model import load_accounts, save_accounts
                    accounts = load_accounts()
                    updated = False
                    for a in accounts:
                        if (a.get("name") == profile_name or 
                            a.get("username") == profile_name or 
                            str(a.get("id")) == str(profile_name)):
                            a["balance"] = bal_val
                            updated = True
                            break
                    if updated:
                        save_accounts(accounts)
                except Exception as e:
                    log.warning("Lỗi lưu balance vào accounts.json: %s", e)

                self._emit({
                    "type": "accounts_updated",
                    "profile_name": profile_name,
                    "balance": bal_val,
                })

        # 2. Cập nhật Log Tiến Trình Realtime từ Extension
        elif msg_type in ("LOG_UPDATE", "AUTOTOOL_LOG_UPDATE"):
            log_text = msg.get("log")
            if not log_text and isinstance(msg.get("data"), dict):
                log_text = msg.get("data", {}).get("log")
            if log_text:
                state["log"] = str(log_text)
                try:
                    from models.config_model import load_accounts, save_accounts
                    accounts = load_accounts()
                    for a in accounts:
                        if (a.get("name") == profile_name or 
                            a.get("username") == profile_name or 
                            str(a.get("id")) == str(profile_name)):
                            a["log"] = str(log_text)
                            save_accounts(accounts)
                            break
                except Exception:
                    pass

                self._emit({
                    "type": "accounts_updated",
                    "profile_name": profile_name,
                    "log": str(log_text),
                })

        # 3. Cập nhật thông tin bàn cược & Tự động điều phối ID phòng tức thời (<2ms)
        elif msg_type in ("ROOM_INFO", "ROOM_UPDATE"):
            ri = msg.get("room_info") or msg.get("data")
            if ri and isinstance(ri, dict):
                rid = ri.get("rid") or "Chống Vây"
                state["room_info"] = ri
                state["room_id"] = rid
                room_display = f"Bàn #{rid}" if str(rid).isdigit() else f"Bàn {rid}"
                state["log"] = f"{room_display} (${ri.get('b', 100)})"
                try:
                    from models.config_model import load_accounts, save_accounts
                    accounts = load_accounts()
                    for a in accounts:
                        if (a.get("name") == profile_name or 
                            a.get("username") == profile_name or 
                            str(a.get("id")) == str(profile_name)):
                            a["room"] = rid
                            a["log"] = room_display
                            save_accounts(accounts)
                            break
                except Exception:
                    pass

                self._emit({
                    "type": "room_info_updated",
                    "profile_name": profile_name,
                    "room_info": ri,
                })
                self._emit({
                    "type": "accounts_updated",
                    "profile_name": profile_name,
                    "room": rid,
                })

                # Tự động chia sẻ thông tin phòng cho các profile đối tác với độ trễ <2ms
                last_rid = getattr(self, "_last_broadcast_rid", None)
                now_t = time.time()
                last_t = getattr(self, "_last_broadcast_time", 0)

                # Tránh lặp lại cùng 1 rid trong 1.5 giây
                if str(rid) != str(last_rid) or (now_t - last_t > 1.5):
                    self._last_broadcast_rid = rid
                    self._last_broadcast_time = now_t
                    self._last_shared_room = {
                        "rid": rid,
                        "b": ri.get("b", 100),
                        "Mu": ri.get("Mu", 2),
                        "source_profile": profile_name,
                        "timestamp": now_t,
                    }

                    # 1. Báo về cho Profile A (Chủ phòng) biết đã chia sẻ thành công khi có đồng đội online
                    target_count = max(0, len(self.active_sockets) - 1)
                    if target_count > 0:
                        asyncio.create_task(self.send_command(profile_name, "ROOM_SHARED_CONFIRM", {
                            "rid": rid,
                            "target_count": target_count,
                        }))

                    # 2. Bắn lệnh JOIN_ROOM ngay lập tức (<2ms) tới tất cả các profile khác đang online!
                    for other_profile in list(self.active_sockets.keys()):
                        if other_profile != profile_name:
                            log.info("ExtensionHub V3: >>> TỰ ĐỘNG CHUYỂN TIẾP BÀN '%s' TỪ '%s' SANG '%s' TỨC THỜI (<2ms)! <<<",
                                     rid, profile_name, other_profile)
                            asyncio.create_task(self.send_command(other_profile, "JOIN_ROOM", {
                                "rid": rid,
                                "bet": ri.get("b", 100),
                                "mu": ri.get("Mu", 2),
                                "source_profile": profile_name,
                            }))

        # 4. Xác nhận khớp bàn thành công giữa các đối tác (Cứu hẹn giờ out)
        elif msg_type in ("PARTNER_MATCHED", "AUTOTOOL_MATCH_SUCCESS"):
            partner_name = msg.get("partner_name")
            log.info("ExtensionHub V3: >>> PROFILE '%s' XÁC NHẬN KHỚP BÀN VỚI '%s' -> PHÁT LỆNH CONFIRM_MATCH TỨC THÌ! <<<",
                     profile_name, partner_name)
            for other_profile in list(self.active_sockets.keys()):
                if other_profile != profile_name:
                    asyncio.create_task(self.send_command(other_profile, "CONFIRM_MATCH", {
                        "source": profile_name,
                        "partner": partner_name,
                    }))

        # 5. Cập nhật danh sách người chơi
        elif msg_type in ("PLAYER_LIST", "PLAYERS"):
            pls = msg.get("players") or msg.get("ps") or msg.get("data")
            if isinstance(pls, list):
                state["players"] = pls

        # 5. Cập nhật bài được chia
        elif msg_type in ("CARDS_DEALT", "HAND_INFO"):
            cards = msg.get("cards") or msg.get("data")
            if isinstance(cards, list):
                state["cards"] = cards
                self._emit({
                    "type": "cards_updated",
                    "profile_name": profile_name,
                    "cards": cards,
                })

        # 6. Trạng thái rời bàn / Đang ở sảnh
        elif msg_type in ("ROOM_LEFT", "LEAVE_ROOM", "AUTOTOOL_ROOM_LEFT"):
            state["room_info"] = None
            state["room_id"] = -1
            state["log"] = "Đang ở sảnh"
            state["players"] = []
            state["cards"] = []
            try:
                from models.config_model import load_accounts, save_accounts
                accounts = load_accounts()
                for a in accounts:
                    if (a.get("name") == profile_name or 
                        a.get("username") == profile_name or 
                        str(a.get("id")) == str(profile_name)):
                        a["room"] = -1
                        a["log"] = "Đang ở sảnh"
                        save_accounts(accounts)
                        break
            except Exception:
                pass

            self._emit({
                "type": "room_left",
                "profile_name": profile_name,
            })
            self._emit({
                "type": "accounts_updated",
                "profile_name": profile_name,
                "room": -1,
                "log": "Đang ở sảnh",
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

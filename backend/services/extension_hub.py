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

from controllers.account_controller import _match_account, _parse_balance

log = logging.getLogger("extension_hub")


class ExtensionHubManager:
    """Hub trung tâm điều phối kết nối Chrome Extension đa profile."""

    def __init__(self, on_event: Optional[Callable[[dict], Any]] = None):
        self.active_sockets: Dict[str, WebSocket] = {}
        self.profile_states: Dict[str, dict] = {}
        self.on_event = on_event
        self._lock = asyncio.Lock()
        # Khi user bấm Dừng: tắt chia sẻ bàn (chặn mọi JOIN_ROOM tự động do anchor
        # báo "bàn trống" phát ra trễ) cho tới khi bắt đầu gom bàn lại.
        # Hub không được tự quyết định RID/mức cược từ frame của extension.
        # Luồng đó từng chuyển rid=4 ($500) dù UI đã cấu hình $100. Controller
        # là nơi duy nhất được quyền ghép bàn và hiện luôn giữ cờ này tắt.
        self._room_share_enabled = False

    def set_room_share(self, enabled: bool):
        """Bật/tắt cơ chế tự động chia sẻ bàn trống giữa các profile."""
        self._room_share_enabled = bool(enabled)
        log.info("ExtensionHub V3: room_share_enabled = %s", self._room_share_enabled)

    def relay_toast(self, source_profile: str, text: str, type_: str = "info", title: str = "AutoTool"):
        """Gửi thông báo nổi (toast 2s tự xoá) từ profile nguồn tới MỌI profile khác
        đang online — giúp Account phụ luôn biết Account chính đang làm gì:
        vào phòng nào, phòng có khách/trống, đang hủy/tìm bàn khác...
        """
        if not text:
            return
        try:
            key = (source_profile, type_, text[:40])
            now_t = time.time()
            last_map = getattr(self, "_last_relay_ts", {})
            if now_t - last_map.get(key, 0) < 2.0:
                return
            last_map[key] = now_t
            self._last_relay_ts = last_map
        except Exception:
            pass
        for other_profile in list(self.active_sockets.keys()):
            if other_profile == source_profile:
                continue
            asyncio.create_task(self.send_command(other_profile, "TOAST", {
                "title": title,
                "text": text,
                "type": type_,
                "source_profile": source_profile,
                "duration": 2200,
            }))

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
        asyncio.create_task(self.broadcast_partners())

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

    def _resolve_ws(self, profile_name: str) -> tuple[Optional[str], Optional[WebSocket]]:
        """Phân giải WebSocket của profile theo tên, username, character_name, uid hoặc alias."""
        if not profile_name:
            return None, None
        # 1. Trực tiếp
        if profile_name in self.active_sockets:
            return profile_name, self.active_sockets[profile_name]

        # 2. Không phân biệt hoa thường
        p_low = str(profile_name).strip().lower()
        for k, ws in self.active_sockets.items():
            if str(k).strip().lower() == p_low:
                return k, ws

        # 3. Phân giải qua accounts.json
        accounts = self._get_accounts_data()
        matched_account = None
        for a in accounts:
            a_name = str(a.get("name") or "").strip().lower()
            a_user = str(a.get("username") or "").strip().lower()
            a_char = str(a.get("character_name") or "").strip().lower()
            a_id = str(a.get("id") or "").strip().lower()
            a_uid = str(a.get("uid") or "").strip()
            ws_local = (a.get("web_storage") or {}).get("local") or {}
            k_user = str(ws_local.get("KEY_USER_NAME") or "").strip().lower()
            p_user = str(ws_local.get("AUTOTOOL_PROFILE_NAME") or "").strip().lower()

            if (p_low in (a_name, a_user, a_char, a_id, k_user, p_user) or 
                (a_uid and p_low == a_uid) or
                (a_name.replace(" ", "") == p_low.replace(" ", "")) or
                (a_name.replace("0", "") == p_low.replace("0", ""))):
                matched_account = a
                break

        if matched_account:
            candidate_names = [
                str(matched_account.get("name") or ""),
                str(matched_account.get("username") or ""),
                str(matched_account.get("character_name") or ""),
                str(matched_account.get("uid") or ""),
                str(((matched_account.get("web_storage") or {}).get("local") or {}).get("KEY_USER_NAME") or ""),
                str(((matched_account.get("web_storage") or {}).get("local") or {}).get("AUTOTOOL_PROFILE_NAME") or ""),
            ]
            for cand in candidate_names:
                if not cand:
                    continue
                c_low = cand.strip().lower()
                for k, ws in self.active_sockets.items():
                    if str(k).strip().lower() == c_low:
                        return k, ws

        # 4. Phân giải qua profile_states (dn, u, uid)
        for k, st in self.profile_states.items():
            if not st.get("connected"):
                continue
            st_dn = str(st.get("dn") or "").strip().lower()
            st_u = str(st.get("u") or "").strip().lower()
            st_uid = str(st.get("uid") or "").strip()
            if p_low in (st_dn, st_u) or (st_uid and p_low == st_uid):
                if k in self.active_sockets:
                    return k, self.active_sockets[k]

        return None, None

    def is_connected(self, profile_name: str) -> bool:
        """Kiểm tra xem profile có đang kết nối Extension không (hỗ trợ alias)."""
        k, ws = self._resolve_ws(profile_name)
        return bool(ws)

    async def send_command(self, profile_name: str, action: str, data: Optional[dict] = None) -> bool:
        """Bắn lệnh tức thời xuống tab của profile qua Extension Bridge (Độ trễ <2ms, hỗ trợ alias)."""
        resolved_name, ws = self._resolve_ws(profile_name)
        if not ws or not resolved_name:
            log.warning("send_command: Profile '%s' chưa kết nối Extension! (Active: %s)", 
                        profile_name, list(self.active_sockets.keys()))
            return False

        payload = {
            "action": action,
            "profile_name": resolved_name,
            "data": data or {},
            "timestamp": time.time(),
        }

        try:
            await ws.send_text(json.dumps(payload))
            log.info("ExtensionHub V3 -> [%s (alias: %s)] Lệnh '%s' gửi thành công: %s", 
                     resolved_name, profile_name, action, data)
            return True
        except Exception as e:
            log.warning("ExtensionHub V3 -> [%s] Lỗi gửi lệnh '%s': %s", resolved_name, action, e)
            await self.unregister(resolved_name, ws)
            return False

    async def broadcast_command(self, action: str, data: Optional[dict] = None) -> int:
        """Gửi lệnh đồng loạt tới tất cả các profile đang kết nối."""
        sent_count = 0
        for name in list(self.active_sockets.keys()):
            ok = await self.send_command(name, action, data)
            if ok:
                sent_count += 1
        return sent_count

    def _get_accounts_data(self) -> list[dict]:
        """Đọc toàn bộ accounts.json để trích xuất name, username, và các alias trong web_storage."""
        try:
            from models.config_model import load_accounts
            return load_accounts()
        except Exception as e:
            log.warning("ExtensionHub V3: Lỗi đọc accounts.json: %s", e)
            return []

    async def broadcast_partners(self):
        """Đồng bộ danh sách tất cả đồng đội (in-game DN, U, UID và aliases) cho mọi extension đang online."""
        accounts = self._get_accounts_data()
        active_names = list(self.active_sockets.keys())

        # Xây dựng danh sách aliases riêng biệt cho từng tài khoản (dựa trên account ID)
        account_groups = []
        for a in accounts:
            names = set()
            for key_field in ("name", "username", "character_name", "id", "uid", "game_username"):
                val = a.get(key_field)
                if val:
                    names.add(str(val).strip().lower())
            ws_local = (a.get("web_storage") or {}).get("local") or {}
            if ws_local.get("KEY_USER_NAME"):
                names.add(str(ws_local["KEY_USER_NAME"]).strip().lower())
            for k in ws_local.keys():
                if "KEY_SETTING" in k:
                    prefix = k.split("KEY_SETTING")[0].strip().lower()
                    if prefix: names.add(prefix)
                elif "EAuthenticatorKey_" in k:
                    prefix = k.replace("EAuthenticatorKey_", "").strip().lower()
                    if prefix: names.add(prefix)
            account_groups.append({
                "id": str(a.get("id") or a.get("index")),
                "names": names,
            })

        for name in active_names:
            name_low = str(name).strip().lower()
            partners = []

            # 1. Thêm từ các tab browser khác đang kết nối
            for p in active_names:
                p_low = str(p).strip().lower()
                if p_low != name_low:
                    st = self.profile_states.get(p) or {}
                    partners.append(p)
                    if st.get("dn"): partners.append(str(st["dn"]).strip().lower())
                    if st.get("u"): partners.append(str(st["u"]).strip().lower())
                    if st.get("uid"): partners.append(str(st["uid"]).strip())

            # 2. Bổ sung các aliases từ accounts.json của các tài khoản KHÁC (tránh đụng hàng chính mình)
            my_acc_id = None
            for grp in account_groups:
                if name_low in grp["names"]:
                    my_acc_id = grp["id"]
                    break

            for grp in account_groups:
                if grp["id"] != my_acc_id:
                    for alias in grp["names"]:
                        if alias and alias not in partners and alias != name_low:
                            partners.append(alias)

            # Khử trùng lặp
            unique_partners = []
            seen = set()
            for item in partners:
                if str(item).lower() not in seen:
                    seen.add(str(item).lower())
                    unique_partners.append(item)

            log.info("ExtensionHub V3: Đồng bộ %d đồng đội cho '%s': %s",
                     len(unique_partners), name, unique_partners)

            asyncio.create_task(self.send_command(name, "SYNC_PARTNERS", {
                "partners": unique_partners,
                "all_profiles": active_names,
            }))

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

        # 0. Cập nhật Định Danh In-Game (DN, U, UID) từ Extension
        if msg_type in ("AUTOTOOL_INIT_PROFILE", "INIT_PROFILE", "PROFILE_INIT") or msg.get("user_info"):
            u_info = msg.get("user_info") or {}
            dn = u_info.get("dn") or msg.get("dn")
            u = u_info.get("u") or msg.get("u")
            uid = u_info.get("uid") or msg.get("uid")
            if dn: state["dn"] = dn
            if u: state["u"] = u
            if uid: state["uid"] = uid
            asyncio.create_task(self.broadcast_partners())

        # 0b. ĐỒNG BỘ TÊN IN-GAME THỰC TẾ VÀO accounts.json (Tránh lệch ký tự do người dùng nhập sai)
        # Khi game gửi cmd 100 -> Extension bắt được dn/u/uid chính xác -> cập nhật thẳng vào DB
        if msg_type == "AUTOTOOL_USERNAME_SYNC":
            real_dn = msg.get("real_dn") or ""
            real_u  = msg.get("real_u") or ""
            real_uid = msg.get("real_uid") or ""
            if real_dn:
                # Cập nhật state in-memory ngay lập tức
                state["dn"] = real_dn
                if real_u:  state["u"]   = real_u
                if real_uid: state["uid"] = str(real_uid)

                log.info("ExtensionHub V3: >>> AUTO-SYNC tên in-game '%s' -> '%s' (uid=%s) cho profile '%s' <<<",
                         profile_name, real_dn, real_uid, profile_name)

                # Cập nhật accounts.json: ghi đúng real_dn vào trường username
                try:
                    from models.config_model import load_accounts, save_accounts
                    accounts = load_accounts()
                    updated = False
                    for a in accounts:
                        p_low = str(profile_name).strip().lower()
                        a_name = str(a.get("name") or "").strip().lower()
                        a_user = str(a.get("username") or "").strip().lower()
                        a_id = str(a.get("id") or "").strip().lower()
                        a_uid = str(a.get("uid") or "").strip()
                        ws_local = (a.get("web_storage") or {}).get("local") or {}
                        k_user = str(ws_local.get("KEY_USER_NAME") or "").strip().lower()

                        name_match = (
                            p_low == a_name or
                            p_low == a_user or
                            p_low == a_id or
                            p_low == k_user or
                            (real_uid and a_uid == str(real_uid))
                        )
                        if name_match:
                            old_char = a.get("character_name", "")
                            # Ghi đúng tên nhân vật in-game vào character_name (dùng để tìm bàn và so khớp)
                            a["character_name"] = real_dn
                            a["game_username"] = real_dn

                            if real_uid:
                                a["uid"] = str(real_uid)     # ghi UID chính xác
                            if real_u and real_u != real_dn:
                                a["game_username"] = real_u  # lưu thêm game u để tham chiếu
                            updated = True
                            if old_char != real_dn:
                                log.info("ExtensionHub V3: Đã cập nhật character_name '%s' -> '%s' cho profile '%s'",
                                         old_char, real_dn, profile_name)
                            break
                    if updated:
                        save_accounts(accounts)
                except Exception as e:
                    log.warning("ExtensionHub V3: Lỗi cập nhật character_name vào accounts.json: %s", e)

                # Re-broadcast partners để tất cả tab dùng đúng tên mới
                asyncio.create_task(self.broadcast_partners())

                # Thông báo App UI cập nhật tên ngay lập tức
                self._emit({
                    "type": "accounts_updated",
                    "profile_name": profile_name,
                    "character_name": real_dn,
                    "uid": str(real_uid) if real_uid else None,
                })

        # 1. Cập nhật Số Dư (Balance) Realtime từ Extension
        if msg_type in ("BALANCE_UPDATE", "AUTOTOOL_BALANCE_UPDATE"):
            bal = msg.get("balance")
            if bal is None and isinstance(msg.get("data"), dict):
                bal = msg.get("data", {}).get("balance")
            if bal is not None:
                bal_val = _parse_balance(bal)
                if isinstance(bal_val, str):
                    bal_val = bal

                state["balance"] = bal_val
                state["last_balance_ts"] = time.time()
                log.info("ExtensionHub V3: Profile '%s' cập nhật số dư mới: %s", profile_name, bal_val)

                # Cập nhật và lưu vào accounts.json (khớp mềm theo mọi alias: name/username/character_name/uid...)
                matched_profile = profile_name
                try:
                    from models.config_model import load_accounts, save_accounts
                    accounts = load_accounts()
                    updated = False
                    for a in accounts:
                        if _match_account(a, profile_name):
                            a["balance"] = bal_val
                            matched_profile = a.get("name") or profile_name
                            updated = True
                            break
                    if updated:
                        save_accounts(accounts)
                except Exception as e:
                    log.warning("Lỗi lưu balance vào accounts.json: %s", e)

                self._emit({
                    "type": "accounts_updated",
                    "profile_name": matched_profile,
                    "balance": bal_val,
                })

        # 2. Cập nhật Log Tiến Trình Realtime từ Extension
        elif msg_type in ("LOG_UPDATE", "AUTOTOOL_LOG_UPDATE"):
            log_text = msg.get("log")
            if not log_text and isinstance(msg.get("data"), dict):
                log_text = msg.get("data", {}).get("log")
            if log_text:
                state["log"] = str(log_text)
                state["last_log_ts"] = time.time()
                matched_profile = profile_name
                try:
                    from models.config_model import load_accounts, save_accounts
                    accounts = load_accounts()
                    updated = False
                    for a in accounts:
                        if _match_account(a, profile_name):
                            a["log"] = str(log_text)
                            matched_profile = a.get("name") or profile_name
                            updated = True
                            break
                    if updated:
                        save_accounts(accounts)
                except Exception:
                    pass

                self._emit({
                    "type": "accounts_updated",
                    "profile_name": matched_profile,
                    "log": str(log_text),
                })

        # 3. Cập nhật thông tin bàn cược & Tự động điều phối ID phòng tức thời (<2ms)
        elif msg_type in ("ROOM_INFO", "ROOM_UPDATE", "AUTOTOOL_ROOM_INFO", "ANCHOR_ROOM_VERIFIED_EMPTY", "AUTOTOOL_ANCHOR_ROOM_VERIFIED_EMPTY"):
            ri = msg.get("room_info") or msg.get("data")
            if ri and isinstance(ri, dict):
                rid = ri.get("rid") or "Chống Vây"
                state["room_info"] = ri
                state["room_id"] = rid
                room_display = f"Bàn #{rid}" if str(rid).isdigit() else f"Bàn {rid}"
                state["log"] = f"{room_display} (${ri.get('b', 100)})"
                matched_profile = profile_name
                try:
                    from models.config_model import load_accounts, save_accounts
                    accounts = load_accounts()
                    for a in accounts:
                        if _match_account(a, profile_name):
                            a["room"] = rid
                            a["log"] = room_display
                            matched_profile = a.get("name") or profile_name
                            save_accounts(accounts)
                            break
                except Exception:
                    pass

                self._emit({
                    "type": "room_info_updated",
                    "profile_name": matched_profile,
                    "room_info": ri,
                })
                self._emit({
                    "type": "accounts_updated",
                    "profile_name": matched_profile,
                    "room": rid,
                })

                # KIỂM TRA ĐIỀU KIỆN CHÍNH XÁC: BÀN TRỐNG ĐÃ XÁC THỰC 100% (CHỈ CÓ 1 MÌNH ANCHOR)
                # Chỉ phát lệnh mời B khi có xác nhận rõ ràng bàn trống (không khách lạ, không partner)
                is_verified_empty = (
                    msg_type in ("ANCHOR_ROOM_VERIFIED_EMPTY", "AUTOTOOL_ANCHOR_ROOM_VERIFIED_EMPTY")
                    or (ri.get("is_verified_empty") is True and ri.get("player_count") == 1)
                )
                has_stranger = ri.get("has_stranger") or bool(msg.get("guests"))
                partner_found = ri.get("partner_found")

                if has_stranger:
                    log.info("ExtensionHub V3: Profile '%s' vào bàn có khách lạ -> KHÔNG gửi lệnh join cho đồng đội!", profile_name)
                    self.relay_toast(profile_name,
                                     f"Bàn #{rid} có NGƯỜI LẠ — đồng đội đừng vào; sẽ out & tìm bàn trống khác",
                                     "warn", f"⚠️ {profile_name}")
                elif not getattr(self, "_room_share_enabled", True):
                    # User đã bấm Dừng -> chặn mọi lệnh mời tự động phát ra trễ (zombie gom bàn)
                    log.info("ExtensionHub V3: room_share ĐANG TẮT (đã Dừng) -> bỏ qua phát lệnh mời bàn #%s từ '%s'", rid, profile_name)
                elif is_verified_empty and not partner_found:
                    # Hub KHÔNG được tự gửi JOIN_ROOM. Trước đây nó forward theo
                    # ri.get('b') — mức cược do chính client báo — nên dễ mời
                    # Account phụ vào bàn sai mức (100 -> 500), và phụ có thể
                    # vào TRƯỚC khi anchor kịp xác minh mình còn ngồi một mình.
                    # Nay controller là nguồn DUY NHẤT cấp vé join, sau khi đã
                    # kiểm anchor đúng RID + đúng mức cược + còn một mình.
                    # Xem gate cấp vé trong auto_flow_controller/matching.py.
                    log.warning(
                        "ExtensionHub V3: bỏ qua auto-forward bàn #%s từ '%s'; "
                        "chỉ controller được phép mời Account phụ.", rid, profile_name)

        # 3b. HỦY LỆNH MỜI VÀO BÀN KHI ANCHOR PHÁT HIỆN NGƯỜI LẠ / BÀN FULL
        elif msg_type in ("CANCEL_ROOM_INVITE", "AUTOTOOL_CANCEL_ROOM_INVITE"):
            rid = msg.get("rid") or (state.get("room_info") and state["room_info"].get("rid"))
            reason = msg.get("reason") or "Phát hiện người lạ / Bàn full"
            log.warning("ExtensionHub V3: Profile '%s' HỦY LỆNH MỜI BÀN #%s (%s) -> LẬP TỨC GỬI LEAVE_ROOM CHO CÁC PROFILE PHỤ!",
                        profile_name, rid, reason)
            self.relay_toast(profile_name,
                             f"HỦY bàn #{rid}: {reason} — chủ bàn out tìm bàn trống khác, đứng yên chờ lệnh",
                             "warn", f"🔄 {profile_name}")
            self._last_shared_room = None
            self._last_broadcast_rid = None
            for other_profile in list(self.active_sockets.keys()):
                if other_profile != profile_name:
                    log.info("ExtensionHub V3: >>> Buộc profile '%s' rời phòng / hủy lệnh join về sảnh ngay! <<<", other_profile)
                    asyncio.create_task(self.send_command(other_profile, "LEAVE_ROOM", {
                        "reason": f"Chủ bàn {profile_name} hủy bàn #{rid}: {reason}",
                        "source": profile_name,
                    }))

        # 3c. PROFILE TỰ RỜI BÀN (khách lạ / hết giờ / sai bàn...) -> báo realtime cho đồng đội
        elif msg_type in ("AUTO_LEAVING", "AUTOTOOL_AUTO_LEAVING"):
            reason = msg.get("reason") or "Tự rời bàn"
            state["log"] = f"Đã rời bàn ({reason})"
            log.info("ExtensionHub V3: Profile '%s' rời bàn: %s", profile_name, reason)
            self.relay_toast(profile_name,
                             f"Đã out bàn: {reason} — đang tìm bàn trống thực sự, chờ lệnh vào tiếp",
                             "info", f"🚪 {profile_name}")
            self._last_shared_room = None
            self._last_broadcast_rid = None

        # 4. Xác nhận khớp bàn thành công giữa các đối tác (Cứu hẹn giờ out)
        elif msg_type in ("PARTNER_MATCHED", "AUTOTOOL_MATCH_SUCCESS"):
            partner_name = msg.get("partner_name")
            # CHẶN: Không gửi CONFIRM_MATCH nếu partner_name là None/rỗng (tránh vòng lặp vô hạn)
            if not partner_name or str(partner_name).strip().lower() in ("none", ""):
                log.warning("ExtensionHub V3: BỎ QUA CONFIRM_MATCH từ '%s' vì partner_name=%r (chưa xác định đồng đội)!",
                            profile_name, partner_name)
            else:
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

        # 5. Cập nhật bài được chia / đánh bài
        elif msg_type in ("CARDS_DEALT", "HAND_INFO", "CARDS_UPDATED", "AUTOTOOL_CARDS_DEALT", "AUTOTOOL_CARDS_UPDATED"):
            cards = msg.get("cards")
            if cards is None and isinstance(msg.get("data"), dict):
                cards = msg.get("data", {}).get("cards")
            if isinstance(cards, list):
                state["cards"] = cards
                matched_n = profile_name
                try:
                    from models.config_model import load_accounts, save_accounts
                    accounts = load_accounts()
                    for a in accounts:
                        if _match_account(a, profile_name):
                            a["cards"] = cards
                            matched_n = a.get("name") or profile_name
                            save_accounts(accounts)
                            break
                except Exception:
                    pass

                self._emit({
                    "type": "cards_updated",
                    "profile_name": profile_name,
                    "cards": cards,
                })
                self._emit({
                    "type": "accounts_updated",
                    "profile_name": profile_name,
                    "cards": cards,
                })
                if matched_n != profile_name:
                    self._emit({
                        "type": "cards_updated",
                        "profile_name": matched_n,
                        "cards": cards,
                    })
                    self._emit({
                        "type": "accounts_updated",
                        "profile_name": matched_n,
                        "cards": cards,
                    })

                # Chuyển tiếp bài đồng đội sang các tab khác cùng online (<2ms)
                for other_profile in list(self.active_sockets.keys()):
                    if other_profile != profile_name:
                        asyncio.create_task(self.send_command(other_profile, "PARTNER_CARDS_SHARED", {
                            "source_profile": profile_name,
                            "cards": cards,
                        }))

        # 6. Trạng thái rời bàn / Đang ở sảnh -> XÓA SẠCH BÀI TRÊN TAY
        elif msg_type in ("ROOM_LEFT", "LEAVE_ROOM", "AUTOTOOL_ROOM_LEFT"):
            state["room_info"] = None
            state["room_id"] = -1
            state["log"] = "Đang ở sảnh (Chưa vào bàn)"
            state["players"] = []
            state["cards"] = []
            matched_n = profile_name
            try:
                from models.config_model import load_accounts, save_accounts
                accounts = load_accounts()
                for a in accounts:
                    if _match_account(a, profile_name):
                        a["room"] = -1
                        a["log"] = "Đang ở sảnh (Chưa vào bàn)"
                        a["cards"] = []
                        matched_n = a.get("name") or profile_name
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
                "log": "Đang ở sảnh (Chưa vào bàn)",
                "cards": [],
            })
            self._emit({
                "type": "cards_updated",
                "profile_name": profile_name,
                "cards": [],
            })
            if matched_n != profile_name:
                self._emit({
                    "type": "accounts_updated",
                    "profile_name": matched_n,
                    "room": -1,
                    "log": "Đang ở sảnh (Chưa vào bàn)",
                    "cards": [],
                })
                self._emit({
                    "type": "cards_updated",
                    "profile_name": matched_n,
                    "cards": [],
                })

    def get_profile_state(self, profile_name: str) -> dict:
        """Lấy thông tin trạng thái mới nhất của profile (hỗ trợ so khớp mềm)."""
        if not profile_name:
            return {"profile_name": "", "connected": False, "room_info": None, "players": [], "cards": []}
        if profile_name in self.profile_states:
            return self.profile_states[profile_name]
        p_clean = "".join(c for c in profile_name.lower() if c.isalnum())
        for k, v in self.profile_states.items():
            k_clean = "".join(c for c in k.lower() if c.isalnum())
            if k_clean == p_clean or (p_clean.endswith("1") and k_clean.endswith("1")) or (p_clean.endswith("2") and k_clean.endswith("2")):
                return v
        return {
            "profile_name": profile_name,
            "connected": False,
            "room_info": None,
            "players": [],
            "cards": [],
        }

    def get_status(self) -> dict:
        """Báo cáo tổng thể toàn bộ kết nối Extension Hub."""
        return {
            "version": "3.0.0",
            "hub_name": "Multi-Profile Extension Bridge Hub",
            "connected_count": len(self.active_sockets),
            "connected_profiles": list(self.active_sockets.keys()),
            "states": self.profile_states,
        }

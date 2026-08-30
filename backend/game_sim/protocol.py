"""Protocol Learner — học + cache WS protocol game từ capture thực tế.

Thay vì hardcode join/ready/leave/auth frames, học từ WS messages thật
bắt được khi game client hoạt động (CAPTURE mode hoặc lần chạy đầu).
Lưu protocol.json để tái sử dụng giữa các lần chạy.

Thứ tự ưu tiên khi gửi lệnh:
  1. Protocol đã học (protocol.json) + verify khớp live socket
  2. Học từ capture hiện tại (_PAGE_RECV + drain)
  3. Config game.ws_patterns (user cấu hình thủ công)
  4. Hardcoded mặc định (LAST RESORT, log warning)

Các key học được:
  - channel: tên kênh game ("Simms") — từ auth frame [1,"channel",...]
  - socket_urls: danh sách URL WS live — từ Playwright ws event
  - join: template join bàn cụ thể, chứa {room_id}
  - join_quick: template join nhanh (quick match)
  - ready: frame auto-ready (cmd=363)
  - leave: frame rời bàn
  - room_list: template liệt kê bàn, chứa {gid}
  - auth_frame: template auth, chứa {token}
  - agent_id: agentId từ auth frame
  - token_prefix: prefix token (vd "1-")
"""
import json
import logging
from pathlib import Path

log = logging.getLogger("protocol")

# Hardcoded defaults — chỉ dùng khi CHƯA học được gì (last resort).
_DEFAULTS = {
    "channel": "Simms",
    "join": '[3,"Simms",1,"{room_id}"]',
    "join_quick": '[3,"Simms",2,""]',
    "ready": '[6,"Simms","channelPlugin",{"cmd":363,"aRd":"true"}]',
    "leave": '[4,"Simms",-1]',
    "room_list": '[6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":{gid}}]',
    "auth_frame": '[1,"Simms","","",{"agentId":"1","accessToken":"{token}","reconnect":false}]',
    "agent_id": "1",
    "token_prefix": "1-",
}


class ProtocolLearner:
    """Học protocol WS từ capture, cache xuống protocol.json."""

    def __init__(self, save_path):
        self.save_path = Path(save_path)
        self._learned = {}
        self._dirty = False
        self.load()

    # ---- persistence ----
    def load(self):
        try:
            if self.save_path.exists():
                data = json.loads(self.save_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._learned = data
                    log.info("protocol loaded from %s (%d keys)", self.save_path.name, len(data))
        except Exception as e:
            log.warning("protocol load fail: %s", e)

    def save(self):
        if not self._dirty:
            return
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            self.save_path.write_text(
                json.dumps(self._learned, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._dirty = False
            log.info("protocol saved -> %s", self.save_path)
        except Exception as e:
            log.warning("protocol save fail: %s", e)

    # ---- accessors ----
    def get(self, key: str, default=None):
        """Trả giá trị đã học, fallback default, rồi fallback _DEFAULTS."""
        val = self._learned.get(key)
        if val is not None:
            return val
        if default is not None:
            return default
        return _DEFAULTS.get(key)

    def set(self, key: str, value):
        if self._learned.get(key) != value:
            self._learned[key] = value
            self._dirty = True

    def has(self, key: str) -> bool:
        return key in self._learned

    def all(self) -> dict:
        """Toàn bộ protocol đã học (cho API debug)."""
        return dict(self._learned)

    def clear(self):
        self._learned = {}
        self._dirty = True

    # ---- học từ captured messages ----
    def learn_from_msgs(self, msgs: list, known_room_id=None) -> dict:
        """Phân tích captured WS messages, trích protocol templates.

        msgs: [{"dir": "send"|"recv"|"inject", "text": str}, ...]
        known_room_id: nếu biết, dò SEND frame chứa rid này để tìm join template.

        Trả dict {key: True/False} cho biết học được gì.
        """
        learned = {}
        for it in msgs:
            if it.get("dir") not in ("send", "inject"):
                continue
            text = it.get("text", "")
            try:
                arr = json.loads(text)
            except Exception:
                continue
            if not isinstance(arr, list) or len(arr) < 2:
                continue

            # --- Auth frame: [1,"channel","","",{...}] ---
            if arr[0] == 1 and isinstance(arr[1], str) and arr[1]:
                self._learn_auth_frame(arr, text)
                learned["channel"] = True

            # --- Join bàn cụ thể: [3,"channel",1,"<rid>"] ---
            if len(arr) >= 4 and arr[0] == 3 and arr[2] == 1:
                rid_str = str(arr[3]) if arr[3] else ""
                if rid_str and rid_str not in ("", "{}", "null"):
                    template = self._replace_once(text, rid_str, "{room_id}")
                    if template != text:
                        self.set("join", template)
                        learned["join"] = True

            # --- Join nhanh: [3,"channel",2,""] ---
            if len(arr) >= 3 and arr[0] == 3 and arr[2] == 2:
                # giữ nguyên, thay channel nếu cần
                self.set("join_quick", text)
                learned["join_quick"] = True

            # --- Leave: [4,"channel",...] ---
            if arr[0] == 4:
                self.set("leave", text)
                learned["leave"] = True

            # --- Plugin commands: [6,"channel","<plugin>",{payload}] ---
            if len(arr) >= 4 and isinstance(arr[3], dict) and "cmd" in arr[3]:
                cmd = arr[3].get("cmd")
                if cmd == 363:
                    self.set("ready", text)
                    learned["ready"] = True
                elif cmd == 300:
                    # Thay gid bằng placeholder {gid}
                    gid_val = arr[3].get("gid")
                    if gid_val is not None:
                        template = self._replace_once(text, str(gid_val), "{gid}")
                        # chỉ thay số, không thay trong string key
                        if "{gid}" in template:
                            self.set("room_list", template)
                            learned["room_list"] = True

            # --- cmd=308 SEND (format cũ hơn): [6,"ch","channelPlugin",{"cmd":308,...,"rid":N}] ---
            if len(arr) >= 4 and isinstance(arr[3], dict):
                cmd = arr[3].get("cmd")
                if cmd == 308 and "rid" in arr[3]:
                    rid_val = arr[3]["rid"]
                    # thay rid bằng placeholder
                    new_payload = dict(arr[3])
                    new_payload["rid"] = "{room_id}"
                    new_arr = list(arr)
                    new_arr[3] = new_payload
                    template = json.dumps(new_arr, ensure_ascii=False)
                    self.set("join", template)
                    learned["join_cmd308"] = True

        # Lưu nếu học được gì mới
        if learned:
            self.save()
            log.info("protocol learned: %s", list(learned.keys()))
        return learned

    def _learn_auth_frame(self, arr: list, text: str):
        """Học từ auth frame [1,"channel","","",{agentId, accessToken, ...}]."""
        channel = arr[1]
        self.set("channel", channel)

        # Trích payload auth (index 4 nếu có)
        payload = arr[4] if len(arr) > 4 and isinstance(arr[4], dict) else {}
        agent_id = str(payload.get("agentId", "1"))
        self.set("agent_id", agent_id)

        # Token prefix: accessToken thường có dạng "<agentId>-<hex>"
        access_token = payload.get("accessToken", "")
        if access_token and "-" in str(access_token):
            prefix = str(access_token).split("-")[0] + "-"
            self.set("token_prefix", prefix)

        # Build auth template: thay accessToken bằng {token}
        if access_token:
            template = self._replace_once(text, str(access_token), "{token}")
            if template != text:
                self.set("auth_frame", template)

    @staticmethod
    def _replace_once(text: str, old: str, new: str) -> str:
        """Thay lần xuất hiện ĐẦU TIÊN của old bằng new (tránh thay nhầm)."""
        idx = text.find(old)
        if idx == -1:
            return text
        return text[:idx] + new + text[idx + len(old):]

    # ---- học từ live state ----
    def learn_channel_from_page(self, page) -> str | None:
        """Đọc channel đã nhận diện từ _PAGE_CHANNEL (inject_playwright đã parse)."""
        from game_sim.ws_sniffer import _PAGE_CHANNEL

        channels = _PAGE_CHANNEL.get(id(page), {})
        if channels:
            # Lấy channel đầu tiên (thường chỉ có 1 game channel chính)
            ch = next(iter(channels.values()))
            if ch:
                self.set("channel", ch)
                return ch
        return None

    def learn_socket_urls(self, page) -> list:
        """Đọc URL socket live từ _PAGE_SOCKETS."""
        from game_sim.ws_sniffer import _PAGE_SOCKETS

        socks = _PAGE_SOCKETS.get(id(page), {})
        urls = []
        seen = set()
        for ws in socks.values():
            u = getattr(ws, "url", "")
            if u and u not in seen:
                urls.append(u)
                seen.add(u)
        if urls:
            self.set("socket_urls", urls)
            self.save()
        return urls

    def learn_token_prefix(self, page_token: str):
        """Học token prefix từ token thực tế (vd "1-abc..." -> "1-")."""
        if page_token and "-" in page_token:
            prefix = page_token.split("-")[0] + "-"
            self.set("token_prefix", prefix)

    # ---- verify ----
    def verify_live(self, page) -> dict:
        """Kiểm tra protocol đã học còn khớp với live socket không.

        Trả {"channel_ok": bool, "socket_ok": bool, "details": str}
        """
        result = {"channel_ok": False, "socket_ok": False, "details": ""}

        # Check channel
        live_ch = self.learn_channel_from_page(page)
        saved_ch = self.get("channel")
        if live_ch and saved_ch:
            result["channel_ok"] = (live_ch == saved_ch)
            if not result["channel_ok"]:
                result["details"] += f"channel changed: {saved_ch} -> {live_ch}. "

        # Check socket URLs
        live_urls = self.learn_socket_urls(page)
        saved_urls = self.get("socket_urls", [])
        if live_urls:
            result["socket_ok"] = bool(set(live_urls) & set(saved_urls)) if saved_urls else True
            if saved_urls and not result["socket_ok"]:
                result["details"] += f"socket URLs changed. "

        return result

    # ---- build helpers ----
    def build_join_msg(self, rid, template=None) -> str:
        """Build message join với room id cụ thể."""
        tpl = template or self.get("join")
        if tpl and "{room_id}" in tpl:
            return tpl.replace("{room_id}", str(rid))
        # fallback hardcoded
        ch = self.get("channel", "Simms")
        log.warning("protocol: no join template learned, using hardcoded for rid=%s", rid)
        return f'[3,"{ch}",1,"{rid}"]'

    def build_room_list_msg(self, gid=1) -> str:
        """Build message liệt kê bàn."""
        tpl = self.get("room_list")
        if tpl and "{gid}" in tpl:
            return tpl.replace("{gid}", str(int(gid)))
        ch = self.get("channel", "Simms")
        log.warning("protocol: no room_list template learned, using hardcoded")
        return f'[6,"{ch}","channelPlugin",{{"cmd":300,"aid":"{self.get("agent_id", "1")}","gid":{int(gid)}}}]'

    def build_auth_frame(self, access_token: str) -> list:
        """Build auth/connect frame cho side socket."""
        ch = self.get("channel", "Simms")
        agent_id = self.get("agent_id", "1")
        prefix = self.get("token_prefix", "1-")
        # Đảm bảo token có đúng prefix
        if isinstance(access_token, str) and not access_token.startswith(prefix):
            access_token = prefix + access_token
        return [1, ch, "", "", {"agentId": agent_id, "accessToken": access_token, "reconnect": False}]

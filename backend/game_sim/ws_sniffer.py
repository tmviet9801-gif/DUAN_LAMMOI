"""WS Sniffer — hook WebSocket trong page để bắt + gửi message protocol game.

Game canvas (Cocos2d + Wasm) giao tiếp server qua WebSocket. Inject JS hook:
- Ghi mọi message (send/recv) vào `window.__ws_capture`.
- Expose `window.__ws_send(text)` để GỬI message qua socket gần nhất
  (dùng cho việc join phòng theo room id bắt được).
- Tách room id + template join từ capture (dò theo regex cấu hình).
"""
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("ws_sniffer")

_INJECT_JS = r"""
(() => {
  if (window.__ws_hooked) return;
  window.__ws_hooked = true;
  window.__ws_capture = [];
  window.__ws_last = null;
  const orig = window.WebSocket;
  const push = (dir, data) => {
    try {
      let text = "";
      if (typeof data === "string") text = data;
      else if (data instanceof Blob) text = "[Blob " + data.size + "b]";
      else if (data instanceof ArrayBuffer) text = new TextDecoder().decode(data);
      else if (data && data.data !== undefined) text = typeof data.data === "string" ? data.data : "[binary]";
      else text = "[?]";
      window.__ws_capture.push({ ts: Date.now(), dir, text: String(text).slice(0, 8000) });
      if (window.__ws_capture.length > 3000) window.__ws_capture.splice(0, 1500);
    } catch (e) {}
  };
  window.WebSocket = function (...args) {
    const ws = new orig(...args);
    window.__ws_last = ws;
    const send = ws.send.bind(ws);
    ws.send = (data) => { push("send", data); try { return send(data); } catch (e) {} };
    ws.addEventListener("message", (e) => push("recv", e.data));
    return ws;
  };
  window.WebSocket.prototype = orig.prototype;
  window.WebSocket.CONNECTING = orig.CONNECTING;
  window.WebSocket.OPEN = orig.OPEN;
  window.WebSocket.CLOSING = orig.CLOSING;
  window.WebSocket.CLOSED = orig.CLOSED;
  window.__ws_send = (text) => {
    try {
      if (window.__ws_last && window.__ws_last.readyState === 1) {
        window.__ws_last.send(text);
        window.__ws_capture.push({ ts: Date.now(), dir: "inject", text: String(text) });
        return true;
      }
    } catch (e) {}
    return false;
  };
})();
"""


class WsSniffer:
    def __init__(self, save_dir):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.save_dir / "ws_capture.jsonl"

    async def inject(self, page):
        if not page:
            return False
        try:
            await page.evaluate(_INJECT_JS)
            return True
        except Exception as e:
            log.warning("inject ws hook fail: %s", e)
            return False

    async def drain(self, page):
        """Đọc + xóa capture trong page, ghi tiếp vào file JSONL."""
        if not page:
            return 0
        try:
            items = await page.evaluate(
                "() => { const c = window.__ws_capture || []; window.__ws_capture = []; return c; }"
            )
        except Exception:
            return 0
        if not items:
            return 0
        lines = [json.dumps(it, ensure_ascii=False) for it in items]
        with self._file.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log.info("ws sniffer drained %d messages -> %s", len(items), self._file.name)
        return len(items)

    async def send_raw(self, page, text: str) -> bool:
        """Gửi 1 message raw qua WS của page (dùng cho join room theo room id)."""
        if not page:
            return False
        try:
            ok = await page.evaluate(f"window.__ws_send && window.__ws_send({json.dumps(text)})")
            return bool(ok)
        except Exception as e:
            log.warning("ws send_raw fail: %s", e)
            return False

    @property
    def capture_file(self) -> Path:
        return self._file

    def recent(self, limit=200) -> list:
        if not self._file.exists():
            return []
        items = []
        with self._file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    pass
        return items[-limit:]

    def search(self, keyword: str, limit=100) -> list:
        return [it for it in self.recent(5000) if keyword.lower() in it.get("text", "").lower()][-limit:]

    # ---- phân tích room id + template join ----
    @staticmethod
    def find_room_ids(msgs: list, regexes: list) -> list:
        """Dò capture tìm room id theo các regex cấu hình."""
        ids = []
        for it in msgs:
            text = it.get("text", "")
            for rx in regexes or []:
                try:
                    for m in re.finditer(rx, text, re.I):
                        rid = m.group(1) if m.lastindex else m.group(0)
                        if rid and rid not in ids:
                            ids.append(rid)
                except Exception:
                    continue
        return ids

    @staticmethod
    def build_join_template(msgs: list, room_id_regexes: list) -> str | None:
        """Tìm message SEND gần nhất chứa room id → trả template (room id -> {room_id}).

        Dùng để phát lại đúng format join với room id mới.
        """
        for it in reversed(msgs):
            if it.get("dir") not in ("send", "inject"):
                continue
            text = it.get("text", "")
            for rx in room_id_regexes or []:
                try:
                    m = re.search(rx, text, re.I)
                    if m:
                        rid = m.group(1) if m.lastindex else m.group(0)
                        if rid:
                            template = text.replace(rid, "{room_id}")
                            return template
                except Exception:
                    continue
        return None

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
import time
from pathlib import Path

log = logging.getLogger("ws_sniffer")

# socket WS thật bắt được qua Playwright, chia sẻ mọi instance sniffer,
# keyed by id(page) — vì mỗi adapter tạo 1 sniffer riêng nhưng page object là chung.
_PAGE_WS = {}

_INJECT_JS = r"""
(() => {
  if (window.__ws_hooked) return;
  window.__ws_hooked = true;
  window.__ws_capture = [];
  window.__ws_map = {};
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
    const url = String(args[0] || "");
    window.__ws_map[url] = ws;
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
  // gửi qua socket có URL chứa channel (vd "carkgwaiz" = Simms)
  window.__ws_send_channel = (channel, text) => {
    try {
      for (const url in window.__ws_map) {
        if (url.indexOf(channel) !== -1) {
          const ws = window.__ws_map[url];
          if (ws && ws.readyState === 1) {
            ws.send(text);
            window.__ws_capture.push({ ts: Date.now(), dir: "inject", text: String(text) });
            return true;
          }
        }
      }
    } catch (e) {}
    return false;
  };
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


# Mở 1 WS phụ từ page (KHÔNG reload, không động vào session game đang login)
# để gửi lệnh join bàn. Dùng accessToken + URL WS thực tế từ localStorage của account.
_SIDE_SOCK_JS = r"""
(async (url, accessToken, cmd, connectFrame) => {
  return await new Promise((resolve) => {
    const out = [];
    let done = false;
    const readData = async (data) => {
      try {
        if (data instanceof Blob) return await data.text();
        if (data instanceof ArrayBuffer) return new TextDecoder().decode(data);
        return String(data);
      } catch (e) { return String(data); }
    };
    const finish = () => { if (!done) { done = true; resolve(out); } };
    let ws;
    try { ws = new WebSocket(url); } catch (e) { resolve(["ERR:" + e]); return; }
    const t0 = Date.now();
    ws.onopen = () => {
      try {
        ws.send(JSON.stringify(connectFrame));
        ws.send(cmd);
      } catch (e) { out.push("SEND_ERR:" + e); }
    };
    ws.onmessage = async (e) => {
      const t = await readData(e.data);
      out.push(t.slice(0, 8000));
      if (Date.now() - t0 > 4000 || out.length >= 8) finish();
    };
    ws.onerror = () => { out.push("WS_ERR"); finish(); };
    setTimeout(finish, 6000);
  });
})
"""


class WsSniffer:
    def __init__(self, save_dir):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.save_dir / "ws_capture.jsonl"
        # socket WS thật bắt được qua Playwright, phân theo từng page (id(page))
        self._page_ws = {}

    async def side_command(self, page, urls, access_token, cmd, connect_frame=None):
        """Mở WS phụ tới 1 trong các url, gửi frame auth + cmd, trả về list message.

        Thử từng url đến khi nhận được response thực sự (không chỉ ERR).
        Không reload, không ảnh hưởng session game đang login của user.
        """
        if not page or not urls or not access_token:
            return []
        if isinstance(urls, str):
            urls = [urls]
        if connect_frame is None:
            connect_frame = [1, "Simms", "", "", {"agentId": "1", "accessToken": access_token, "reconnect": False}]
        for url in urls:
            try:
                out = await page.evaluate(_SIDE_SOCK_JS, url, access_token, cmd, connect_frame)
            except Exception as e:
                log.warning("side_command fail url=%s: %s", url, e)
                continue
            out = out or []
            if any(not str(m).startswith(("ERR", "WS_ERR", "SEND_ERR")) for m in out):
                return out
        return []

    async def inject(self, page):
        if not page:
            return False
        try:
            await page.evaluate(_INJECT_JS)
            return True
        except Exception as e:
            log.warning("inject ws hook fail: %s", e)
            return False

    async def inject_init(self, page):
        """Inject hook qua add_init_script — chạy TRƯỚC mọi script của game,
        tồn tại qua reload/navigation nên bắt được cả socket persistent.

        Lưu ý: cần reload sau khi gọi để game kết nối WS qua hook.
        """
        if not page:
            return False
        try:
            await page.add_init_script(_INJECT_JS)
            return True
        except Exception as e:
            log.warning("inject ws init hook fail: %s", e)
            return False

    async def inject_playwright(self, page):
        """Dùng page.on('websocket') của Playwright — bắt mọi WS kể cả trong Web Worker.
        
        Ghi toàn bộ message vào ws_capture.jsonl + riêng cmd=300/305/308/202 vào room_debug.jsonl.
        """
        if not page:
            return False
        self._room_file = self.save_dir / "room_debug.jsonl"
        try:
            async def _on_ws(ws):
                url = ws.url
                log.info("ws captured: %s", url)
                # ưu tiên socket "Simms" (host carkgwaiz) để gửi lệnh join/raw.
                # lưu trực tiếp lên page object để mọi adapter truy cập được
                # (page_pool cache cùng 1 page object qua các lời gọi).
                if "carkgwaiz" in url or "Simms" in url:
                    _PAGE_WS[id(page)] = ws

                def _on_send(data):
                    self._save({"ts": int(time.time() * 1000), "dir": "send", "text": str(data)[:8000], "url": url})
                    self._save_room({"ts": int(time.time() * 1000), "dir": "send", "text": str(data)[:8000]})

                def _on_recv(data):
                    self._save({"ts": int(time.time() * 1000), "dir": "recv", "text": str(data)[:8000], "url": url})
                    self._save_room({"ts": int(time.time() * 1000), "dir": "recv", "text": str(data)[:8000]})

                ws.on("framesent", _on_send)
                ws.on("framereceived", _on_recv)

            page.on("websocket", _on_ws)
            return True
        except Exception as e:
            log.warning("inject_playwright ws fail: %s", e)
            return False

    async def inject_http(self, page):
        """Bắt HTTP request/response (login API, config...) qua page.on('request'/'response')."""
        if not page:
            return False
        self._http_file = self.save_dir / "http_capture.jsonl"
        try:
            def _on_request(req):
                try:
                    post = None
                    if req.method in ("POST", "PUT"):
                        post = req.post_data or ""
                    self._save_http({
                        "ts": int(time.time() * 1000), "dir": "req",
                        "method": req.method, "url": req.url[:500], "post": post[:2000],
                    })
                except Exception:
                    pass

            async def _on_response(resp):
                try:
                    body = None
                    if resp.request.method == "POST":
                        try:
                            b = await resp.body()
                            body = b.decode("utf-8", errors="replace")[:2000]
                        except Exception:
                            pass
                    self._save_http({
                        "ts": int(time.time() * 1000), "dir": "resp",
                        "status": resp.status, "url": resp.url[:500], "body": body,
                    })
                except Exception:
                    pass

            page.on("request", _on_request)
            page.on("response", _on_response)
            return True
        except Exception as e:
            log.warning("inject_http fail: %s", e)
            return False

    def _save_http(self, item: dict):
        try:
            f = getattr(self, "_http_file", None) or (self.save_dir / "http_capture.jsonl")
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _save(self, item: dict):
        """Ghi 1 item vào file JSONL (thread-safe-ish)."""
        try:
            line = json.dumps(item, ensure_ascii=False)
            with self._file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            log.warning("ws save fail: %s", e)

    def _save_room(self, item: dict):
        """Ghi riêng message phòng (cmd=300/305/308/202) vào room_debug.jsonl."""
        try:
            text = item.get("text", "")
            if not any(c in text for c in ['"cmd":300', '"cmd":305', '"cmd":308', '"cmd":202']):
                return
            f = getattr(self, "_room_file", None) or (self.save_dir / "room_debug.jsonl")
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception:
            pass

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
        """Gửi 1 message raw qua WS của page (dùng cho join room theo room id).

        Ưu tiên Playwright socket (`page.on('websocket')` bắt được mọi WS kể cả
        Worker), fallback JS hook trên mọi frame/socket.
        """
        if not page:
            return False
        # 1) Playwright socket (bắt qua inject_playwright)
        try:
            ws = _PAGE_WS.get(id(page))
            if ws is not None:
                ws.send(text)
                self._save({"ts": int(time.time() * 1000), "dir": "inject", "text": str(text)[:8000], "url": "playwright_ws"})
                return True
        except Exception:
            pass
        # 2) JS hook: mọi frame, mọi socket
        frames = [page] + page.frames
        for f in frames:
            try:
                ok = await f.evaluate(f"""
                    (() => {{
                        const map = window.__ws_map || {{}};
                        const text = {json.dumps(text)};
                        for (const url in map) {{
                            const ws = map[url];
                            if (ws && ws.readyState === 1) {{
                                try {{ ws.send(text); return true; }} catch(e) {{}}
                            }}
                        }}
                        return false;
                    }})()
                """)
                if ok:
                    self._save({"ts": int(time.time() * 1000), "dir": "inject", "text": str(text)[:8000], "url": f"frame:{f.url[:80]}"})
                    return True
            except Exception:
                pass
        # 3) fallback: socket cuối cùng (main frame)
        try:
            ok = await page.evaluate(f"window.__ws_send && window.__ws_send({json.dumps(text)})")
            if ok:
                return True
            return False
        except Exception:
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

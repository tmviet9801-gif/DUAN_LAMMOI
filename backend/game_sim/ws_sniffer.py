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

# Toàn bộ socket theo page + channel (từ auth frame [1,"<channel>",...]):
_PAGE_SOCKETS = {}   # id(page) -> {url: ws}
_PAGE_CHANNEL = {}   # id(page) -> {url: channel_name}  ("Simms"/"MiniGame"/"MiniGame3"/portal)

# Frame recv gần nhất của TỪNG page (qua Playwright socket), để xác minh room id
# của từng account mà không cần so tên (window.__ws_capture không bắt được socket
# tạo trong Web Worker của game).
_PAGE_RECV = {}

# Worker đã hook WebSocket (id(worker)) — tránh hook lặp.
_WORKER_HOOKED = set()

# Page đã inject hook (id(page)) — tránh đăng ký listener lặp khi inject nhiều lần.
_PAGE_INJECTED = set()


def cleanup_page(page):
    """Dọn các container module của 1 page khi đóng session — tránh rò rỉ bộ nhớ."""
    pid = id(page)
    for d in (_PAGE_WS, _PAGE_SOCKETS, _PAGE_CHANNEL, _PAGE_RECV):
        d.pop(pid, None)
    _PAGE_INJECTED.discard(pid)


def _pick_channel_ws(page, channel):
    """Chọn socket theo channel ("Simms"/"MiniGame"/"MiniGame3") đã nhận diện.

    Key theo id(ws) (không theo URL) vì nhiều socket có thể cùng URL khác channel.
    """
    pid = id(page)
    socks = _PAGE_SOCKETS.get(pid, {})
    channels = _PAGE_CHANNEL.get(pid, {})
    for wid, ch in channels.items():
        if ch == channel and wid in socks:
            return socks[wid]
    return None


_INJECT_JS = r"""
(() => {
  const G = globalThis;
  if (G.__ws_hooked) return;
  G.__ws_hooked = true;
  G.__ws_capture = [];
  G.__ws_map = {};       // url -> socket (bắt qua constructor patch)
  G.__ws_instances = []; // mọi socket (bắt qua prototype send)

  const push = (dir, data) => {
    try {
      let text = "";
      if (typeof data === "string") text = data;
      else if (data instanceof Blob) text = "[Blob " + data.size + "b]";
      else if (data instanceof ArrayBuffer) text = new TextDecoder().decode(data);
      else if (data && data.data !== undefined) text = typeof data.data === "string" ? data.data : "[binary]";
      else text = "[?]";
      G.__ws_capture.push({ ts: Date.now(), dir, text: String(text).slice(0, 8000) });
      if (G.__ws_capture.length > 3000) G.__ws_capture.splice(0, 1500);
    } catch (e) {}
  };

  const register = (ws) => {
    try {
      if (G.__ws_instances.indexOf(ws) === -1) {
        G.__ws_instances.push(ws);
        if (G.__ws_instances.length > 30) G.__ws_instances.shift();
      }
      const url = (ws.url || "");
      if (url) G.__ws_map[url] = ws;
    } catch (e) {}
  };

  // 1) Patch PROTOTYPE.send — bắt cả socket ĐANG TỒN TẠI (kể cả tạo trước hook)
  const origSend = WebSocket.prototype.send;
  WebSocket.prototype.send = function (...args) {
    register(this);
    push("send", args[0]);
    return origSend.apply(this, args);
  };

  // 2) Patch CONSTRUCTOR — bắt socket MỚI (game reconnect sau offline->online)
  const OrigWS = G.WebSocket;
  G.WebSocket = function (...args) {
    const ws = new OrigWS(...args);
    register(ws);
    return ws;
  };
  G.WebSocket.prototype = OrigWS.prototype;
  G.WebSocket.CONNECTING = OrigWS.CONNECTING;
  G.WebSocket.OPEN = OrigWS.OPEN;
  G.WebSocket.CLOSING = OrigWS.CLOSING;
  G.WebSocket.CLOSED = OrigWS.CLOSED;

  const score = (s) => {
    const u = (s.url || "");
    return (/carkgwaiz/.test(u) ? 3 : 0) + (/mynisketgw/.test(u) ? 2 : 0) + (/Simms/.test(u) ? 1 : 0);
  };

  G.__ws_send_hint = (hint, text) => {
    try {
      // ưu tiên theo score (game socket)
      const arr = G.__ws_instances.slice().sort((a, b) => score(b) - score(a));
      for (const s of arr) {
        if (!s || s.readyState !== 1) continue;
        if (hint && (s.url || "").indexOf(hint) === -1) continue;
        try { s.send(text); G.__ws_capture.push({ ts: Date.now(), dir: "inject", text: String(text) }); return true; } catch (e) {}
      }
    } catch (e) {}
    return false;
  };
  G.__ws_send = (text) => G.__ws_send_hint("", text);
  G.__ws_send_channel = (channel, text) => G.__ws_send_hint(
    channel === "Simms" ? "carkgwaiz" : "mynisketgw", text
  );
})();
"""


# Mở 1 WS phụ từ page (KHÔNG reload, không động vào session game đang login)
# để gửi lệnh join bàn. Dùng accessToken + URL WS thực tế từ localStorage của account.
_SIDE_SOCK_JS = r"""
(async ([url, accessToken, cmd, connectFrame]) => {
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
        # Auth token của game có prefix "1-" (agentId): "1-<token>"
        if isinstance(access_token, str) and not access_token.startswith("1-"):
            connect_frame[4]["accessToken"] = "1-" + access_token
        for url in urls:
            try:
                # page.evaluate chỉ nhận 1 arg -> truyền 1 array rồi destructure trong JS
                out = await page.evaluate(_SIDE_SOCK_JS, [url, access_token, cmd, connect_frame])
            except Exception as e:
                log.warning("side_command fail url=%s: %s", url, e)
                continue
            out = out or []
            log.info("side_command url=%s -> %d msgs: %s", url[:60], len(out), [str(m)[:120] for m in out][:5])
            if any(not str(m).startswith(("ERR", "WS_ERR", "SEND_ERR")) for m in out):
                return out
        return []

    async def inject(self, page):
        """Patch WebSocket.prototype vào MỌI frame + worker (game tạo socket
        trong iframe about:blank / worker, không chỉ main frame)."""
        if not page:
            return False
        injected = 0
        for f in [page] + page.frames:
            try:
                await f.evaluate(_INJECT_JS)
                injected += 1
            except Exception as e:
                log.warning("inject frame fail %s: %s", (f.url or "")[:60], str(e)[:80])
        for w in list(page.workers or []):
            try:
                await w.evaluate(_INJECT_JS)
                injected += 1
            except Exception as e:
                log.warning("inject worker fail: %s", str(e)[:80])
        log.info("inject ws hook: %d context(s)", injected)
        return injected > 0

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

    async def inject_workers(self, page):
        """Hook WebSocket trong mọi Web Worker của page (game tạo socket trong worker).

        `_INJECT_JS` dùng `globalThis` nên chạy được cả trong worker. Sau khi hook,
        worker.__ws_map bắt được socket mới (khi game reconnect), gửi lệnh qua
        `worker.evaluate` sẽ dùng đúng socket game.
        """
        if not page:
            return False

        async def _hook(worker):
            try:
                if id(worker) in _WORKER_HOOKED:
                    return
                await worker.evaluate(_INJECT_JS)
                _WORKER_HOOKED.add(id(worker))
                log.info("worker ws hooked: %s", (worker.url or "")[:100])
            except Exception as e:
                log.warning("worker ws hook fail: %s", e)

        try:
            page.on("worker", lambda w: asyncio.create_task(_hook(w)))
        except Exception:
            pass
        for w in list(page.workers or []):
            await _hook(w)
        return True

    async def inject_playwright(self, page):
        """Dùng page.on('websocket') của Playwright — bắt mọi WS kể cả trong Web Worker.
        
        Ghi toàn bộ message vào ws_capture.jsonl + riêng cmd=300/305/308/202 vào room_debug.jsonl.
        Chỉ đăng ký listener 1 lần/page (tránh trùng, ghi đĩa N lần/frame).
        """
        if not page:
            return False
        if id(page) in _PAGE_INJECTED:
            return True
        _PAGE_INJECTED.add(id(page))
        self._room_file = self.save_dir / "room_debug.jsonl"
        try:
            async def _on_ws(ws):
                url = ws.url
                log.info("ws captured: %s", url)
                # key theo id(ws) — vì NHIỀU socket có thể cùng URL nhưng khác channel
                # (vd mynisketgw = cả MiniGame lẫn MiniGame3)
                _PAGE_SOCKETS.setdefault(id(page), {})[id(ws)] = ws

                def _on_send(data):
                    text = str(data)[:8000]
                    # Nhận diện channel từ auth frame [1,"<channel>","","",{...}]
                    try:
                        if text.startswith('[1,') or text.startswith('["1",'):
                            arr = json.loads(text)
                            if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], str):
                                ch = arr[1]
                                _PAGE_CHANNEL.setdefault(id(page), {})[id(ws)] = ch
                                if ch == "Simms":
                                    _PAGE_WS[id(page)] = ws  # socket game chính
                                log.info("ws channel: url=%s -> %s", url[:60], ch)
                    except Exception:
                        pass
                    self._save({"ts": int(time.time() * 1000), "dir": "send", "text": text, "url": url})
                    self._save_room({"ts": int(time.time() * 1000), "dir": "send", "text": text})

                def _on_recv(data):
                    text = str(data)[:8000]
                    self._save({"ts": int(time.time() * 1000), "dir": "recv", "text": text, "url": url})
                    self._save_room({"ts": int(time.time() * 1000), "dir": "recv", "text": text})
                    try:
                        buf = _PAGE_RECV.setdefault(id(page), [])
                        buf.append({"dir": "recv", "text": text})
                        if len(buf) > 2000:
                            del buf[:1000]
                    except Exception:
                        pass

                ws.on("framesent", _on_send)
                ws.on("framereceived", _on_recv)

            page.on("websocket", _on_ws)
            return True
        except Exception as e:
            log.warning("inject_playwright ws fail: %s", e)
            return False

    async def route_web_sockets(self, page):
        """(Đã bỏ) route_web_socket làm game treo khi intercept — không còn dùng."""
        return True

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

        Đường gửi HOẠT ĐỘNG THẬT: JS `__ws_send` (patch WebSocket.prototype — bắt
        socket đang tồn tại). CDP `sendToServer` chỉ là fallback cuối (không chắc
        gửi được vì socket quan sát của Playwright không hỗ trợ sendToServer).
        """
        if not page:
            return False
        # 1) JS __ws_send: main frame + iframe (prototype patch bắt socket đang có)
        for f in [page] + page.frames:
            try:
                ok = await f.evaluate(f"globalThis.__ws_send && globalThis.__ws_send({json.dumps(text)})")
                if ok:
                    self._save({"ts": int(time.time() * 1000), "dir": "inject", "text": str(text)[:8000], "url": f"frame:{f.url[:80]}"})
                    return True
            except Exception:
                pass
        # 2) JS __ws_send: Web Worker
        for w in list(page.workers or []):
            try:
                ok = await w.evaluate(f"globalThis.__ws_send && globalThis.__ws_send({json.dumps(text)})")
                if ok:
                    self._save({"ts": int(time.time() * 1000), "dir": "inject", "text": str(text)[:8000], "url": f"worker:{w.url[:80]}"})
                    return True
            except Exception:
                pass
        return False

    async def send_raw_channel(self, page, channel: str, text: str) -> bool:
        """Gửi lệnh raw vào 1 channel CỤ THỂ (Simms/MiniGame/MiniGame3) của page.

        Dùng JS `__ws_send_channel` (patch WebSocket.prototype) — bắt socket đang
        tồn tại, không cần intercept.
        """
        if not page:
            return False
        # 1) JS __ws_send_channel (prototype patch) — main frame + iframe
        for f in [page] + page.frames:
            try:
                ok = await f.evaluate(
                    f"globalThis.__ws_send_channel && globalThis.__ws_send_channel({json.dumps(channel)}, {json.dumps(text)})"
                )
                if ok:
                    self._save({"ts": int(time.time() * 1000), "dir": "inject", "text": str(text)[:8000], "url": f"channel:{channel}"})
                    return True
            except Exception:
                pass
        # 2) Fallback cuối: socket theo CHANNEL (id-based — MiniGame vs MiniGame3 cùng URL)
        ws = _pick_channel_ws(page, channel)
        if ws is not None:
            try:
                impl = getattr(ws, "_impl_obj", ws)
                impl._channel.send_may_fail(
                    "sendToServer", None, {"message": text, "isBase64": False}
                )
                self._save({"ts": int(time.time() * 1000), "dir": "inject", "text": str(text)[:8000], "url": f"channel:{channel}"})
                return True
            except Exception as e:
                log.warning("send_raw_channel %s impl fail (page=%s): %s", channel, id(page), e)
        log.warning("send_raw_channel: no socket for channel=%s page=%s", channel, id(page))
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

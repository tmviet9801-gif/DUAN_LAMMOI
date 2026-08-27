"""HitClubAdapter — adapter cho cổng game HitClub (canvas Cocos2d + Wasm).

Vì toàn bộ UI vẽ trong <canvas> (không có DOM selectors), adapter dùng:
1. Click theo TỌA ĐỘ (cấu hình `game.clicks`).
2. Bắt WebSocket (`game_sim/ws_sniffer.py`) để đọc winner/first_player.
3. Chế độ `capture` để ghi protocol khi user chơi thử → phân tích sau.

Cấu hình mẫu:
```json
{
  "game": {
    "adapter": "hitclub",
    "capture": false,
    "url": "https://play.hitclub.voting/?a=hitclub",
    "clicks": {
      "login_btn": [960, 520],
      "find_table_btn": [500, 800],
      "join_btn": [700, 800],
      "leave_btn": [1200, 700]
    },
    "ws_patterns": {
      "winner": ["winner", "thang", "ketqua", "result"],
      "first_player": ["firstplayer", "danhtruoc", "turn"]
    }
  }
}
```
"""
import asyncio
import json
import logging
import re

from core.time_utils import utcnow_iso
from game_sim.game_adapter import GameAdapter
from game_sim.token_store import TokenStore
from game_sim.ws_sniffer import WsSniffer
from models.config_model import DATA_DIR

log = logging.getLogger("adapter.hitclub")


def _find_cmd_payload(arr):
    """Trả (index, payload_dict) chứa 'cmd' trong 1 frame WS.

    RECV: [5, {payload}]  -> index 1
    SEND: [6, 'Simms', 'channelPlugin', {payload}] -> index 3
    """
    if not isinstance(arr, list):
        return None, None
    for i, el in enumerate(arr):
        if isinstance(el, dict) and "cmd" in el:
            return i, el
    return None, None


class HitClubAdapter(GameAdapter):
    def __init__(self, config: dict, account_lookup=None, page_pool=None):
        super().__init__(config)
        self.page_pool = page_pool
        self.account_lookup = account_lookup or {}
        self.game = config.get("game", {})
        self.url = self.game.get("url", "https://play.hitclub.voting/?a=hitclub")
        self.clicks = self.game.get("clicks", {})
        self.patterns = self.game.get("ws_patterns", {})
        self.capture = bool(self.game.get("capture", False))
        self.use_room_flow = bool(self.game.get("use_room_flow", True))
        self.sniffer = WsSniffer(DATA_DIR / "game_sim_debug")
        self.token_store = TokenStore(DATA_DIR / "game_sim_token.json")
        self._pages = {}
        self._last_msgs = []
        self._room_id = None
        self._join_template = None

    # ---- token helpers ----
    async def _read_token(self, page):
        """Đọc token login (localStorage['token']) từ page."""
        try:
            tok = await page.evaluate("localStorage.getItem('token')")
            return tok if tok else ""
        except Exception:
            return ""

    async def _restore_token(self, page, account_name):
        """Nếu page chưa có token hợp lệ, khôi phục token MỚI NHẤT từ token store.

        Game HITCLUB trả token MỚI mỗi lần login -> token cũ trong web_storage
        có thể đã expire. Ta ưu tiên token store (luôn là token mới nhất) để
        profile tự login mà không cần gõ lại tài khoản.
        """
        live = await self._read_token(page)
        if live and live.startswith("1-"):
            return live
        saved = self.token_store.get(account_name)
        if saved:
            try:
                await page.evaluate(f"localStorage.setItem('token', {json.dumps(saved)})")
                await page.evaluate(f"localStorage.setItem('user_token', {json.dumps(saved)})")
                log.info("restored fresh token for %s from token store", account_name)
            except Exception:
                pass
            return saved
        return live

    def _persist_token_to_account(self, account_name, token, username=None):
        """Ghi token mới vào account_lookup[].web_storage để _open_one restore sau này."""
        acc = self.account_lookup.get(account_name)
        if not acc:
            return
        ws = acc.setdefault("web_storage", {})
        loc = ws.setdefault("local", {})
        loc["token"] = token
        loc["user_token"] = token
        if username:
            loc["KEY_USER_NAME"] = username
        try:
            from models.config_model import load_accounts, save_accounts

            accounts = load_accounts()
            for a in accounts:
                if a.get("name") == account_name or a.get("id") == account_name:
                    a.setdefault("web_storage", {})["local"] = loc
                    save_accounts(accounts)
                    break
        except Exception as e:
            log.warning("persist token to account fail: %s", e)

    # ---- page helpers ----
    async def _page(self, account_name):
        if not account_name or not self.page_pool:
            return None
        if account_name not in self._pages:
            acc = self.account_lookup.get(account_name)
            if not acc:
                return None
            page = await self.page_pool.get_or_open(acc)
            if page:
                # Chỉ cắm hook (KHÔNG reload) để không làm đứt session login
                # của user — game này không giữ login qua reload.
                try:
                    await self.sniffer.inject_playwright(page)
                    await self.sniffer.inject_init(page)
                except Exception:
                    pass
                self._pages[account_name] = page
        return self._pages.get(account_name)

    async def _goto(self, page):
        if not page:
            return
        try:
            await page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(float(self.game.get("load_wait", 4)))
        except Exception as e:
            log.warning("hitclub goto fail: %s", e)

    async def _click(self, page, key, hold_ms=300):
        coord = self.clicks.get(key)
        if not coord or not page:
            log.warning("hitclub click %s: no coords configured", key)
            return False
        x, y = coord
        try:
            await page.mouse.click(x, y)
            await asyncio.sleep(hold_ms / 1000)
            return True
        except Exception as e:
            log.warning("hitclub click %s fail: %s", key, e)
            return False

    async def _type(self, page, key, text):
        coord = self.clicks.get(key)
        if not coord or not text:
            return False
        x, y = coord
        try:
            await page.mouse.click(x, y)
            await asyncio.sleep(0.3)
            for ch in text:
                await page.keyboard.type(ch, delay=80)
            await asyncio.sleep(0.2)
            return True
        except Exception:
            return False

    async def _screenshot(self, page, label):
        try:
            from game_sim.debug_capture import DebugCapture

            return await DebugCapture(DATA_DIR / "game_sim_debug").screenshot(page, label)
        except Exception:
            return ""

    # ---- WS role parsing ----
    def _parse_role(self, ctx, keyword):
        """Dò WS messages tìm keyword, đoán 'main'/'support' theo tên gần đó."""
        main = ctx.get("main_account")
        support = ctx.get("support_account")
        for it in reversed(self._last_msgs):
            text = it.get("text", "")
            if keyword and keyword not in text.lower():
                continue
            low = text.lower()
            if main and main.lower() in low:
                return "main"
            if support and support.lower() in low:
                return "support"
            # đoán theo "player_1"/"seat_0" gần keyword
            m = re.search(r"(?:player|seat|user)[_:=]?(\d+)", text, re.I)
            if m:
                idx = int(m.group(1))
                # quy ước: seat 0 = main
                return "main" if idx == 0 else "support"
        return "unknown"

    # ---- Room flow: bắt room id + join theo room id ----
    async def _capture_room(self, ctx):
        """Drain WS của MAIN, tách room id + template join từ protocol thực tế.

        Không phụ thuộc regex — dựa trên phân tích WS capture:
        - Room id: msg `cmd=308` RECV chứa `ri.rid` (room vừa join),
          hoặc msg `cmd=305` RECV mà `fu.u` == tên game của anchor.
        - Template: msg `cmd=308` SEND (join auto) + chèn `rid` vào.
        """
        anchor_name = ctx.get("main_account") or ""
        # Lookup tên game thực tế (username) từ account record
        acc = self.account_lookup.get(anchor_name) or {}
        game_user = (acc.get("username") or anchor_name).lower().strip()
        page = await self._page(anchor_name)
        await self.sniffer.drain(page)
        msgs = self.sniffer.recent(limit=1500)

        # 1) Tìm room id từ cmd=308 RECV (ri.rid)
        rid = None
        for it in reversed(msgs):
            if it.get("dir") != "recv":
                continue
            try:
                arr = json.loads(it.get("text", ""))
            except Exception:
                continue
            if not isinstance(arr, list) or len(arr) < 2:
                continue
            _, payload = _find_cmd_payload(arr)
            if isinstance(payload, dict) and payload.get("cmd") == 308 and isinstance(payload.get("ri"), dict):
                r = payload["ri"].get("rid")
                if isinstance(r, (int, float)) and r > 0:
                    rid = int(r)
                    break

        # 2) Fallback: cmd=305 RECV mà fu.u == game_user
        if not rid:
            for it in reversed(msgs):
                if it.get("dir") != "recv":
                    continue
                try:
                    arr = json.loads(it.get("text", ""))
                except Exception:
                    continue
                if not isinstance(arr, list) or len(arr) < 2:
                    continue
                _, payload = _find_cmd_payload(arr)
                if isinstance(payload, dict) and payload.get("cmd") == 305 and isinstance(payload.get("ri"), dict):
                    fu = payload.get("fu") or {}
                    u = str(fu.get("u") or "").lower().strip()
                    if u and (u == game_user or game_user in u or u in game_user):
                        r = payload["ri"].get("rid")
                        if isinstance(r, (int, float)) and r > 0:
                            rid = int(r)
                            break

        if not rid:
            log.info("chưa bắt được room id (không có cmd=308/305 recv phù hợp, game_user=%s)", game_user)
            return False

        # 3) Xây dựng template join: lấy msg cmd=308 SEND gần nhất, thêm rid
        template = None
        for it in reversed(msgs):
            if it.get("dir") not in ("send", "inject"):
                continue
            try:
                arr = json.loads(it.get("text", ""))
            except Exception:
                continue
            # SEND frame: payload ở arr[3]; RECV frame: arr[1]
            idx, p = _find_cmd_payload(arr)
            if idx is None or not isinstance(p, dict) or p.get("cmd") != 308:
                continue
            raw = dict(p)
            raw.pop("rid", None)
            raw["rid"] = rid
            new_arr = list(arr)
            new_arr[idx] = raw
            template = json.dumps(new_arr, ensure_ascii=False)
            break

        if not template:
            template = f'[6,"Simms","channelPlugin",{{"cmd":308,"aid":1,"gid":1,"b":100,"Mu":2,"iJ":true,"inc":false,"pwd":"1","rid":{rid}}}]'
        template = template.replace(str(rid), "{room_id}")

        self._room_id = rid
        self._join_template = template
        log.info("CAPTURED room_id=%s template=%s game_user=%s", self._room_id, template[:120], game_user)
        return True

    async def _join_room_by_id(self, page):
        """Cho member gửi message join với room id đã bắt được."""
        if not self._room_id or not self._join_template:
            return False
        msg = self._join_template.replace("{room_id}", str(self._room_id))
        try:
            ok = await self.sniffer.send_raw(page, msg)
            await asyncio.sleep(float(self.game.get("join_wait", 2)))
            log.info("sent join room_id=%s ok=%s", self._room_id, ok)
            return ok
        except Exception as e:
            log.warning("join room by id fail: %s", e)
            return False

    def _build_join_msg(self, rid, template=None):
        """Build message join cmd=308 với rid cụ thể.

        Ưu tiên: template truyền vào > template đã bắt (_join_template) >
        template mặc định. Template có placeholder {room_id} sẽ thay bằng rid;
        nếu template chứa rid cũ (số) cũng được thay thế.
        """
        rid = str(int(rid))
        tpl = template or self._join_template
        if tpl:
            msg = tpl.replace("{room_id}", rid)
            if self._room_id and str(self._room_id) != rid:
                msg = msg.replace(str(self._room_id), rid)
            return msg
        gid = int(self.game.get("gid", 1))
        return (
            f'[6,"Simms","channelPlugin",{{"cmd":308,"aid":1,"gid":{gid},'
            f'"b":100,"Mu":2,"iJ":true,"inc":false,"pwd":"1","rid":{rid}}}]'
        )

    async def join_by_id(self, account_name, rid, template=None):
        """Ép account join CHÍNH XÁC vào bàn rid (dùng template bắt được).

        Gửi qua game socket đã bắt (send_raw tự fallback Playwright + JS map).
        Trả dict {ok, rid, verified, sent} để endpoint trả về cho UI test.
        """
        page = await self._page(account_name)
        if not page:
            return {"ok": False, "rid": int(rid), "verified": False,
                    "error": "no_page", "sent": None}
        # không bắt buộc Playwright socket — send_raw sẽ thử JS map nếu cần
        msg = self._build_join_msg(rid, template)
        ok = await self.sniffer.send_raw(page, msg)
        await asyncio.sleep(float(self.game.get("join_wait", 2)))
        await self.sniffer.drain(page)
        verified = False
        msgs = self.sniffer.recent(limit=1500)
        for it in msgs:
            try:
                arr = json.loads(it.get("text", ""))
            except Exception:
                continue
            if not isinstance(arr, list):
                continue
            _, p = _find_cmd_payload(arr)
            if not isinstance(p, dict):
                continue
            if p.get("cmd") == 308 and isinstance(p.get("ri"), dict):
                if p["ri"].get("rid") == int(rid):
                    verified = True
                    break
            if p.get("cmd") == 202 and isinstance(p.get("ps"), list):
                verified = True
                break
        log.info("join_by_id %s -> rid=%s ok=%s verified=%s", account_name, rid, ok, verified)
        return {"ok": bool(ok), "rid": int(rid), "verified": verified, "sent": msg}

    async def _game_ws_info(self, page):
        """Đọc token + danh sách URL WS thực tế từ localStorage (KHÔNG reload)."""
        return await page.evaluate(
            """() => {
                const tok = localStorage.getItem('token') || localStorage.getItem('user_token') || '';
                let raw = localStorage.getItem('appConfigLocalStore') || '';
                let cfg = null;
                try { cfg = JSON.parse(raw); } catch(e) { try { cfg = JSON.parse(atob(raw)); } catch(e2) {} }
                const urls = [];
                if (cfg) {
                    (cfg.SOCKET_URL || []).forEach(u => urls.push(u));
                    ['IPMaster1','IPMaster3','IPMaster6','IPMaster7'].forEach(k => { if (cfg[k]) urls.push(cfg[k]); });
                }
                // ưu tiên m-f*.wsmt8g.cc/v3/ (đã xác nhận kết nối được)
                const pri = urls.filter(u => /m-f[0-9].*wsmt8g\\.cc\\/v3/.test(u));
                return { token: tok, urls: pri.concat(urls.filter(u => !pri.includes(u))) };
            }"""
        )

    async def join_by_id_side(self, account_name, rid, template=None):
        """Join bàn rid bằng 1 WS phụ MỚI, KHÔNG reload / KHÔNG động session game.

        Đọc token + URL WS thực tế từ localStorage của profile (đã login), mở WS
        riêng, gửi frame auth + cmd=308 join. Trả về {ok, rid, responses, verified}.
        """
        page = await self._page(account_name)
        if not page:
            return {"ok": False, "rid": int(rid), "responses": [], "error": "no_page"}
        info = await self._game_ws_info(page)
        token = (info or {}).get("token", "")
        urls = (info or {}).get("urls", []) or []
        if not token or not urls:
            return {"ok": False, "rid": int(rid), "responses": [],
                    "error": "no_token_or_socket", "token": bool(token), "urls": len(urls)}
        msg = self._build_join_msg(rid, template)
        responses = await self.sniffer.side_command(page, urls, token, msg)
        verified = False
        for r in responses:
            try:
                arr = json.loads(r)
            except Exception:
                continue
            if isinstance(arr, list):
                for el in arr:
                    if isinstance(el, dict) and el.get("cmd") in (308, 202, 305):
                        verified = True
                        break
            if verified:
                break
        log.info("join_by_id_side %s -> rid=%s responses=%d verified=%s", account_name, rid, len(responses), verified)
        return {"ok": bool(responses), "rid": int(rid), "responses": responses, "verified": verified, "sent": msg}




    async def list_rooms_side(self, account_name, gid=1):
        """Liệt kê bàn via WS phụ (KHÔNG reload). Trả về list {rid, rn, uC, b, gid}."""
        page = await self._page(account_name)
        if not page:
            return {"ok": False, "error": "no_page", "rooms": []}
        info = await self._game_ws_info(page)
        token = (info or {}).get("token", "")
        urls = (info or {}).get("urls", []) or []
        if not token or not urls:
            return {"ok": False, "error": "no_token_or_socket", "rooms": [],
                    "token": bool(token), "urls": len(urls)}
        cmd = '[6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":%d}]' % int(gid)
        responses = await self.sniffer.side_command(page, urls, token, cmd)
        rooms = {}
        for r in responses:
            try:
                arr = json.loads(r)
            except Exception:
                continue
            if not isinstance(arr, list):
                continue
            _, p = _find_cmd_payload(arr)
            if isinstance(p, dict) and p.get("cmd") == 300 and isinstance(p.get("rs"), list):
                for rm in p["rs"]:
                    if isinstance(rm, dict) and isinstance(rm.get("rid"), (int, float)):
                        rid = int(rm["rid"])
                        rooms[rid] = {
                            "rid": rid, "rn": rm.get("rn"), "uC": rm.get("uC"),
                            "b": rm.get("b"), "gid": rm.get("gid"), "Mu": rm.get("Mu"),
                        }
        return {"ok": bool(responses), "rooms": list(rooms.values()), "responses": responses}

    async def _verify_same_room(self, account_names):
        """Xác nhận tất cả account đã ở cùng 1 phòng.

        Drain WS của mỗi account, kiểm tra cmd=308 recv có cùng rid,
        hoặc cmd=305 recv có danh sách player chứa tên cả 2.
        """
        if not self._room_id:
            return False
        for name in account_names:
            page = await self._page(name)
            if not page:
                continue
            await self.sniffer.drain(page)
        msgs = self.sniffer.recent(limit=2000)
        found = {name: False for name in account_names}
        for it in msgs:
            try:
                arr = json.loads(it.get("text", ""))
            except Exception:
                continue
            if not isinstance(arr, list) or len(arr) < 2:
                continue
            _, payload = _find_cmd_payload(arr)
            if not isinstance(payload, dict):
                continue
            # cmd=308 recv: room info of current player
            if payload.get("cmd") == 308 and isinstance(payload.get("ri"), dict):
                r = payload["ri"].get("rid")
                if r == self._room_id:
                    # tìm tên user trong msg
                    for name in account_names:
                        if name.lower() in it.get("text", "").lower():
                            found[name] = True
            # cmd=202: trạng thái bàn, ps[] = danh sách người chơi (dn=display name)
            if payload.get("cmd") == 202 and isinstance(payload.get("ps"), list):
                for p in payload["ps"]:
                    dn = (p.get("dn") or "").lower()
                    for name in account_names:
                        if name.lower() in dn:
                            found[name] = True
            # cmd=100: broadcast từng người chơi vào bàn (dn=display name)
            if payload.get("cmd") == 100 and isinstance(payload.get("dn"), str):
                dn = payload["dn"].lower()
                for name in account_names:
                    if name.lower() in dn:
                        found[name] = True
            # cmd=305/308 ri.rid khớp + fu.u là người tạo bàn
            if payload.get("cmd") in (305, 308) and isinstance(payload.get("ri"), dict):
                if payload["ri"].get("rid") == self._room_id:
                    fu = payload.get("fu") or {}
                    fu_u = str(fu.get("u") or "").lower()
                    for name in account_names:
                        if name.lower() in fu_u or name.lower() in it.get("text", "").lower():
                            found[name] = True
        ok = all(found.values())
        log.info("verify same room %s: %s -> %s", self._room_id, found, ok)
        return ok

    # ---- hành động chính (có retry + screenshot) ----
    async def _click_retry(self, page, key, attempts=3, delay=1.0):
        """Click tọa độ với retry — True nếu có 1 lần thành công."""
        for i in range(attempts):
            if await self._click(page, key):
                return True
            await asyncio.sleep(delay)
        return False

    def _confirmed_rid(self, msgs):
        """Từ capture, trả rid nếu có msg cmd=308 recv (ri.rid) hoặc cmd=305 (ri.rid)."""
        for it in msgs:
            try:
                arr = json.loads(it.get("text", ""))
            except Exception:
                continue
            if not isinstance(arr, list) or len(arr) < 2:
                continue
            _, payload = _find_cmd_payload(arr)
            if isinstance(payload, dict):
                if payload.get("cmd") == 308 and isinstance(payload.get("ri"), dict):
                    r = payload["ri"].get("rid")
                    if isinstance(r, (int, float)) and r > 0:
                        return int(r)
                if payload.get("cmd") == 305 and isinstance(payload.get("ri"), dict):
                    r = payload["ri"].get("rid")
                    if isinstance(r, (int, float)) and r > 0:
                        return int(r)
        return None

    async def _wait_for_socket(self, page, timeout=20):
        """Chờ Playwright WS socket được capture (carkgwaiz channel)."""
        import time
        from game_sim.ws_sniffer import _PAGE_WS
        page_id = id(page)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                ws = _PAGE_WS.get(page_id)
                if ws is not None:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        log.info("ws socket wait timeout page=%s, _PAGE_WS keys=%s", page_id, list(_PAGE_WS.keys())[:8])
        return False

    async def _find_empty_room(self, page, max_tries=6, wait=2, gid=1):
        """Tìm 1 phòng (ưu tiên uC=0, fallback uC thấp nhất) qua WS cmd=300.

        Game HITCLUB: gửi [6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":1}]
        → recv cmd=300 chứa `rs:[{rid,uC,...}]`. Trả rid phù hợp nhất.
        """
        req = '[6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":%d}]' % gid
        # Chờ socket sẵn sàng trước khi gửi lệnh
        if not await self._wait_for_socket(page, timeout=20):
            log.info("ws socket chưa sẵn sàng cho page %s", id(page))
            return None
        for i in range(max_tries):
            try:
                await self.sniffer.send_raw(page, req)
            except Exception:
                pass
            await asyncio.sleep(wait)
            await self.sniffer.drain(page)
            msgs = self.sniffer.recent(limit=1500)
            best = None
            cmd300_count = 0
            for it in msgs:
                try:
                    arr = json.loads(it.get("text", ""))
                except Exception:
                    continue
                if not isinstance(arr, list) or len(arr) < 2:
                    continue
                _, payload = _find_cmd_payload(arr)
                if isinstance(payload, dict) and payload.get("cmd") == 300 and isinstance(payload.get("rs"), list):
                    cmd300_count += 1
                    for room in payload["rs"]:
                        if isinstance(room, dict):
                            uc = room.get("uC", 99)
                            rid = room.get("rid")
                            if not (isinstance(rid, (int, float)) and rid > 0):
                                continue
                            # ưu tiên phòng rỗng (uC=0); fallback uC thấp nhất
                            if uc == 0:
                                log.info("found empty room rid=%s (rn=%s) attempt=%s", rid, room.get("rn"), i + 1)
                                return int(rid)
                            if best is None or uc < best[0]:
                                best = (uc, int(rid), room.get("rn"))
            if best and best[0] <= 2:
                log.info("found low-occupancy room rid=%s (uC=%s, rn=%s) attempt=%s", best[1], best[0], best[2], i + 1)
                return best[1]
            log.info("cmd=300 no suitable room (cmd300=%s, best=%s) attempt %s/%s", cmd300_count, best, i + 1, max_tries)
        return None

    async def _discard_cards(self, page, member_name="x"):
        """Xả bài: click nút xả (retry) và/hoặc gửi ws discard_cmd, chụp ảnh sau.

        Trả True nếu có ít nhất 1 cách thành công (click được / gửi được message).
        """
        ok = False
        if self.clicks.get("discard_btn"):
            ok = await self._click_retry(page, "discard_btn", attempts=2, delay=0.8)
        cmd = self.patterns.get("discard_cmd")
        if cmd:
            try:
                ok = await self.sniffer.send_raw(page, cmd) or ok
            except Exception as e:
                log.warning("discard_cmd send fail: %s", e)
        await asyncio.sleep(float(self.game.get("discard_wait", 1.5)))
        await self.sniffer.drain(page)
        await self._screenshot(page, f"hitclub_discard_{member_name}")
        return ok

    # ---- GameAdapter interface ----
    async def join(self, ctx, account_name, auto_find_table=True):
        page = await self._page(account_name)
        if not page:
            return False
        if self.capture:
            # CAPTURE: dùng Playwright websocket route (bắt mọi WS, kể cả Worker),
            # rồi reload để game kết nối WS sau khi handler đã đăng ký.
            await self.sniffer.inject_playwright(page)
            await self.sniffer.inject_init(page)
            await self.sniffer.inject_http(page)
            await self._goto(page)
            await self.sniffer.drain(page)
            log.info("hitclub CAPTURE mode: playwright WS handler + init hook đã set")
            return True
        await self._goto(page)
        # Khôi phục token MỚI NHẤT nếu page chưa có token hợp lệ.
        # Game HITCLUB trả token MỚI mỗi lần login -> token cũ trong web_storage
        # có thể đã expire, gây "profile vẫn không login được".
        try:
            live = await self._restore_token(page, account_name)
        except Exception:
            live = ""
        # Kiểm tra đã login chưa (token hợp lệ)
        if live and live.startswith("1-"):
            # luôn cập nhật token store bằng token live (bắt kịp token mới nhất)
            self.token_store.save(account_name, live, extra={"username": (self.account_lookup.get(account_name) or {}).get("username")})
            self._persist_token_to_account(account_name, live)
            log.info("skip login for %s (token valid)", account_name)
            if auto_find_table:
                await self._click_retry(page, "create_room_btn", attempts=2) or await self._click_retry(page, "find_table_btn", attempts=3)
                await asyncio.sleep(float(self.game.get("room_wait", 3)))
                if self.use_room_flow:
                    await self._capture_room(ctx)
            return True
        acc = self.account_lookup.get(account_name) or {}
        uname = (acc.get("username") or acc.get("name") or "").strip()
        pwd = (acc.get("password") or "").strip()
        # MAIN: login + tạo/vào phòng + bắt room id
        # SUPPORT: cũng cần login riêng (profile khác) trước khi join chung phòng
        await self._type(page, "username_input", uname)
        await self._type(page, "password_input", pwd)
        await self._click(page, "login_btn")
        await asyncio.sleep(float(self.game.get("login_wait", 1.5)))
        # ---- capture token MỚI ngay sau login (tránh lưu token cũ/hết hạn) ----
        new_tok = await self._read_token(page)
        if new_tok and new_tok.startswith("1-"):
            self.token_store.save(account_name, new_tok, extra={"username": uname})
            self._persist_token_to_account(account_name, new_tok, username=uname)
            log.info("captured NEW token for %s after login", account_name)
        else:
            log.warning("%s login: không đọc được token mới từ localStorage", account_name)
        main = ctx.get("main_account")
        if account_name == main:
            if auto_find_table:
                await self._click_retry(page, "create_room_btn", attempts=2) or await self._click_retry(page, "find_table_btn", attempts=3)
                await asyncio.sleep(float(self.game.get("room_wait", 3)))
                if self.use_room_flow:
                    await self._capture_room(ctx)
            return True
        # SUPPORT: join đúng phòng MAIN đã tạo (theo room id bắt được)
        if self.use_room_flow and self._join_template and self._room_id:
            return await self._join_room_by_id(page)
        if auto_find_table:
            await self._click(page, "join_btn")
        return True

    async def wait_table(self, ctx):
        # Canvas: đợi 1 khoảng thời gian cấu hình (không có selector)
        await asyncio.sleep(float(self.game.get("wait_table", 5)))
        return True

    async def bootstrap(self, ctx):
        return True

    async def play_round(self, ctx):
        page = await self._page(ctx.get("main_account"))
        await self.sniffer.drain(page)
        # đợi ván kết thúc
        await asyncio.sleep(float(self.game.get("round_wait", 15)))
        await self.sniffer.drain(page)
        self._last_msgs = self.sniffer.recent(limit=500)

        if self.capture:
            await self._screenshot(page, "hitclub_capture")
            return {"winner": "unknown", "first_player": "unknown", "capture": True}

        winner = self._parse_role(ctx, self.patterns.get("winner", ["winner"]))
        first = self._parse_role(ctx, self.patterns.get("first_player", ["firstplayer", "turn"]))
        if winner == "unknown" or first == "unknown":
            await self._screenshot(page, "hitclub_state")
        return {"winner": winner, "first_player": first}

    async def leave(self, ctx, account_name):
        page = await self._page(account_name)
        await self.sniffer.drain(page)
        return await self._click(page, "leave_btn") if page else True

    async def wait_next_player(self, ctx, account_name):
        page = await self._page(account_name)
        if not page:
            return False
        await self._click(page, "join_btn")
        await asyncio.sleep(float(self.game.get("wait_table", 5)))
        return True

    async def reset_table(self, ctx):
        return True

    async def recover(self, ctx):
        return True

    def capture_file(self):
        return str(self.sniffer.capture_file)

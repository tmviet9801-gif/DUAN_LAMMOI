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
import logging
import re

from core.time_utils import utcnow_iso
from game_sim.game_adapter import GameAdapter
from game_sim.ws_sniffer import WsSniffer
from models.config_model import DATA_DIR

log = logging.getLogger("adapter.hitclub")


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
        self._pages = {}
        self._last_msgs = []
        self._room_id = None
        self._join_template = None

    # ---- page helpers ----
    async def _page(self, account_name):
        if not account_name or not self.page_pool:
            return None
        if account_name not in self._pages:
            acc = self.account_lookup.get(account_name)
            page = await self.page_pool.get_or_open(acc)
            if page:
                await self.sniffer.inject(page)
            self._pages[account_name] = page
        return self._pages[account_name]

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
        """Drain WS của MAIN, tách room id + template join (message SEND chứa room id)."""
        page = await self._page(ctx.get("main_account"))
        await self.sniffer.drain(page)
        msgs = self.sniffer.recent(limit=1500)
        regexes = self.patterns.get("room_id", [])
        room_ids = self.sniffer.find_room_ids(msgs, regexes)
        if not room_ids:
            log.info("chưa bắt được room id (kiểm tra ws_patterns.room_id regex)")
            return False
        self._room_id = room_ids[0]
        self._join_template = self.sniffer.build_join_template(msgs, regexes)
        log.info("CAPTURED room_id=%s template=%s", self._room_id, self._join_template)
        return True

    async def _join_room_by_id(self, page):
        """Cho A1 (support) gửi message join với room id đã bắt được."""
        if not self._room_id or not self._join_template:
            return False
        template = self._join_template.replace("{room_id}", str(self._room_id))
        try:
            ok = await self.sniffer.send_raw(page, template)
            await asyncio.sleep(float(self.game.get("join_wait", 2)))
            log.info("sent join room_id=%s ok=%s", self._room_id, ok)
            return ok
        except Exception as e:
            log.warning("join room by id fail: %s", e)
            return False

    # ---- GameAdapter interface ----
    async def join(self, ctx, account_name):
        page = await self._page(account_name)
        if not page:
            return False
        await self._goto(page)
        if self.capture:
            log.info("hitclub CAPTURE mode: không auto-play, đợi user thao tác")
            return True
        main = ctx.get("main_account")
        if account_name == main:
            # MAIN: login + tạo/vào phòng + bắt room id
            await self._type(page, "username_input", (self.account_lookup.get(account_name) or {}).get("name", ""))
            await self._type(page, "password_input", (self.account_lookup.get(account_name) or {}).get("password", ""))
            await self._click(page, "login_btn")
            await self._click(page, "create_room_btn") or await self._click(page, "find_table_btn")
            await asyncio.sleep(float(self.game.get("room_wait", 3)))
            if self.use_room_flow:
                await self._capture_room(ctx)
            return True
        # SUPPORT: join đúng phòng MAIN đã tạo (theo room id bắt được)
        if self.use_room_flow and self._join_template and self._room_id:
            return await self._join_room_by_id(page)
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

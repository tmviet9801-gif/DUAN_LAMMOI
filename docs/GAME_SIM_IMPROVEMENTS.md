# Đề xuất cải tiến — Game Room Simulator cho bài toán game thực tế

## 1. Vấn đề hiện tại

- **Mock adapter** chạy được nhưng không tương tác với game thật.
- **Selector adapter** là scaffold, chưa đủ để xử lý flow real (login, tìm bàn, chờ đối thủ, phát hiện kết thúc ván...).
- **BrowserManager** mở session riêng biệt, không có cơ chế chia sẻ Page object với adapter.
- Chưa có **human-like behavior** (tránh anti-bot).
- Chưa có **screenshot / debug** khi lỗi.
- Chưa có **plugin architecture** cho game cụ thể (tiến lên, poker, baccarat...).

## 2. Kiến trúc bổ sung

```
game_sim/
  adapters/                    ← Plugin adapter cho từng game
    __init__.py
    base.py                    ← GameAdapterBase (interface mở rộng)
    mock.py                    ← Mock hiện tại
    tienlen.py                 ← Adapter cho Tiến Lên Miền Nam
    poker.py                   ← Adapter cho Poker
    baccarat.py                ← Adapter cho Baccarat
    configurable.py            ← Adapter cấu hình bằng JSON (selector-driven)
    human.py                   ← Human-like behavior wrapper (decorator/bridge)
  page_pool.py                 ← Quản lý Page object từ BrowserManager
  screenshot.py                ← Chụp ảnh màn hình khi lỗi
  debug.py                     ← Ghi lại DOM, network, console log
  recovery.py                  ← Recovery strategy nâng cao
  dashboard/                   ← Dashboard realtime (WebSocket push)
```

## 3. Cải tiến chi tiết

### 3.1. Page Pool — chia sẻ Page với adapter

Hiện tại `BrowserManager.open_sessions()` mở browser và giữ `TabSession.page`. Adapter cần truy cập Page để điều khiển.

```python
# services/page_pool.py (mới)
class PagePool:
    def __init__(self, manager: BrowserManager):
        self.manager = manager

    async def open_page(self, account: dict) -> Page:
        """Mở session cho account, trả về Playwright Page."""
        ids = await self.manager.open_sessions(accounts=[account])
        if ids:
            session = self.manager.sessions.get(ids[0])
            if session:
                return session.page
        return None

    async def navigate(self, page: Page, url: str, wait_until="networkidle"):
        await page.goto(url, wait_until=wait_until)

    async def close_page(self, account_id: str):
        await self.manager.close_all(account_ids=[account_id])
```

### 3.2. GameAdapterBase mở rộng

```python
class GameAdapterBase:
    async def login(self, page: Page, account: dict) -> bool
    async def find_table(self, page: Page, table_id: str = None) -> bool
    async def join_table(self, page: Page) -> bool
    async def wait_table_ready(self, page: Page, players: int = 2) -> bool
    async def play_round(self, page: Page) -> dict  # {winner, first_player, screenshots}
    async def leave_table(self, page: Page) -> bool
    async def get_winner(self, page: Page) -> str   # "main" | "support"
    async def get_first_player(self, page: Page) -> str
    async def screenshot(self, page: Page, path: str) -> str
    async def recover(self, page: Page) -> bool
```

### 3.3. Selector-driven adapter (cấu hình JSON)

```json
{
  "game": {
    "adapter": "configurable",
    "selectors": {
      "login_btn": "#btn-login",
      "username_input": "#username",
      "password_input": "#password",
      "find_table_btn": ".btn-find",
      "join_btn": ".btn-join",
      "ready_indicator": ".table-ready",
      "player_list": ".player-list .player-name",
      "winner_text": ".result .winner",
      "first_player_indicator": ".current-turn .name",
      "leave_btn": "#btn-leave"
    },
    "urls": {
      "login": "https://game.example.com/login",
      "lobby": "https://game.example.com/lobby",
      "table": "https://game.example.com/table/{table_id}"
    },
    "wait": {
      "login": 5,
      "find_table": 15,
      "ready": 10,
      "round_end": 60
    }
  }
}
```

### 3.4. Human-like behavior wrapper

```python
class HumanBehavior:
    @staticmethod
    async def random_delay(min_ms=200, max_ms=800):
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)

    @staticmethod
    async def human_type(page, selector, text):
        await page.click(selector)
        for char in text:
            await page.keyboard.type(char, delay=random.randint(50, 150))

    @staticmethod
    async def human_click(page, selector):
        box = await page.locator(selector).bounding_box()
        if box:
            x = box["x"] + random.uniform(2, box["width"] - 2)
            y = box["y"] + random.uniform(2, box["height"] - 2)
            await page.mouse.move(x, y, steps=random.randint(5, 12))
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await page.mouse.click(x, y)

    @staticmethod
    async def random_mouse_movement(page):
        """Di chuyển chuột ngẫu nhiên trong khoảng thời gian rảnh."""
        for _ in range(random.randint(1, 3)):
            x = random.randint(100, 1200)
            y = random.randint(100, 800)
            await page.mouse.move(x, y, steps=random.randint(8, 20))
            await asyncio.sleep(random.uniform(0.1, 0.3))
```

### 3.5. Screenshot + Debug

```python
class DebugCapture:
    def __init__(self, save_dir):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

    async def capture(self, page, label):
        ts = utcnow_iso().replace(":", "-")
        path = self.save_dir / f"{label}_{ts}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def dump_html(self, page, label):
        ts = utcnow_iso().replace(":", "-")
        path = self.save_dir / f"{label}_{ts}.html"
        html = await page.content()
        path.write_text(html, encoding="utf-8")
        return str(path)
```

### 3.6. Plugin adapter cho game cụ thể

Ví dụ adapter Tiến Lên Miền Nam:

```python
# game_sim/adapters/tienlen.py
class TienLenAdapter(GameAdapterBase):
    """Adapter cho game Tiến Lên Miền Nam (các cổng game bài Việt Nam)."""

    WINNER_SELECTORS = [".winner-name", ".result .player-win", ".table .winner"]
    FIRST_PLAYER_SELECTORS = [".current-turn .name", ".player-turn .active"]

    async def join_table(self, page):
        await page.goto(self.cfg["urls"]["lobby"])
        await page.click(self.cfg["selectors"]["find_table_btn"])
        await page.wait_for_selector(self.cfg["selectors"]["ready_indicator"], timeout=15000)
        return True

    async def get_winner(self, page):
        for sel in self.WINNER_SELECTORS:
            try:
                el = await page.wait_for_selector(sel, timeout=5000)
                if el: return await el.text_content()
            except: pass
        return "unknown"

    async def get_first_player(self, page):
        for sel in self.FIRST_PLAYER_SELECTORS:
            try:
                el = await page.wait_for_selector(sel, timeout=3000)
                if el: return await el.text_content()
            except: pass
        return "unknown"
```

### 3.7. Realtime Dashboard (WebSocket push)

Thay vì poll `/api/gamesim/status` mỗi 1.2s, state machine gửi event qua WebSocket (EventHub đã có sẵn). Frontend gamesim.js lắng nghe WS events để cập nhật dashboard realtime:

```python
# Trong manager.py, khi state machine chuyển trạng thái:
event = {
    "type": "game_sim_state",
    "run_id": run_id,
    "group": group_name,
    "state": machine.current,
    "round": ctx.get("round_no", 0),
    "metrics": metrics.to_dict(),
}
# Gửi qua EventHub (app.state.hub) để frontend nhận realtime
```

### 3.8. Recovery strategy nâng cao

```python
class RecoveryStrategy:
    """Chiến lược recovery khi disconnect/error."""

    STRATEGIES = {
        "reconnect_retry": {"max": 3, "delay": 2, "backoff": 1.5},
        "reopen_browser": {"max": 2, "delay": 5},
        "restart_scenario": {"max": 1, "delay": 10},
    }

    async def execute(self, context, error_type):
        strategy = self.STRATEGIES.get(error_type, self.STRATEGIES["reconnect_retry"])
        for attempt in range(strategy["max"]):
            ok = await context["adapter"].recover(context)
            if ok: return True
            delay = strategy["delay"] * (strategy.get("backoff", 1) ** attempt)
            await asyncio.sleep(delay)
        return False
```

### 3.9. Multi-table song song

Mở rộng cấu hình để chạy nhiều bàn cùng lúc:

```json
{
  "rooms": [
    {
      "table_url": "https://game.example.com/table/room1",
      "groups": ["A", "B"]
    },
    {
      "table_url": "https://game.example.com/table/room2",
      "groups": ["C", "D"]
    }
  ]
}
```

Mỗi room có 1 state machine riêng, chạy song song.

### 3.10. Tích hợp với BrowserManager hiện tại

```python
# services/page_pool.py
class PagePool:
    def __init__(self, browser_manager: BrowserManager):
        self.manager = browser_manager

    async def get_or_open(self, account: dict) -> Page:
        # Tìm session đang mở cho account này
        for sid, s in self.manager.sessions.items():
            if s.account and s.account.get("id") == account.get("id"):
                return s.page
        # Mở mới
        ids = await self.manager.open_sessions(accounts=[account])
        if ids:
            s = self.manager.sessions.get(ids[0])
            return s.page if s else None
        return None

    async def close(self, account_id: str):
        await self.manager.close_all(account_ids=[account_id])
```

## 4. Lộ trình triển khai

| Phase | Nội dung | Phụ thuộc |
|---|---|---|
| **1** | PagePool + GameAdapterBase mở rộng + HumanBehavior | — |
| **2** | Adapter configurable (selector-driven) | Phase 1 |
| **3** | Screenshot/Debug + Recovery nâng cao | Phase 1 |
| **4** | Plugin adapter cho game cụ thể (Tiến Lên, Poker...) | Phase 2 |
| **5** | Realtime dashboard (WS push) | Phase 0 (EventHub có sẵn) |
| **6** | Multi-table support | Phase 2 |
| **7** | Test scenario tự động với game thật (end-to-end) | Phase 2-4 |

## 5. Test với game thật — hướng dẫn

1. Mở tab **Nhóm** → chọn main + support từ profile có sẵn → Lưu.
2. Mở tab **Cấu hình** → cấu hình proxy cho từng profile (nếu cần IP riêng).
3. Mở tab **Game Test** → chọn scenario → chọn adapter `selector` → cấu hình selectors (qua API hoặc code).
4. Ấn **Start** → hệ thống mở browser cho từng profile → login → join bàn → chạy ván test → verify winner/first player.
5. Nếu lỗi: screenshot tự động lưu trong `%APPDATA%\AutoTool\data\game_sim_debug\`.

## 6. Kết luận

Hệ thống hiện tại đã có nền tảng vững chắc: state machine, account pool, metrics, storage, group config. Để vận hành với game thật, cần bổ sung **PagePool** (chia sẻ Page), **HumanBehavior** (tránh anti-bot), **DebugCapture** (screenshot khi lỗi), và viết adapter cụ thể cho từng nền tảng game. Kiến trúc plugin cho phép mở rộng dễ dàng mà không ảnh hưởng đến core.
## 10. HitClub — hướng dẫn tích hợp

**Quan trọng:** `https://play.hitclub.voting/?a=hitclub` là game HTML5 dùng **Cocos2d + WebAssembly** — toàn bộ UI vẽ trong `<canvas>`, **không có DOM selectors**. Vì vậy:
- Không dùng được `adapter: configurable` (selector-driven).
- Dùng **`adapter: "hitclub"`** — click theo tọa độ + bắt WebSocket.

### Bước 1: Capture protocol (bắt buộc trước khi auto-play)
HitClub giao tiếp server qua WebSocket. Ghi lại protocol để biết message nào báo winner/first_player:
- POST /api/gamesim/capture {"account_name": "A1"} → mở trang + bật WS sniffer
- Chơi 1 ván thủ công trên browser vừa mở
- GET /api/gamesim/ws-capture?keyword=winner → đọc messages
- POST /api/gamesim/capture-stop → dừng
Capture lưu tại `%APPDATA%\AutoTool\data\game_sim_debug\ws_capture.jsonl`.

### Bước 2: Cấu hình tọa độ click
Xác định tọa độ (px) của nút login / tìm bàn / vào bàn / rời bàn từ screenshot, điền vào config `game.clicks`.

### Bước 3: Chạy auto-play
POST /api/gamesim/start với `game.adapter: "hitclub"` + clicks + ws_patterns. Nếu winner/first_player vẫn "unknown", gửi nội dung ws_capture.jsonl để phân tích.

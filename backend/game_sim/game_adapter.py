"""Game adapter — interface thống nhất mà state machine gọi.

State machine gọi các method với `account_name` (tên profile).
- MockGameAdapter: mô phỏng, không cần browser.
- ConfigurableAdapter: điều khiển game thật qua selectors + PagePool.
"""
import asyncio
import logging
import random

log = logging.getLogger("game_sim.adapter")


class GameAdapter:
    """Interface. account_name = tên profile (main/support)."""

    def __init__(self, config=None):
        self.config = config or {}

    async def join(self, ctx, account_name) -> bool: ...
    async def wait_table(self, ctx) -> bool: ...
    async def bootstrap(self, ctx) -> bool: ...
    async def play_round(self, ctx) -> dict: ...
    async def leave(self, ctx, account_name) -> bool: ...
    async def wait_next_player(self, ctx, account_name) -> bool: ...
    async def reset_table(self, ctx) -> bool: ...
    async def recover(self, ctx) -> bool: ...


class MockGameAdapter(GameAdapter):
    def __init__(self, config: dict):
        super().__init__(config)
        game = config.get("game", {})
        self.force = game.get("force", "auto")  # main_wins / main_loses / auto
        self.join_fail_rate = float(game.get("join_fail_rate", 0.05))
        self.delay = float(game.get("mock_delay", 0.05))
        self._round_seed = 0

    async def _sleep(self):
        await asyncio.sleep(self.delay)

    async def join(self, ctx, account_name):
        await self._sleep()
        return random.random() >= self.join_fail_rate

    async def wait_table(self, ctx):
        await self._sleep()
        return True

    async def bootstrap(self, ctx):
        await self._sleep()
        return True

    async def play_round(self, ctx):
        await self._sleep()
        self._round_seed += 1
        if self.force == "main_wins":
            winner = "main"
        elif self.force == "main_loses":
            winner = "support"
        else:
            winner = random.choice(["main", "support"])
        # Quy luật game: người thắng ván trước đi trước ván sau.
        expected = ctx.get("prev_winner")
        first_player = expected if expected else random.choice(["main", "support"])
        return {"winner": winner, "first_player": first_player, "round": self._round_seed}

    async def leave(self, ctx, account_name):
        await self._sleep()
        return True

    async def wait_next_player(self, ctx, account_name):
        await self._sleep()
        return True

    async def reset_table(self, ctx):
        await self._sleep()
        return True

    async def recover(self, ctx):
        await self._sleep()
        return True


class ConfigurableAdapter(GameAdapter):
    """Điều khiển game thật qua selectors JSON + PagePool.

    `account_lookup`: {name -> account dict} để mở session qua PagePool.
    """

    def __init__(self, config: dict, account_lookup=None, page_pool=None):
        super().__init__(config)
        self.page_pool = page_pool
        self.account_lookup = account_lookup or {}
        self.selectors = config.get("game", {}).get("selectors", {})
        self.urls = config.get("game", {}).get("urls", {})
        self.wait_settings = config.get("game", {}).get("wait", {})
        self._pages = {}

    # ---- helpers ----
    async def _page(self, account_name):
        if not account_name or not self.page_pool:
            return None
        if account_name not in self._pages:
            acc = self.account_lookup.get(account_name)
            self._pages[account_name] = await self.page_pool.get_or_open(acc)
        return self._pages[account_name]

    async def _click(self, page, key, timeout=None):
        sel = self.selectors.get(key)
        if not sel or not page:
            return False
        timeout = timeout or int(self.wait_settings.get(key, 8))
        try:
            await page.wait_for_selector(sel, timeout=timeout * 1000)
            from game_sim.adapters.human import HumanBehavior

            return await HumanBehavior.human_click(page, sel)
        except Exception as e:
            log.warning("click %s (%s) fail: %s", key, sel, e)
            return False

    async def _wait_for(self, page, key, timeout=None):
        sel = self.selectors.get(key)
        if not sel:
            return True
        timeout = timeout or int(self.wait_settings.get(key, 10))
        try:
            await page.wait_for_selector(sel, timeout=timeout * 1000)
            return True
        except Exception:
            return False

    async def _text(self, page, key):
        sel = self.selectors.get(key)
        if not sel or not page:
            return ""
        try:
            el = await page.wait_for_selector(sel, timeout=5000)
            if el:
                return (await el.text_content()).strip()
        except Exception:
            pass
        return ""

    async def _goto(self, page, key):
        url = self.urls.get(key)
        if url and page:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(0.8)
                return True
            except Exception as e:
                log.warning("goto %s fail: %s", key, e)
        return False

    def _map_role(self, text, ctx, default="unknown"):
        main = ctx.get("main_account")
        support = ctx.get("support_account")
        t = (text or "").lower()
        if main and main.lower() in t:
            return "main"
        if support and support.lower() in t:
            return "support"
        return default

    # ---- GameAdapter interface ----
    async def join(self, ctx, account_name):
        page = await self._page(account_name)
        if not page:
            return False
        acc = self.account_lookup.get(account_name) or {}
        ok_login = await self._login(page, acc)
        await self._goto(page, "lobby")
        await self._click(page, "find_table_btn")
        await self._click(page, "join_btn")
        return ok_login

    async def _login(self, page, account):
        url = self.urls.get("login")
        if url:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
            except Exception as e:
                log.warning("login navigate fail: %s", e)
        u = self.selectors.get("username_input")
        p = self.selectors.get("password_input")
        if u:
            name = (account.get("name") or "").strip()
            if name:
                from game_sim.adapters.human import HumanBehavior

                await HumanBehavior.human_type(page, u, name)
        if p:
            pwd = (account.get("password") or "").strip()
            if pwd:
                from game_sim.adapters.human import HumanBehavior

                await HumanBehavior.human_type(page, p, pwd)
        await asyncio.sleep(0.3)
        return await self._click(page, "login_btn")

    async def wait_table(self, ctx):
        page = await self._page(ctx.get("main_account")) or await self._page(ctx.get("support_account"))
        return await self._wait_for(page, "ready_indicator", timeout=20)

    async def bootstrap(self, ctx):
        return True

    async def play_round(self, ctx):
        page = await self._page(ctx.get("main_account"))
        wait_s = float(self.wait_settings.get("round_end", 60))
        if page and not await self._wait_for(page, "winner_text", timeout=wait_s):
            await self._screenshot(page, "play_round_timeout")
            return {"winner": "unknown", "first_player": "unknown", "error": "timeout"}
        winner_txt = await self._text(page, "winner_text")
        first_txt = await self._text(page, "first_player_indicator")
        return {
            "winner": self._map_role(winner_txt, ctx),
            "first_player": self._map_role(first_txt, ctx),
        }

    async def leave(self, ctx, account_name):
        page = await self._page(account_name)
        if not page:
            return True
        return await self._click(page, "leave_btn")

    async def wait_next_player(self, ctx, account_name):
        page = await self._page(account_name)
        if not page:
            return False
        await self._click(page, "join_btn")
        return await self._wait_for(page, "ready_indicator", timeout=20)

    async def reset_table(self, ctx):
        return True

    async def recover(self, ctx):
        return True

    async def _screenshot(self, page, label):
        try:
            from game_sim.debug_capture import DebugCapture
            from models.config_model import DATA_DIR

            return await DebugCapture(DATA_DIR / "game_sim_debug").screenshot(page, label)
        except Exception:
            return ""


def create_adapter(config: dict, account_lookup=None, page_pool=None) -> GameAdapter:
    kind = config.get("game", {}).get("adapter", "mock")
    if kind in ("configurable", "selector"):
        return ConfigurableAdapter(config, account_lookup=account_lookup, page_pool=page_pool)
    if kind == "hitclub":
        from game_sim.adapters.hitclub import HitClubAdapter

        return HitClubAdapter(config, account_lookup=account_lookup, page_pool=page_pool)
    return MockGameAdapter(config)

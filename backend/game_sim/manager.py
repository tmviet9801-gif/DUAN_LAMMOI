"""GameSimManager — điều phối toàn hệ thống mô phỏng."""
import asyncio
import logging
import uuid

from core.time_utils import utcnow_iso
from models.config_model import DATA_DIR

from .account_pool import AccountPool
from .game_adapter import create_adapter
from .metrics import Metrics
from .scheduler import Scheduler
from .storage import Storage

log = logging.getLogger("game_sim.manager")


class GameSimManager:
    def __init__(self, storage: Storage | None = None, browser_manager=None):
        self.storage = storage or Storage(DATA_DIR / "game_sim.db")
        self.scheduler = Scheduler(self)
        self.browser_manager = browser_manager
        self.page_pool = None
        self.config = None
        self.run_id = None
        self.pool = None
        self.adapter = None
        self.metrics = {}
        self.metrics_final = {}
        self.machines = {}
        self.stop_event = None
        self._started_at = None
        self.running = False
        self._event_sink = None

    def set_event_sink(self, sink):
        """Gán callback push sự kiện realtime (qua EventHub → WebSocket)."""
        self._event_sink = sink

    # ---- emit_log ----
    def _emit(self, **kw):
        log.debug("[%s] %s --(%s)--> %s %s", kw.get("group_name"), kw.get("state_from"),
                  kw.get("event_id"), kw.get("state_to"), kw.get("message"))
        try:
            self.storage.add_event(
                kw.get("run_id"), kw.get("group_name"), kw.get("session_id"),
                kw.get("event_id"), kw.get("state_from"), kw.get("state_to"),
                kw.get("message", ""),
            )
        except Exception:
            pass
        if self._event_sink:
            try:
                self._event_sink({
                    "type": "game_sim_event",
                    "run_id": kw.get("run_id"),
                    "group": kw.get("group_name"),
                    "state_from": kw.get("state_from"),
                    "state_to": kw.get("state_to"),
                    "message": kw.get("message", ""),
                })
            except Exception:
                pass

    # ---- lifecycle ----
    async def start(self, config: dict):
        self.stop()
        self.config = config
        self.run_id = f"run_{uuid.uuid4().hex[:10]}"
        self._started_at = utcnow_iso()
        self.stop_event = asyncio.Event()

        groups = config.get("groups", {})
        if not groups:
            raise ValueError("Config thiếu 'groups'")

        self.pool = AccountPool(groups)
        if self.browser_manager:
            from services.page_pool import PagePool

            self.page_pool = PagePool(self.browser_manager)
        from models.config_model import load_accounts

        accounts = load_accounts()
        self.account_lookup = {a["name"]: a for a in accounts if a.get("name")}
        self.adapter = create_adapter(
            config, account_lookup=self.account_lookup, page_pool=self.page_pool
        )
        self.metrics = {g: Metrics() for g in groups}
        self.metrics_final = {}
        self.machines = {}
        self.running = True

        timing = config.get("timing", {})
        for g in groups:
            task = asyncio.create_task(
                self.scheduler.run_group(g, config, timing, self.stop_event, self._emit)
            )
            self.scheduler.tasks[g] = task
            task.add_done_callback(lambda _t, g=g: self._on_group_done(g))
        log.info("GameSim started: %s (%d groups, adapter=%s)", self.run_id, len(groups),
                 config.get("game", {}).get("adapter", "mock"))
        return {"run_id": self.run_id, "groups": list(groups)}

    def _on_group_done(self, group):
        tasks = self.scheduler.tasks
        if tasks and all(t.done() for t in tasks.values()):
            self.running = False

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        for t in self.scheduler.tasks.values():
            if not t.done():
                t.cancel()
        self.scheduler.tasks.clear()
        for g, m in self.metrics.items():
            if g not in self.metrics_final:
                try:
                    self.storage.finish_run(self.run_id, m.to_dict(), status="stopped")
                except Exception:
                    pass
        self.running = False
        self.config = None

    def recover_group(self, group: str):
        """Recovery thủ công: trigger recover từ ERROR."""
        m = self.machines.get(group)
        if m and m.current == "ERROR":
            asyncio.create_task(m.trigger("recover"))
            return True
        return False

    # ---- query ----
    def status(self) -> dict:
        states = {}
        for g, m in self.machines.items():
            states[g] = {
                "state": m.current,
                "session_id": m.context.get("session_id"),
                "main": m.context.get("main_account"),
                "support": m.context.get("support_account"),
                "round": m.context.get("round_no", 0),
                "retries": m.context.get("retries", 0),
            }
        return {
            "running": self.running,
            "run_id": self.run_id,
            "started_at": self._started_at,
            "adapter": (self.config or {}).get("game", {}).get("adapter", "mock"),
            "scenario": (self.config or {}).get("scenario", "winner_keeps_first_move"),
            "rounds": (self.config or {}).get("rounds", 0),
            "groups": states,
        }

    def metrics_view(self) -> dict:
        out = {}
        for g in (self.config or {}).get("groups", {}):
            m = self.metrics.get(g)
            out[g] = m.to_dict() if m else {}
        return out

    def recent_events(self, limit=30):
        return self.storage.recent_events(limit)

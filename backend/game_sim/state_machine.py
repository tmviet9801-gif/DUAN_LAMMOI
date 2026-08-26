"""Engine FSM generic.

Đặc điểm:
- Trigger event bằng hàng đợi nội bộ (tránh đệ quy khi on_enter phát event tiếp).
- Mỗi state có thể có timeout (an toàn lưới), retry tối đa.
- Log chi tiết mọi transition với event_id / session_id.
"""
import asyncio
import logging
import time
from typing import Callable, Optional

log = logging.getLogger("game_sim.fsm")


class Transition:
    """Một cạnh của state machine."""

    def __init__(
        self,
        target: str,
        condition: Optional[Callable[[dict], bool]] = None,
        timeout: Optional[float] = None,
        max_retries: int = 0,
        timeout_target: str = "RETRY",
        retry_exhausted_target: str = "ERROR",
    ):
        self.target = target
        self.condition = condition
        self.timeout = timeout
        self.max_retries = max_retries
        self.timeout_target = timeout_target
        self.retry_exhausted_target = retry_exhausted_target


class State:
    def __init__(self, name, on_enter=None, on_exit=None, transitions=None, timeout=None):
        self.name = name
        self.on_enter = on_enter  # async (ctx, machine)
        self.on_exit = on_exit
        self.transitions = transitions or {}  # event -> Transition
        self.timeout = timeout


class StateMachine:
    """FSM có event queue + timeout + retry + recovery.

    ctx: dict giữ trạng thái nghiệp vụ (group, session_id, retry_target...).
    """

    def __init__(self, name, states, initial="IDLE", emit_log=None):
        self.name = name
        self.states = {s.name: s for s in states}
        self.initial = initial
        self.current = initial
        self.context = {}
        self._queue = []
        self._processing = False
        self._timer_task = None
        self._retries = {}
        self.emit_log = emit_log or (lambda **kw: None)
        self.event_seq = 0

    # ---- helpers ----
    def set_context(self, **kw):
        self.context.update(kw)

    def _next_event_id(self) -> str:
        self.event_seq += 1
        return f"{self.name}-{self.event_seq}"

    def _log(self, state_from, state_to, message, **extra):
        self.emit_log(
            event_id=self._next_event_id(),
            state_from=state_from,
            state_to=state_to,
            message=message,
            **extra,
        )

    # ---- API ----
    async def start(self):
        self._log("-", self.current, "enter initial")
        await self._enter_state()

    async def trigger(self, event, **payload):
        """Phát event. Nếu đang xử lý event khác thì xếp hàng đợi."""
        self._queue.append((event, payload))
        if self._processing:
            return
        self._processing = True
        try:
            while self._queue:
                ev, payload = self._queue.pop(0)
                await self._handle(ev, payload)
        finally:
            self._processing = False

    # ---- nội bộ ----
    async def _handle(self, event, payload):
        state = self.states[self.current]
        tr = state.transitions.get(event)
        if not tr:
            # Nếu state có timeout và event là timeout
            if event == "timeout" and state.timeout:
                tr = Transition(
                    target=self._retry_or_error_target(state),
                    timeout_target="RETRY",
                )
                tr.target = self._retry_or_error_target(state)
            else:
                log.warning("[%s] no transition for '%s' in %s", self.name, event, self.current)
                self._log(self.current, self.current, f"IGNORE event '{event}' (no transition)")
                return
        if tr.condition and not tr.condition(payload):
            log.info("[%s] condition failed '%s' in %s", self.name, event, self.current)
            return

        # Reset retry khi đi bằng event bình thường (không phải timeout/retry)
        if event not in ("timeout", "retry"):
            self._retries[self.current] = 0

        target = tr.target
        if target == "__retry_target__":
            target = self.context.get("retry_target", "ERROR")

        # recovery/timeout → tăng retry
        if event in ("timeout",) or (isinstance(payload, dict) and payload.get("recover")):
            pass

        await self._go(target, event, payload)

    def _retry_or_error_target(self, state) -> str:
        retries = self._retries.get(self.current, 0)
        tr_any = next((t for t in state.transitions.values() if t.timeout), None)
        if tr_any and retries < tr_any.max_retries:
            return "RETRY"
        return "ERROR"

    async def _go(self, target, event, payload):
        state = self.states[self.current]
        if state.on_exit:
            await state.on_exit(self.context, self)
        self.context["last_event"] = event
        self._cancel_timer()
        self._log(self.current, target, f"event '{event}'", session_id=self.context.get("session_id"))
        self.current = target
        await self._enter_state()

    async def _enter_state(self):
        state = self.states[self.current]
        # schedule timeout watchdog
        if state.timeout:
            self._timer_task = asyncio.create_task(self._timeout_watch(state.timeout))
        if state.on_enter:
            await state.on_enter(self.context, self)

    async def _timeout_watch(self, timeout):
        await asyncio.sleep(timeout)
        if self._timer_task and self._timer_task.cancelled():
            return
        if self.current is None:
            return
        log.warning("[%s] TIMEOUT in state %s", self.name, self.current)
        self._log(self.current, "RETRY/ERROR", "TIMEOUT watchdog fired")
        await self.trigger("timeout")

    def _cancel_timer(self):
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    # ---- recovery ----
    def mark_reconnect(self, ok: bool):
        """Adapter báo kết nối lại sau disconnect."""
        self.context["reconnected"] = ok


def new_machine(name, states, initial="IDLE", emit_log=None) -> StateMachine:
    return StateMachine(name, states, initial, emit_log=emit_log)

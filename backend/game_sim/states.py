"""11 trạng thái vòng đời phòng game + transitions.

Các trạng thái: IDLE, JOINING, WAITING_FOR_TABLE, BOOTSTRAP_ROUND, PLAYING,
VERIFYING_RESULT, LEAVING, WAITING_NEXT_PLAYER, RESETTING, RETRY, ERROR
(+ FINISHED terminal nội bộ).

ctx mang: run_id, group_name, session_id, main_account, support_account,
scenario, rounds, timing, adapter, pool, metrics, storage, prev_winner...
"""
import asyncio
import logging
import uuid

from core.time_utils import utcnow_iso
from .state_machine import State, Transition

log = logging.getLogger("game_sim.states")


def _emit(machine, state_from, state_to, message, **extra):
    ctx = machine.context
    machine.emit_log(
        run_id=ctx.get("run_id"),
        group_name=ctx.get("group_name"),
        session_id=ctx.get("session_id"),
        state_from=state_from,
        state_to=state_to,
        message=message,
        **extra,
    )
    storage = ctx.get("storage")
    if storage:
        try:
            storage.add_event(
                ctx.get("run_id"), ctx.get("group_name"), ctx.get("session_id"),
                extra.get("event_id"), state_from, state_to, message,
            )
        except Exception:
            pass


def _set_retry_target(machine, target):
    machine.context["retry_target"] = target


# ---- on_enter handlers ----

async def _enter_idle(ctx, machine):
    ctx["session_id"] = f"ses_{uuid.uuid4().hex[:8]}"
    await machine.trigger("start")


async def _enter_joining(ctx, machine):
    cfg = ctx.get("config", {})
    pool = ctx.get("pool")
    adapter = ctx.get("adapter")
    timing = ctx.get("timing", {})
    ctx["retry_target"] = "JOINING"
    ctx["session_id"] = f"ses_{uuid.uuid4().hex[:8]}"
    main = ctx.get("main_account") or cfg.get("groups", {}).get(ctx["group_name"], {}).get("main")
    support = pool.next_support(ctx["group_name"], exclude=[main]) if pool else None
    if not main or not support:
        await machine.trigger("join_failed")
        return
    ctx["main_account"] = main
    ctx["support_account"] = support
    # Join cả 2 (song song)
    ok_m, ok_s = await asyncio.gather(
        adapter.join(ctx, main),
        adapter.join(ctx, support),
    )
    ctx["metrics"].record_join(ok_m and ok_s)
    if ok_m and ok_s:
        await machine.trigger("joined")
    else:
        await machine.trigger("join_failed")


async def _enter_waiting_table(ctx, machine):
    timing = ctx.get("timing", {})
    ctx["retry_target"] = "WAITING_FOR_TABLE"
    try:
        ok = await asyncio.wait_for(ctx["adapter"].wait_table(ctx), timeout=float(timing.get("table_wait", 15)))
    except asyncio.TimeoutError:
        ctx["metrics"].record_timeout()
        await machine.trigger("table_wait_timeout")
        return
    await machine.trigger("table_ready" if ok else "table_wait_timeout")


async def _enter_bootstrap(ctx, machine):
    ctx["retry_target"] = "BOOTSTRAP_ROUND"
    ok = await ctx["adapter"].bootstrap(ctx)
    await machine.trigger("round_ready" if ok else "bootstrap_failed")


async def _enter_playing(ctx, machine):
    ctx["retry_target"] = "PLAYING"
    ctx["retries"] = 0  # reset retry counter mỗi ván
    timing = ctx.get("timing", {})
    try:
        result = await asyncio.wait_for(ctx["adapter"].play_round(ctx), timeout=float(timing.get("play_timeout", 60)))
    except asyncio.TimeoutError:
        ctx["metrics"].record_timeout()
        await machine.trigger("play_failed")
        return
    if not isinstance(result, dict):
        await machine.trigger("play_failed")
        return
    ctx["round_result"] = result
    ctx["round_no"] = ctx.get("round_no", 0) + 1
    first = result.get("first_player")
    winner = result.get("winner")
    ctx["first_player"] = first
    ctx["last_winner"] = winner
    # Assert: expected first = winner ván trước
    expected = ctx.get("prev_winner")
    ok = (expected is None) or (first == expected)
    ctx["metrics"].record_first_move(expected, first, ok)
    storage = ctx.get("storage")
    if storage:
        try:
            storage.add_round(ctx.get("run_id"), ctx["group_name"], ctx["round_no"],
                              first, winner, expected, ok)
        except Exception:
            pass
    rounds_limit = ctx.get("rounds", 0)
    if rounds_limit and ctx["round_no"] >= rounds_limit:
        await machine.trigger("finished")
    else:
        await machine.trigger("round_end")


async def _enter_verifying(ctx, machine):
    ctx["retry_target"] = "VERIFYING_RESULT"
    winner = (ctx.get("round_result") or {}).get("winner")  # "main" | "support"
    ctx["prev_winner"] = winner
    if winner == "main":
        ctx["leaving_role"] = "support"
        await machine.trigger("main_won")
    else:
        ctx["leaving_role"] = "main"
        await machine.trigger("main_lost")


async def _enter_leaving(ctx, machine):
    ctx["retry_target"] = "LEAVING"
    role = ctx.get("leaving_role", "support")
    account = ctx.get("support_account") if role == "support" else ctx.get("main_account")
    ok = await ctx["adapter"].leave(ctx, account)
    pool = ctx.get("pool")
    if pool and account:
        pool.release(account, cooldown_s=float(ctx.get("timing", {}).get("cooldown", 5)))
    ctx["metrics"].end_cycle()
    ctx["metrics"].start_cycle()
    if role == "support":
        await machine.trigger("support_left" if ok else "leave_failed")
    else:
        await machine.trigger("main_left" if ok else "leave_failed")


async def _enter_waiting_next(ctx, machine):
    ctx["retry_target"] = "WAITING_NEXT_PLAYER"
    timing = ctx.get("timing", {})
    pool = ctx.get("pool")
    main = ctx.get("main_account")
    # Đã đủ số ván → kết thúc, không chờ support tiếp theo
    rounds_limit = ctx.get("rounds", 0)
    if rounds_limit and ctx.get("round_no", 0) >= rounds_limit:
        await machine.trigger("finished")
        return
    nxt = pool.next_support(ctx["group_name"], exclude=[main, ctx.get("support_account")]) if pool else None
    if not nxt:
        # Hết support trong pool → kết thúc THÀNH CÔNG (không quay vòng retry/lỗi)
        await machine.trigger("finished")
        return
    ctx["support_account"] = nxt
    try:
        ok = await asyncio.wait_for(
            ctx["adapter"].wait_next_player(ctx, nxt),
            timeout=float(timing.get("next_player_wait", 20)),
        )
    except asyncio.TimeoutError:
        ctx["metrics"].record_timeout()
        # Không chờ vô hạn → kết thúc luôn thay vì wait_player_timeout → RETRY loop
        await machine.trigger("finished")
        return
    await machine.trigger("player_joined" if ok else "finished")


async def _enter_resetting(ctx, machine):
    ctx["retry_target"] = "RESETTING"
    ok = await ctx["adapter"].reset_table(ctx)
    await machine.trigger("reset_done" if ok else "reset_failed")


async def _enter_retry(ctx, machine):
    ctx["retries"] = ctx.get("retries", 0) + 1
    retry_max = int(ctx.get("timing", {}).get("retry_max", 3))
    if ctx["retries"] > retry_max:
        _emit(machine, "RETRY", "ERROR", f"retry exhausted ({ctx['retries']})")
        await machine.trigger("retry_exhausted")
    else:
        _emit(machine, "RETRY", ctx.get("retry_target", "ERROR"), f"retry #{ctx['retries']}")
        await asyncio.sleep(0.3)
        await machine.trigger("retry_ok")


async def _enter_error(ctx, machine):
    _emit(machine, "ERROR", "ERROR", "ERROR state reached", is_error=True)


async def _enter_finished(ctx, machine):
    _emit(machine, "FINISHED", "FINISHED", "scenario finished")


# ---- Build machine ----

def _build_state(name, on_enter, transitions, timeout=None):
    return State(name, on_enter=on_enter, transitions=transitions, timeout=timeout)


def build_machine(group_name: str, timing: dict | None = None, emit_log=None):
    t = {
        "join_timeout": 15, "table_wait": 15, "play_timeout": 60,
        "verify_timeout": 10, "leave_timeout": 10, "next_player_wait": 20,
        "reset_timeout": 10, "cooldown": 5, "retry_max": 3,
    }
    t.update(timing or {})
    states = [
        _build_state("IDLE", _enter_idle, {"start": Transition("JOINING")}),
        _build_state("JOINING", _enter_joining, {
            "joined": Transition("WAITING_FOR_TABLE"),
            "join_failed": Transition("RETRY"),
        }, timeout=t["join_timeout"]),
        _build_state("WAITING_FOR_TABLE", _enter_waiting_table, {
            "table_ready": Transition("BOOTSTRAP_ROUND"),
            "table_wait_timeout": Transition("RETRY"),
        }, timeout=t["table_wait"]),
        _build_state("BOOTSTRAP_ROUND", _enter_bootstrap, {
            "round_ready": Transition("PLAYING"),
            "bootstrap_failed": Transition("RETRY"),
        }, timeout=t["reset_timeout"]),
        _build_state("PLAYING", _enter_playing, {
            "round_end": Transition("VERIFYING_RESULT"),
            "play_failed": Transition("RETRY"),
            "finished": Transition("FINISHED"),
        }, timeout=t["play_timeout"]),
        _build_state("VERIFYING_RESULT", _enter_verifying, {
            "main_won": Transition("LEAVING"),
            "main_lost": Transition("LEAVING"),
            "verify_failed": Transition("RETRY"),
        }, timeout=t["verify_timeout"]),
        _build_state("LEAVING", _enter_leaving, {
            "support_left": Transition("WAITING_NEXT_PLAYER"),
            "main_left": Transition("RESETTING"),
            "leave_failed": Transition("RETRY"),
        }, timeout=t["leave_timeout"]),
        _build_state("WAITING_NEXT_PLAYER", _enter_waiting_next, {
            "player_joined": Transition("PLAYING"),
            "finished": Transition("FINISHED"),
        }, timeout=t["next_player_wait"]),
        _build_state("RESETTING", _enter_resetting, {
            "reset_done": Transition("BOOTSTRAP_ROUND"),
            "reset_failed": Transition("RETRY"),
        }, timeout=t["reset_timeout"]),
        _build_state("RETRY", _enter_retry, {
            "retry_ok": Transition("__retry_target__"),
            "retry_exhausted": Transition("ERROR"),
        }),
        _build_state("ERROR", _enter_error, {
            "recover": Transition("IDLE"),
        }),
        _build_state("FINISHED", _enter_finished, {}),
    ]
    from .state_machine import StateMachine

    return StateMachine(f"group-{group_name}", states, initial="IDLE", emit_log=emit_log)

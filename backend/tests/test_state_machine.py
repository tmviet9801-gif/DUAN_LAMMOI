import asyncio

from game_sim.state_machine import State, StateMachine, Transition


def _make_machine(ok_cb=None, retry_max=3, emit_log=None):
    """Machine: IDLE -> WORKING -> (done) DONE | (fail) RETRY loop -> ERROR."""

    async def enter_working(ctx, m):
        if ok_cb is None or ok_cb(ctx):
            await m.trigger("done")
        else:
            ctx["retry_target"] = "WORKING"
            await m.trigger("work_failed")

    async def enter_retry(ctx, m):
        ctx["retries"] = ctx.get("retries", 0) + 1
        if ctx["retries"] > retry_max:
            await m.trigger("retry_exhausted")
        else:
            await m.trigger("retry_ok")

    states = [
        State("IDLE", transitions={"start": Transition("WORKING")}),
        State("WORKING", on_enter=enter_working, transitions={
            "done": Transition("DONE"),
            "work_failed": Transition("RETRY"),
        }),
        State("RETRY", on_enter=enter_retry, transitions={
            "retry_ok": Transition("__retry_target__"),
            "retry_exhausted": Transition("ERROR"),
        }),
        State("DONE", transitions={}),
        State("ERROR", transitions={}),
    ]
    return StateMachine("test", states, initial="IDLE", emit_log=emit_log)


def _run(coro):
    return asyncio.run(coro)


def test_valid_transition():
    machine = _make_machine(ok_cb=lambda ctx: True)

    async def run():
        await machine.start()
        await machine.trigger("start")
        await asyncio.sleep(0)
        return machine.current

    assert _run(run()) == "DONE"


def test_invalid_event_ignored():
    machine = _make_machine()

    async def run():
        await machine.start()
        await machine.trigger("nonexistent")
        return machine.current

    assert _run(run()) == "IDLE"


def test_condition_blocks_transition():
    states = [
        State("IDLE", transitions={
            "go": Transition("DONE", condition=lambda p: p.get("allow", False)),
        }),
        State("DONE", transitions={}),
    ]
    machine = StateMachine("t2", states, initial="IDLE")

    async def run():
        await machine.start()
        await machine.trigger("go", allow=False)
        assert machine.current == "IDLE"
        await machine.trigger("go", allow=True)
        return machine.current

    assert _run(run()) == "DONE"


def test_retry_recovers_then_succeeds():
    # Fail 2 lần rồi thành công
    attempts = {"n": 0}

    def ok(ctx):
        attempts["n"] += 1
        return attempts["n"] >= 3

    machine = _make_machine(ok_cb=ok)

    async def run():
        await machine.start()
        await machine.trigger("start")
        for _ in range(10):
            await asyncio.sleep(0)
            if machine.current in ("DONE", "ERROR"):
                break
        return machine.current

    assert _run(run()) == "DONE"
    assert machine.context["retries"] == 2


def test_retry_exhaustion_goes_error():
    machine = _make_machine(ok_cb=lambda ctx: False, retry_max=2)

    async def run():
        await machine.start()
        await machine.trigger("start")
        for _ in range(10):
            await asyncio.sleep(0)
            if machine.current in ("DONE", "ERROR"):
                break
        return machine.current

    assert _run(run()) == "ERROR"
    assert machine.context["retries"] == 3  # > retry_max(2)


def test_recovery_from_error():
    machine = _make_machine(ok_cb=lambda ctx: False, retry_max=2)
    states = machine.states
    states["ERROR"].transitions["recover"] = Transition("IDLE")

    async def run():
        await machine.start()
        await machine.trigger("start")
        for _ in range(10):
            await asyncio.sleep(0)
            if machine.current == "ERROR":
                break
        await machine.trigger("recover")
        return machine.current

    assert _run(run()) == "IDLE"

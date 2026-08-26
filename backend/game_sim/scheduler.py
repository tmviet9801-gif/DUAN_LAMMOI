"""Scheduler — chạy scenario cho từng nhóm (mỗi nhóm 1 FSM song song)."""
import asyncio
import logging

from core.time_utils import utcnow_iso

from .account_pool import AccountPool
from .game_adapter import create_adapter
from .metrics import Metrics
from .states import build_machine

log = logging.getLogger("game_sim.scheduler")


class Scheduler:
    def __init__(self, manager):
        self.manager = manager
        self.tasks = {}

    async def run_group(self, group_name, cfg, timing, stop_event, emit):
        base_run_id = self.manager.run_id
        run_id = f"{base_run_id}_{group_name}"
        pool = self.manager.pool
        adapter = self.manager.adapter
        storage = self.manager.storage
        metrics = self.manager.metrics[group_name]

        machine = build_machine(group_name, timing=timing, emit_log=emit)
        machine.set_context(
            run_id=run_id,
            group_name=group_name,
            config=cfg,
            timing=timing,
            adapter=adapter,
            pool=pool,
            metrics=metrics,
            storage=storage,
            rounds=cfg.get("rounds", 5),
            scenario=cfg.get("scenario", "winner_keeps_first_move"),
        )
        self.manager.machines[group_name] = machine

        storage.create_run(run_id, group_name, cfg.get("scenario", "winner_keeps_first_move"))
        metrics.start_cycle()
        await machine.start()

        while not stop_event.is_set() and machine.current not in ("FINISHED", "ERROR"):
            await asyncio.sleep(0.2)

        status = "finished" if machine.current == "FINISHED" else "error"
        metrics.end_cycle()
        storage.finish_run(run_id, metrics.to_dict(), status=status)
        emit(
            run_id=run_id, group_name=group_name, state_from="RUN", state_to=status.upper(),
            message=f"group done -> {status}", event_id=f"{run_id}-done",
        )
        self.manager.metrics_final[group_name] = metrics.to_dict()

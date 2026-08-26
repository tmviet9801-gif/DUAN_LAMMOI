"""Controller: Auto Flow (tìm nhau + xả bài)."""
import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

from models.config_model import load_accounts

log = logging.getLogger("auto_flow_controller")
router = APIRouter()


def _build_adapter(request, config):
    """Tạo HitClubAdapter dùng chung BrowserManager."""
    from game_sim.adapters.hitclub import HitClubAdapter
    from services.page_pool import PagePool

    bm = request.app.state.manager
    page_pool = PagePool(bm)
    accounts = load_accounts()
    lookup = {a["name"]: a for a in accounts if a.get("name")}
    return HitClubAdapter(config, account_lookup=lookup, page_pool=page_pool)


@router.post("/api/autoplay/start")
async def autoplay_start(body: dict, request: Request):
    from game_sim.auto_flow import AutoFlow

    profile_names = [n.strip() for n in (body.get("profile_names") or []) if n.strip()]
    if not profile_names:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào")
    if len(profile_names) > 10:
        raise HTTPException(status_code=400, detail="Tối đa 10 profile/chu trình")

    # license gate
    import license as lic

    if lic.max_tabs() <= 0:
        raise HTTPException(status_code=403, detail="License chưa kích hoạt hoặc hết hạn")

    # dừng run cũ nếu có
    old = getattr(request.app.state, "auto_flow", None)
    if old:
        old["flow"].stop()

    game = body.get("game", {})
    if not game.get("adapter"):
        game["adapter"] = "hitclub"
    if not game.get("url"):
        game["url"] = "https://play.hitclub.voting/?a=hitclub"
    config = {
        "game": game,
        "auto_out": bool(body.get("auto_out", True)),
        "auto_start": bool(body.get("auto_start", False)),
    }

    adapter = _build_adapter(request, config)
    run_id = f"af_{uuid.uuid4().hex[:8]}"
    flow = AutoFlow(run_id, adapter, config)

    task = asyncio.create_task(flow.run(profile_names))
    request.app.state.auto_flow = {"flow": flow, "task": task, "adapter": adapter}
    return {"ok": True, "run_id": run_id, "profiles": profile_names}


@router.post("/api/autoplay/stop")
async def autoplay_stop(request: Request):
    cur = getattr(request.app.state, "auto_flow", None)
    if cur:
        cur["flow"].stop()
        cur["task"].cancel()
        request.app.state.auto_flow = None
        return {"ok": True}
    return {"ok": False}


@router.get("/api/autoplay/status")
async def autoplay_status(request: Request):
    cur = getattr(request.app.state, "auto_flow", None)
    if not cur:
        return {"running": False, "phase": "IDLE", "members": [], "logs": []}
    flow = cur["flow"]
    return {
        "running": not flow.stop_event.is_set() and not cur["task"].done(),
        "run_id": flow.run_id,
        "phase": flow.phase,
        "phase_label": __import__("game_sim.auto_flow", fromlist=["PHASE_LABELS"]).PHASE_LABELS.get(flow.phase, flow.phase),
        "anchor": flow.anchor,
        "room_id": flow._room_id,
        "members": flow.members,
        "logs": flow.logs[-50:],
    }

"""Controller: GameSim (mô phỏng vòng đời phòng game)."""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request

from models import config_model
from models.config_model import load_accounts

log = logging.getLogger("game_sim_controller")
router = APIRouter()


def _gs_config_file():
    return config_model.DATA_DIR / "game_sim_config.json"


def _load_saved() -> dict:
    try:
        return json.loads(_gs_config_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_saved(cfg: dict):
    _gs_config_file().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_config() -> dict:
    accounts = load_accounts()
    names = [a["name"] for a in accounts if a.get("name")]
    saved = _load_saved()
    group = {}
    if names:
        group = {"main": names[0], "supports": names[1:10] or [names[0]]}
    base = {
        "scenario": "winner_keeps_first_move",
        "rounds": 5,
        "table": {"url": "https://game.example.com/room"},
        "game": {
            "adapter": "mock",
            "force": "auto",
            "join_fail_rate": 0.05,
            "mock_delay": 0.05,
        },
        "groups": {"A": group} if group else {
            "A": {"main": "A", "supports": ["A1", "A2", "A3"]},
            "B": {"main": "B", "supports": ["B1", "B2", "B3"]},
        },
        "timing": {
            "join_timeout": 15, "table_wait": 15, "play_timeout": 60,
            "verify_timeout": 10, "leave_timeout": 10, "next_player_wait": 20,
            "reset_timeout": 10, "cooldown": 5, "retry_max": 3,
        },
    }
    # Ghi đè bằng cấu hình nhóm đã lưu (nếu có)
    if saved.get("groups"):
        base["groups"] = saved["groups"]
    if saved.get("scenario"):
        base["scenario"] = saved["scenario"]
    if saved.get("rounds"):
        base["rounds"] = saved["rounds"]
    return base


@router.get("/api/gamesim/default-config")
async def gamesim_default_config():
    return _default_config()


@router.get("/api/gamesim/config")
async def gamesim_get_config():
    return _default_config()


@router.post("/api/gamesim/config")
async def gamesim_save_config(body: dict):
    """Lưu cấu hình nhóm (main + supports) cho Game Test."""
    groups = body.get("groups")
    if groups is None:
        raise HTTPException(status_code=400, detail="Thiếu 'groups'")
    # Chuẩn hóa: chỉ giữ group có main hợp lệ
    cleaned = {}
    for name, g in groups.items():
        if not name or not name.strip():
            continue
        main = (g or {}).get("main") or ""
        supports = [s for s in (g or {}).get("supports") or [] if s]
        cleaned[name.strip()] = {"main": main, "supports": supports}
    if not cleaned:
        raise HTTPException(status_code=400, detail="Ít nhất 1 nhóm hợp lệ")
    saved = _load_saved()
    saved["groups"] = cleaned
    if body.get("scenario"):
        saved["scenario"] = body["scenario"]
    if body.get("rounds"):
        saved["rounds"] = int(body["rounds"])
    _save_saved(saved)
    log.info("saved game_sim groups: %s", list(cleaned))
    return {"ok": True, "groups": cleaned}


@router.post("/api/gamesim/start")
async def gamesim_start(body: dict | None = None, request: Request = None):
    gs = request.app.state.game_sim
    cfg = body if body and body.get("groups") else _default_config()
    try:
        return await gs.start(cfg)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/gamesim/stop")
async def gamesim_stop(request: Request):
    request.app.state.game_sim.stop()
    return {"ok": True}


@router.get("/api/gamesim/status")
async def gamesim_status(request: Request):
    return request.app.state.game_sim.status()


@router.get("/api/gamesim/metrics")
async def gamesim_metrics(request: Request):
    return request.app.state.game_sim.metrics_view()


@router.get("/api/gamesim/events")
async def gamesim_events(request: Request, limit: int = 30):
    return request.app.state.game_sim.recent_events(limit=min(limit, 200))


@router.post("/api/gamesim/recover")
async def gamesim_recover(body: dict, request: Request):
    ok = request.app.state.game_sim.recover_group(body.get("group", ""))
    if not ok:
        raise HTTPException(status_code=400, detail="Không ở trạng thái ERROR")
    return {"ok": True}


@router.post("/api/gamesim/capture")
async def gamesim_capture(body: dict, request: Request):
    """Mở trang game + bật WS sniffer cho 1 account (không auto-play)."""
    from services.page_pool import PagePool
    from game_sim.ws_sniffer import WsSniffer

    name = (body.get("account_name") or "").strip()
    accounts = load_accounts()
    acc = next((a for a in accounts if a["name"] == name), None)
    if not acc:
        raise HTTPException(status_code=400, detail="Không tìm thấy account")
    bm = request.app.state.manager
    pool = PagePool(bm)
    page = await pool.get_or_open(acc)
    if not page:
        raise HTTPException(status_code=400, detail="Không mở được browser")
    url = body.get("url") or "https://play.hitclub.voting/?a=hitclub"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    sniffer = WsSniffer(config_model.DATA_DIR / "game_sim_debug")
    await sniffer.inject(page)
    stop = asyncio.Event()

    async def _drain_loop():
        while not stop.is_set():
            await sniffer.drain(page)
            await asyncio.sleep(1.0)

    task = asyncio.create_task(_drain_loop())
    request.app.state.gs_capture = {
        "task": task,
        "stop": stop,
        "file": str(sniffer.capture_file),
        "page": page,
    }
    return {"ok": True, "capture_file": str(sniffer.capture_file)}


@router.post("/api/gamesim/capture-stop")
async def gamesim_capture_stop(request: Request):
    cap = getattr(request.app.state, "gs_capture", None)
    if cap:
        cap["stop"].set()
        cap["task"].cancel()
        request.app.state.gs_capture = None
        return {"ok": True}
    return {"ok": False}


@router.get("/api/gamesim/ws-capture")
async def gamesim_ws_capture(request: Request, keyword: str = "", limit: int = 200):
    from game_sim.ws_sniffer import WsSniffer

    sniffer = WsSniffer(config_model.DATA_DIR / "game_sim_debug")
    if keyword:
        return sniffer.search(keyword, limit=min(limit, 500))
    return sniffer.recent(limit=min(limit, 500))

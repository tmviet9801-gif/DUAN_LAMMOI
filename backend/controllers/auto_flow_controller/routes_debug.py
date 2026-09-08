"""Route kiểm thử thủ công: bảo vệ bàn & xả bài cho một profile."""
import logging

from fastapi import APIRouter, HTTPException, Request

from .deps import _active_adapter

log = logging.getLogger("auto_flow_controller")
router = APIRouter()


@router.post("/api/autoplay/test-protection")
async def autoplay_test_protection(body: dict, request: Request):
    """Test bảo vệ bàn cho 1 profile: đọc phòng, người chơi, phát hiện khách lạ, và thử thoát."""
    import time
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    do_leave = bool(body.get("do_leave", False))
    known_names = body.get("known_names") or [name]

    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")

    current_room = await adapter._page_current_room(page)
    players = await adapter._get_room_players(page)
    game_state = await adapter._get_game_state(page)
    stranger_diag = await adapter._check_has_stranger(page, known_names)

    left = False
    if do_leave:
        left = await adapter._leave_room(page)

    shot = await adapter._screenshot(page, f"test_protect_{name}")
    return {
        "ok": True,
        "profile": name,
        "current_room": current_room,
        "game_state": game_state,
        "players": players,
        "stranger_diag": stranger_diag,
        "left": left,
        "screenshot": shot,
    }


@router.post("/api/autoplay/test-discard")
async def autoplay_test_discard(body: dict, request: Request):
    """Test xả bài có delay cho 1 profile."""
    import time
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    delay_ms = int(body.get("delay_ms", 1000))
    auto_out = bool(body.get("auto_out", False))

    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")

    t0 = time.time()
    ok_discard = await adapter._discard_cards(page, name, delay_ms=delay_ms)
    elapsed_ms = int((time.time() - t0) * 1000)

    left = False
    if auto_out:
        left = await adapter._leave_room(page)

    shot = await adapter._screenshot(page, f"test_discard_{name}")
    return {
        "ok": ok_discard,
        "profile": name,
        "delay_ms": delay_ms,
        "elapsed_ms": elapsed_ms,
        "left": left,
        "screenshot": shot,
    }

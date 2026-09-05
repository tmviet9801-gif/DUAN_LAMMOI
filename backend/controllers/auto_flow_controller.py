"""Controller: Auto Flow (tìm nhau + xả bài)."""
import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from models.config_model import DATA_DIR, load_accounts

log = logging.getLogger("auto_flow_controller")
router = APIRouter()

AUTOPLAY_CONFIG_FILE = DATA_DIR / "autoplay_config.json"


def _load_game_config() -> dict:
    try:
        if AUTOPLAY_CONFIG_FILE.exists():
            data = json.loads(AUTOPLAY_CONFIG_FILE.read_text(encoding="utf-8"))
            return data.get("game", {}) or {}
    except Exception:
        pass
    return {}


def _build_adapter(request, config):
    from game_sim.adapters.hitclub import HitClubAdapter
    from services.page_pool import PagePool

    bm = getattr(request.app.state, "manager", None)
    if bm is None:
        from services.browser_service import BrowserManager
        from models.config_model import load_config
        bm = BrowserManager(load_config())
        request.app.state.manager = bm
    page_pool = PagePool(bm)
    accounts = load_accounts()
    lookup = {a["name"]: a for a in accounts if a.get("name")}
    return HitClubAdapter(config, account_lookup=lookup, page_pool=page_pool)


@router.post("/api/autoplay/debug-ws-hook")
async def autoplay_debug_ws_hook(body: dict, request: Request):
    """Bật WS hook vào page của 1 profile. Mặc định KHÔNG reload (để không làm
    đứt session login của user — game này không giữ login qua reload).

    Body: {profile_name, reload?}
      - reload=true: chỉ dùng khi muốn capture TỪ ĐẦU (trước login). Lúc đó
        user phải login lại thủ công. Mặc định false = chỉ cắm hook, giữ nguyên
        trạng thái đang login.
    """
    from game_sim.ws_sniffer import WsSniffer
    from models.config_model import DATA_DIR

    name = (body.get("profile_name") or "").strip()
    do_reload = bool(body.get("reload", False))
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    manager = request.app.state.manager
    session = None
    for s in manager.sessions.values():
        if s.account and s.account.get("name") == name and s.page:
            session = s
            break
    if not session:
        raise HTTPException(status_code=400, detail="Không tìm thấy session/page của profile")
    page = session.page
    sniffer = WsSniffer(DATA_DIR / "game_sim_debug")
    await sniffer.inject_playwright(page)
    await sniffer.inject_http(page)
    # inject() patch WebSocket.prototype NGAY LẬP TỨC (bắt socket đang tồn tại)
    # — add_init_script không chạy trong patchright (trả Disposable).
    await sniffer.inject(page)
    if do_reload:
        # Xóa capture cũ để chỉ giữ demo mới
        for fn in ("ws_capture.jsonl", "room_debug.jsonl", "http_capture.jsonl"):
            try:
                fp = DATA_DIR / "game_sim_debug" / fn
                if fp.exists():
                    fp.unlink()
            except Exception:
                pass
        try:
            await page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        log.info("WS hook đã bật cho %s + RELOAD (capture từ đầu).", name)
        return {"ok": True, "reloaded": True, "message": "WS hook + reload. Thao tác join phòng để bắt WS."}
    log.info("WS hook đã bật cho %s (KHÔNG reload, giữ session).", name)
    return {"ok": True, "reloaded": False, "message": "WS hook đã bật, KHÔNG reload — session login được giữ nguyên."}


@router.post("/api/autoplay/debug-test-join")
async def autoplay_debug_test_join(body: dict, request: Request):
    """Test: JOIN bàn có kèm rid từ danh sách cmd=300.

    Thử nhiều format join, kiểm tra cmd=202 xem có vào đúng bàn (rid) không.
    """
    from game_sim.ws_sniffer import WsSniffer
    from models.config_model import DATA_DIR

    name = (body.get("profile_name") or "").strip()
    rid_override = body.get("rid")
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    manager = request.app.state.manager
    session = None
    for s in manager.sessions.values():
        if s.account and s.account.get("name") == name and s.page:
            session = s
            break
    if not session:
        raise HTTPException(status_code=400, detail="Không tìm thấy session của profile")
    page = session.page
    sniffer = WsSniffer(DATA_DIR / "game_sim_debug")
    await sniffer.inject_playwright(page)
    await sniffer.inject_init(page)
    # reload để socket reconnect qua hook (bắt được _PAGE_WS)
    try:
        await page.reload(wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    await asyncio.sleep(6)

    # chờ socket sẵn sàng
    from game_sim.ws_sniffer import _PAGE_WS
    import time
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _PAGE_WS.get(id(page)) is not None:
            break
        await asyncio.sleep(0.5)

    results = {"rid": None, "rooms_seen": [], "join_tests": []}

    # 1) xem danh sách bàn
    await sniffer.send_raw(page, '[6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":1}]')
    await asyncio.sleep(3)
    await sniffer.drain(page)
    msgs = sniffer.recent(limit=800)
    rooms = []
    for it in msgs:
        try:
            arr = json.loads(it.get("text", ""))
        except Exception:
            continue
        if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], dict):
            p = arr[1]
            if p.get("cmd") == 300 and isinstance(p.get("rs"), list):
                for r in p["rs"]:
                    if isinstance(r, dict) and r.get("rid"):
                        rooms.append({"rid": r.get("rid"), "uC": r.get("uC"), "b": r.get("b"), "rn": r.get("rn"), "Mu": r.get("Mu")})
    # chọn phòng trống
    empty = [r for r in rooms if r["uC"] == 0]
    empty.sort(key=lambda r: r.get("b", 0))
    target = None
    if rid_override:
        target = {"rid": int(rid_override)}
    elif empty:
        target = empty[0]
    results["rooms_seen"] = rooms[:10]
    if not target:
        return {**results, "error": "không có phòng trống để test"}
    rid = target["rid"]
    results["rid"] = rid
    results["target_room"] = target

    # 2) thử join với rid (nhiều format)
    variants = [
        f'[3,"Simms",1,{{"rid":{rid}}}]',
        f'[3,"Simms",1,"{{\\"rid\\":{rid}}}"]',
        f'[3,"Simms",1,{rid}]',
        f'[3,"Simms",1,"{rid}"]',
    ]
    for i, variant in enumerate(variants):
        # out nếu đang trong phòng
        await sniffer.send_raw(page, '[4,"Simms",-1]')
        await asyncio.sleep(1.5)
        ok_send = await sniffer.send_raw(page, variant)
        await asyncio.sleep(3)
        await sniffer.drain(page)
        msgs2 = sniffer.recent(limit=800)
        room202 = None
        for it in msgs2:
            try:
                arr = json.loads(it.get("text", ""))
            except Exception:
                continue
            if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], dict):
                p = arr[1]
                if p.get("cmd") == 202:
                    ps = p.get("ps", [])
                    room202 = {"b": p.get("b"), "Mu": p.get("Mu"), "gS": p.get("gS"), "players": [x.get("dn") for x in ps]}
        results["join_tests"].append({
            "variant": variant, "sent": ok_send, "room202": room202,
        })
        if room202:
            # đã vào phòng, dừng thử tiếp
            results["working_variant"] = variant
            break

    return results


@router.post("/api/autoplay/start")
async def autoplay_start(body: dict, request: Request):
    from game_sim.auto_flow import AutoFlow

    profile_names = [n.strip() for n in (body.get("profile_names") or []) if n.strip()]
    if not profile_names:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào")
    if len(profile_names) > 10:
        raise HTTPException(status_code=400, detail="Tối đa 10 profile/chu trình")

    import license as lic

    if lic.max_tabs() <= 0:
        raise HTTPException(status_code=403, detail="License chưa kích hoạt hoặc hết hạn")

    old = getattr(request.app.state, "auto_flow", None)
    if old:
        old["flow"].stop()

    # gộp config từ body + config đã lưu
    game = body.get("game", {}) or {}
    saved = _load_game_config()
    merged = {**saved, **game}
    if not merged.get("adapter"):
        merged["adapter"] = "hitclub"
    if not merged.get("url"):
        merged["url"] = "https://v.hitclub.latino/?a=hitclub"
    config = {
        "game": merged,
        "auto_out": bool(body.get("auto_out", True)),
        "auto_start": bool(body.get("auto_start", False)),
        "chong_pha": bool(body.get("chong_pha", True)),
        "out_guest": bool(body.get("out_guest", True)),
        "xa_delay_ms": int(body.get("xa_delay_ms", 1000)),
    }

    adapter = _build_adapter(request, config)
    run_id = f"af_{uuid.uuid4().hex[:8]}"
    flow = AutoFlow(run_id, adapter, config)

    task = asyncio.create_task(flow.run(profile_names))
    request.app.state.auto_flow = {"flow": flow, "task": task, "adapter": adapter}
    return {"ok": True, "run_id": run_id, "profiles": profile_names}


_GOM_BAN_STOP = False


async def _get_screen_size_util(p):
    try:
        sz = await p.evaluate("({w: window.innerWidth, h: window.innerHeight})")
        return int(sz.get("w") or 784), int(sz.get("h") or 505)
    except Exception:
        return 784, 505


async def _is_in_tldl_lobby_util(p):
    if not p:
        return False
    try:
        from PIL import Image
        import io
        png_bytes = await p.screenshot(type="png")
        im = Image.open(io.BytesIO(png_bytes))
        w, h = im.size
        r1, g1, b1 = im.getpixel((int(w * 0.290), int(h * 0.310)))[:3]
        r2, g2, b2 = im.getpixel((int(w * 0.500), int(h * 0.310)))[:3]
        is_green_tables = (r1 < 40 and g1 > 70 and b1 < 40) and (r2 < 40 and g2 > 70 and b2 < 40)
        return is_green_tables
    except Exception:
        return False


async def _ensure_in_tldl_lobby_util(p, name="Profile", target_mu=2):
    if not p:
        return False
    sw, sh = await _get_screen_size_util(p)
    if await _is_in_tldl_lobby_util(p):
        try:
            tab_x = 0.500 if target_mu == 2 else 0.690
            await p.mouse.click(int(sw * tab_x), int(sh * 0.175))
            await asyncio.sleep(0.4)
        except Exception:
            pass
        return True

    log.info("%s chưa ở sảnh Tiến Lên Đếm Lá -> Bắt đầu đưa về đúng sảnh...", name)
    try:
        await p.mouse.click(50, 50)
        await asyncio.sleep(0.3)
        await p.mouse.click(364, 313)
        await asyncio.sleep(0.3)
        await p.mouse.click(int(sw * 0.854), int(sh * 0.233))
        await asyncio.sleep(0.3)
    except Exception:
        pass

    try:
        await p.mouse.click(335, 128)
        await asyncio.sleep(1.0)
        await p.mouse.click(235, 239)
        await asyncio.sleep(2.0)
    except Exception as e:
        log.warning("Lỗi click vào Tiến Lên Đếm Lá: %s", e)

    try:
        tab_x = 0.500 if target_mu == 2 else 0.690
        await p.mouse.click(int(sw * tab_x), int(sh * 0.175))
        await asyncio.sleep(0.4)
    except Exception:
        pass

    return await _is_in_tldl_lobby_util(p)


async def _do_leave_room(p):
    if not p:
        return
    # Nếu đã ở sảnh TLDL (nhìn thấy các bàn cược xanh lá) -> Bỏ qua không bấm kẻo văng ra ngoài sảnh cổng game
    if await _is_in_tldl_lobby_util(p):
        return
    sw, sh = await _get_screen_size_util(p)
    try:
        # 1. Bấm nút menu [>] góc trên bên trái trong bàn chơi (70, 120)
        await p.mouse.click(int(0.089 * sw), int(0.238 * sh))
        await asyncio.sleep(0.4)
        # 2. Bấm nút biểu tượng cửa [🚪] rời bàn
        await p.mouse.click(int(0.080 * sw), int(0.360 * sh))
        await asyncio.sleep(0.3)
    except Exception:
        pass
    # 3. Gửi lệnh WebSocket rời bàn đảm bảo 100%
    try:
        await p.evaluate("""(() => {
            try {
                if (typeof window.__ws_send_channel === 'function') window.__ws_send_channel('Simms', '[4,"Simms",-1]');
                else if (typeof window.__ws_send === 'function') window.__ws_send('[4,"Simms",-1]');
            } catch(e) {}
        })()""")
    except Exception:
        pass
    await asyncio.sleep(0.6)


@router.post("/api/autoplay/leave-all")
@router.post("/api/autoplay/stop")
async def autoplay_stop(request: Request):
    """Dừng auto và thoát tất cả các profile đang mở khỏi bàn về lại sảnh:
    - Click menu thoát + cửa thoát trên canvas
    - Gửi lệnh WebSocket rời bàn [4, "Simms", -1]
    - Reset room_id = -1, log = "Đã thoát phòng" trên session
    """
    global _GOM_BAN_STOP
    _GOM_BAN_STOP = True

    # 1. Dừng flow cũ nếu có
    cur = getattr(request.app.state, "auto_flow", None)
    if cur:
        try:
            cur["flow"].stop()
            cur["task"].cancel()
        except Exception:
            pass
        request.app.state.auto_flow = None

    # 2. Duyệt qua toàn bộ session đang mở và ép thoát phòng
    manager = getattr(request.app.state, "manager", None)
    left_profiles = []
    if manager and manager.sessions:
        for sid, s in list(manager.sessions.items()):
            if s.page:
                try:
                    await _do_leave_room(s.page)
                except Exception as e:
                    log.warning("Thoát phòng session %s lỗi: %s", sid, e)
            s.room_id = -1
            s.log = "Đã thoát phòng"
            acc_name = (s.account or {}).get("name") or sid
            left_profiles.append(acc_name)

    log.info("autoplay_stop/leave-all: Đã thoát toàn bộ phòng cho %d profile: %s", len(left_profiles), left_profiles)
    return {
        "ok": True, 
        "count": len(left_profiles),
        "profiles": left_profiles,
        "message": f"Đã thoát phòng thành công cho {len(left_profiles)} tài khoản."
    }


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


# ---- config persistence ----
@router.get("/api/autoplay/config")
async def get_autoplay_config():
    return {"game": _load_game_config()}


@router.post("/api/autoplay/config")
async def save_autoplay_config(body: dict):
    game = body.get("game", {}) or {}
    AUTOPLAY_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTOPLAY_CONFIG_FILE.write_text(
        json.dumps({"game": game}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("autoplay config saved: clicks=%s patterns=%s",
             list(game.get("clicks", {}).keys()),
             list(game.get("ws_patterns", {}).keys()))
    return {"ok": True}


# ---- capture mode ----
@router.post("/api/autoplay/capture")
async def autoplay_capture(body: dict, request: Request):
    """Mở profile + bật WS sniffer, chờ user chơi thủ công để ghi protocol."""
    from game_sim.auto_flow import AutoFlow

    profile_names = [n.strip() for n in (body.get("profile_names") or []) if n.strip()]
    if not profile_names:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào")

    import license as lic

    if lic.max_tabs() <= 0:
        raise HTTPException(status_code=403, detail="License chưa kích hoạt hoặc hết hạn")

    old = getattr(request.app.state, "auto_flow", None)
    if old:
        old["flow"].stop()

    saved = _load_game_config()
    game = {**saved, **body.get("game", {}), "adapter": "hitclub", "capture": True}
    if not game.get("url"):
        game["url"] = "https://v.hitclub.latino/?a=hitclub"
    if not game.get("clicks"):
        game["clicks"] = saved.get("clicks", {})
    config = {"game": game, "auto_out": False, "auto_start": False}

    adapter = _build_adapter(request, config)
    run_id = f"cap_{uuid.uuid4().hex[:8]}"
    flow = AutoFlow(run_id, adapter, config)
    task = asyncio.create_task(flow.run(profile_names))
    request.app.state.auto_flow = {"flow": flow, "task": task, "adapter": adapter}
    return {
        "ok": True,
        "run_id": run_id,
        "capture_file": str(adapter.sniffer.capture_file),
        "profiles": profile_names,
    }


# ---- test click ----
@router.post("/api/autoplay/test-click")
async def autoplay_test_click(body: dict, request: Request):
    """Click thử 1 tọa độ trên profile đã mở (để xác định vị trí nút trong canvas)."""
    name = (body.get("profile_name") or "").strip()
    x = int(body.get("x") or 0)
    y = int(body.get("y") or 0)
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if not x or not y:
        raise HTTPException(status_code=400, detail="Thiếu tọa độ x, y")

    adapter = _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    try:
        await page.bring_to_front()
    except Exception:
        pass
    await page.mouse.click(x, y)
    await asyncio.sleep(0.6)
    await adapter.sniffer.drain(page)
    shot = await adapter._screenshot(page, f"test_click_{name}_{x}x{y}")
    return {"ok": True, "clicked": [x, y], "screenshot": shot, "profile": name}


# ---- gửi raw WS / join bàn theo rid (để 2 tài khoản vào CÙNG 1 bàn) ----
def _active_adapter(request):
    """Dùng adapter của capture/autoplay run đang chạy (có sẵn sniffer đã hook
    socket Playwright). Fallback: build mới nếu chưa có run nào."""
    af = getattr(request.app.state, "auto_flow", None)
    if af and af.get("adapter") is not None:
        return af["adapter"]
    return _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})


@router.post("/api/autoplay/send-raw")
async def autoplay_send_raw(body: dict, request: Request):
    """Gửi 1 message WS thô vào profile đã mở (dùng để join bàn theo rid).

    Body: {profile_name, text, channel?} — channel tùy chọn: "Simms"/"MiniGame"/"MiniGame3".
    Nếu không truyền channel, tự chọn socket game (Simms).
    """
    name = (body.get("profile_name") or "").strip()
    text = body.get("text")
    channel = (body.get("channel") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if not text:
        raise HTTPException(status_code=400, detail="Thiếu text")
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    if channel:
        ok = await adapter.sniffer.send_raw_channel(page, channel, str(text))
    else:
        ok = await adapter.sniffer.send_raw(page, str(text))
    return {"ok": bool(ok)}


@router.post("/api/autoplay/create-table")
@router.post("/api/autoplay/join-quick")
async def autoplay_create_table(body: dict, request: Request):
    """Tạo hoặc vào bàn cược thực tế cho profile:
    1. Kiểm tra trình duyệt đã mở chưa -> nếu chưa thì báo lỗi rõ ràng.
    2. Đưa vào sảnh TLDL, chọn tab Solo (2) hoặc 4 người.
    3. Click bàn cược tương ứng (mặc định 100).
    4. Trích xuất Room ID thật.
    5. Cập nhật Room ID vào session để giao diện chính hiển thị ngay lập tức.
    """
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    bet = int(body.get("bet", 100) or 100)
    mu = int(body.get("mu", 2) or 2)
    pwd = str(body.get("pwd", "2222") or "2222")

    adapter = _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})
    page = await adapter._page(name)
    if not page:
        raise HTTPException(
            status_code=400, 
            detail=f"Trình duyệt cho tài khoản '{name}' chưa được mở! Vui lòng tích chọn tài khoản và bấm nút 'Mở Chrome' trước khi tạo phòng."
        )

    # 1. Cắm sniffer & hook
    try:
        await adapter.sniffer.inject_playwright(page)
        await adapter.sniffer.inject_init(page)
        await adapter.sniffer.inject_workers(page)
    except Exception:
        pass

    # 2. Đưa vào sảnh TLDL và chọn tab bàn 2 / 4 người
    await _ensure_in_tldl_lobby_util(page, name, target_mu=mu)

    # 3. Tọa độ click bàn cược
    rx, ry = BET_RATIOS.get(bet, (0.290, 0.310))
    sw, sh = await _get_screen_size_util(page)
    click_x = int(sw * rx)
    click_y = int(sh * ry)

    # 4. Click vào bàn cược trên canvas
    await page.mouse.click(click_x, click_y)
    await asyncio.sleep(1.5)

    # 5. Gửi WS hỗ trợ join/auto-ready
    try:
        await adapter.sniffer.send_raw(page, '[6,"Simms","channelPlugin",{"cmd":363,"aRd":"true"}]')
    except Exception:
        pass

    # 6. Trích xuất Room ID thực tế
    rid = None
    for _ in range(6):
        try:
            val = await page.evaluate("() => (window.__last_room_info && window.__last_room_info.rid) || window.__ws_last_room_id || null")
            if val and int(val) > 0 and int(val) != 100:
                rid = int(val)
                break
        except Exception:
            pass
        if not rid:
            cur = await adapter._page_current_room(page)
            if cur and int(cur) > 0 and int(cur) != 100:
                rid = int(cur)
                break
        await asyncio.sleep(0.3)

    final_rid = rid if rid else bet

    # 7. Cập nhật Room ID vào session của manager
    bm = getattr(request.app.state, "manager", None)
    if bm:
        for sess in bm.sessions.values():
            if sess.account and (sess.account.get("name") == name or sess.account.get("id") == name):
                sess.room_id = final_rid
                sess.log = f"Bàn #{final_rid} (${bet})"
                break

    return {
        "ok": True, 
        "room_id": final_rid, 
        "bet": bet, 
        "mu": mu, 
        "pwd": pwd,
        "message": f"Đã vào bàn #{final_rid} (${bet}) thành công!"
    }


@router.post("/api/autoplay/join-rid")
async def autoplay_join_rid(body: dict, request: Request):
    """Ép 1 profile join CHÍNH XÁC vào bàn có rid (không random như click 'bàn 100').

    Gửi: [6,"Simms","channelPlugin",{"cmd":308,"aid":1,"gid":<gid>,"b":<bet>,
          "Mu":2,"iJ":true,"inc":false,"pwd":"1","rid":<rid>}]
    """
    name = (body.get("profile_name") or "").strip()
    rid = body.get("rid")
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if rid is None:
        raise HTTPException(status_code=400, detail="Thiếu rid")
    gid = int(body.get("gid", 1))
    bet = int(body.get("bet", 100))
    mu = int(body.get("mu", 2))
    payload = {
        "cmd": 308, "aid": 1, "gid": gid, "b": bet, "Mu": mu,
        "iJ": True, "inc": False, "pwd": "1", "rid": int(rid),
    }
    import json as _json
    text = _json.dumps([6, "Simms", "channelPlugin", payload])
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    ok = await adapter.sniffer.send_raw(page, text)
    return {"ok": bool(ok), "sent": text}


# ---- ép 1 profile join CHÍNH XÁC vào bàn rid, dùng template bắt được ----
@router.post("/api/autoplay/join-by-id")
async def autoplay_join_by_id(body: dict, request: Request):
    """Ép 1 profile join đúng bàn rid, dùng template từ capture.

    Ưu tiên: dùng game socket đã bắt (gửi qua send_raw) — chính xác nhất.
    Fallback: kênh WS phụ (join_by_id_side) nếu game socket chưa sẵn sàng.
    KHÔNG reload, KHÔNG logout.

    Body: {profile_name, rid, template?}
      - template: chuỗi bắt từ /api/autoplay/join-capture (có placeholder {room_id}).
        Nếu không truyền, build template mặc định.
    """
    name = (body.get("profile_name") or "").strip()
    rid = body.get("rid")
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if rid is None:
        raise HTTPException(status_code=400, detail="Thiếu rid")
    template = (body.get("template") or "").strip()
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    # thử dùng game socket (captured via reconnect-ws) trước
    result = await adapter.join_by_id(name, rid, template or None)
    if result.get("ok"):
        return result
    # fallback: WS phụ
    log.info("join_by_id (game socket) fail, fallback to side channel")
    result2 = await adapter.join_by_id_side(name, rid, template or None)
    return result2


# ---- chẩn đoán sniffer trên page đang mở ----
@router.get("/api/autoplay/sniffer-status")
async def autoplay_sniffer_status(request: Request):
    """Đọc trực tiếp trên từng page đang mở: hook đã inject chưa, capture có gì."""
    bm = request.app.state.manager
    from game_sim.ws_sniffer import _PAGE_WS
    result = []
    for sid, s in bm.sessions.items():
        page = s.page
        name = (s.account or {}).get("name", sid)
        hooked = False
        count = 0
        url = ""
        page_ws = None
        if page:
            try:
                hooked = bool(await page.evaluate("() => !!(window.__ws_hooked)"))
            except Exception:
                pass
            try:
                count = int(await page.evaluate("() => (window.__ws_capture || []).length") or 0)
            except Exception:
                pass
            try:
                url = page.url
            except Exception:
                pass
            ws = _PAGE_WS.get(id(page))
            if ws is not None:
                try:
                    page_ws = {"url": ws.url, "state": ws.state if hasattr(ws, "state") else "?"}
                except Exception:
                    page_ws = {"url": "?", "error": True}
        result.append({"name": name, "hooked": hooked, "capture_count": count, "url": url, "page_ws": page_ws})
        if page:
            try:
                frames_diag = []
                for f in page.frames:
                    try:
                        diag = await f.evaluate(
                            """() => {
                                const inst = window.__ws_instances || [];
                                const cap = window.__ws_capture || [];
                                return {
                                    hooked: !!window.__ws_hooked,
                                    instCount: inst.length,
                                    instReady: inst.filter(s => s && s.readyState === 1).length,
                                    capCount: cap.length,
                                    instUrls: inst.map(s => (s && s.url || "")).slice(0, 5)
                                };
                            }"""
                        )
                        frames_diag.append({"url": f.url[:80], **diag})
                    except Exception:
                        frames_diag.append({"url": (f.url or "")[:80], "error": True})
                result[-1]["frames_diag"] = frames_diag
            except Exception as e:
                result[-1]["frames_diag"] = {"error": str(e)[:100]}
            try:
                result[-1]["workers"] = len([w for w in page.workers if w])
            except Exception:
                pass
    return {"sessions": result}


# ---- trích accessToken từ page (lưu phiên để dùng client WS độc lập) ----
@router.post("/api/autoplay/session-token")
async def autoplay_session_token(body: dict, request: Request):
    """Đọc accessToken từ page (sessionStorage/localStorage/JS globals).

    Vì game dính captcha khi login, ta lấy token 1 lần (login manual),
    lưu lại để dùng standalone WS client cho automation — không cần re-login.
    """
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    js = """
    () => {
        const found = [];
        const grab = (obj) => {
            try {
                for (let i = 0; i < obj.length; i++) {
                    const k = obj.key(i);
                    const v = obj.getItem(k);
                    if (v && typeof v === 'string' && (v.includes('accessToken') || v.includes('token') || v.includes('1-e') || /^[0-9a-f]{32}$/.test(v) || v.includes('e838bf'))) {
                        found.push({store:'storage', key:k, value:String(v).slice(0,200)});
                    }
                }
            } catch (e) {}
        };
        try { grab(window.sessionStorage); } catch (e) {}
        try { grab(window.localStorage); } catch (e) {}
        try {
            if (document.cookie) found.push({store:'cookie', value: document.cookie.slice(0,300)});
        } catch (e) {}
        // dò global vars chứa token
        try {
            for (const k in window) {
                const v = window[k];
                if (v && typeof v === 'string' && (v.includes('accessToken') || /^1-[0-9a-f]{32}$/.test(v) || v.includes('e838bf'))) {
                    found.push({store:'global', key:k, value:String(v).slice(0,200)});
                }
            }
        } catch (e) {}
        return found;
    }
    """
    try:
        data = await page.evaluate(js)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"evaluate fail: {e}")
    # tìm token dạng 1-<32hex>
    import re as _re
    token = None
    for item in data or []:
        val = str(item.get("value") or "")
        m = _re.search(r"1-[0-9a-f]{32}", val)
        if m:
            token = m.group(0)
            break
    # lưu token MỚI vào token store (login thủ công cũng được tính là login mới)
    if token:
        try:
            from models.config_model import DATA_DIR
            from game_sim.token_store import TokenStore

            TokenStore(DATA_DIR / "game_sim_token.json").save(name, token)
        except Exception:
            pass
    return {"profile": name, "token": token, "found": data or []}


# ---- reload page với hook từ đầu (bắt được WS sau khi login) ----
@router.post("/api/autoplay/reload")
async def autoplay_reload(body: dict, request: Request):
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    await adapter.sniffer.inject_playwright(page)
    await adapter.sniffer.inject_init(page)
    await adapter.sniffer.inject_http(page)
    url = adapter.url or "https://v.hitclub.latino/?a=hitclub"
    diag = {}
    try:
        ctx = page.context
        pages = ctx.pages
        diag["pages_in_context"] = len(pages)
        diag["pages"] = []
        for p in pages:
            try:
                diag["pages"].append({"url": p.url[:120], "title": (await p.title())[:60]})
            except Exception:
                pass
    except Exception as e:
        diag["context_err"] = str(e)[:100]
    try:
        # page.reload() = force reload thật (service worker/SPA không chặn),
        # nên add_init_script chạy -> hook WS từ đầu.
        await page.reload(wait_until="domcontentloaded", timeout=60000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.warning("reload goto fail: %s", e)
    await asyncio.sleep(float(adapter.game.get("load_wait", 4)))
    try:
        diag["hooked_after"] = bool(await page.evaluate("() => !!(window.__ws_hooked)"))
    except Exception:
        diag["hooked_after"] = "err"
    return {"ok": True, "reloaded": name, "diag": diag}


# ---- đọc Gold gần nhất của profile từ ws_capture ----
@router.get("/api/autoplay/gold")
async def autoplay_gold(request: Request):
    name = (request.query_params.get("profile_name") or "").strip()
    is_acc2 = any(x in name.lower() for x in ["2", "sub", "phu", "xabai2"])
    dn_target = "nicktestxxabai2" if is_acc2 else "nicktestxxabai1"
    gold = 77607 if is_acc2 else 57377

    from models.config_model import DATA_DIR as _DATA
    import json as _json
    cf = _DATA / "game_sim_debug" / "ws_capture.jsonl"
    if cf.exists():
        for line in reversed(cf.read_text(encoding="utf-8", errors="replace").splitlines()):
            if '"cmd":100' in line or '"cmd\\":100' in line:
                try:
                    d = _json.loads(line)
                    arr = _json.loads(d.get("text", ""))
                    pl = arr[1] if isinstance(arr, list) and len(arr) > 1 else {}
                    dn = pl.get("dn") or ""
                    if dn == dn_target:
                        as_ = pl.get("As") or {}
                        if as_.get("gold") is not None:
                            gold = as_.get("gold")
                            break
                except Exception:
                    continue
    return {"profile": name, "gold": gold, "dn": dn_target}


_REPORTED_ROOMS = {}


@router.post("/api/autoplay/report-room")
async def autoplay_report_room(body: dict, request: Request):
    """Extension tự động báo cáo thông tin bàn cược hiện tại lên Backend."""
    p_name = str(body.get("profile_name") or "").strip().lower()
    rid = int(body.get("rid") or 0)
    if rid > 0:
        _REPORTED_ROOMS[p_name] = {
            "rid": rid,
            "b": body.get("b"),
            "rn": body.get("rn"),
            "ts": time.time(),
            "data": body,
        }
        # Nếu có cả tên nick thì map thêm key Account01/Account02
        if "1" in p_name or "acc01" in p_name or "xabai1" in p_name:
            _REPORTED_ROOMS["account01"] = _REPORTED_ROOMS[p_name]
        elif "2" in p_name or "acc02" in p_name or "xabai2" in p_name:
            _REPORTED_ROOMS["account02"] = _REPORTED_ROOMS[p_name]
        log.info("report-room: Đã ghi nhận bàn #%s cho profile='%s' (cược %s)!", rid, p_name, body.get("b"))
    return {"ok": True, "reported": _REPORTED_ROOMS.get(p_name)}


@router.get("/api/autoplay/profile-info")
async def autoplay_profile_info(request: Request):
    """Lấy thông tin tài khoản, số dư và bàn cược thời gian thực cho từng Profile trên Extension."""
    name = (request.query_params.get("profile_name") or "Account01").strip()
    is_acc2 = any(x in name.lower() for x in ["2", "sub", "phu", "xabai2"])
    dn_target = "nicktestxxabai2" if is_acc2 else "nicktestxxabai1"
    user_name = "nicktestxabai2" if is_acc2 else "nicktestxabai1"
    gold = 77607 if is_acc2 else 57377
    profile_key = "account02" if is_acc2 else "account01"

    from models.config_model import DATA_DIR as _DATA
    import json as _json
    cf = _DATA / "game_sim_debug" / "ws_capture.jsonl"
    if cf.exists():
        for line in reversed(cf.read_text(encoding="utf-8", errors="replace").splitlines()):
            if '"cmd":100' in line or '"cmd\\":100' in line:
                try:
                    d = _json.loads(line)
                    arr = _json.loads(d.get("text", ""))
                    pl = arr[1] if isinstance(arr, list) and len(arr) > 1 else {}
                    dn = pl.get("dn") or ""
                    if dn == dn_target:
                        as_ = pl.get("As") or {}
                        if as_.get("gold") is not None:
                            gold = as_.get("gold")
                            break
                except Exception:
                    continue

    # Lấy thông tin phòng hiện tại từ báo cáo extension hoặc quét page
    room_text = "Ở sảnh (Chưa vào bàn)"
    bet_text = "--"
    rep = _REPORTED_ROOMS.get(profile_key) or _REPORTED_ROOMS.get(name.lower()) or _REPORTED_ROOMS.get(user_name.lower())
    if rep and rep.get("rid"):
        room_text = rep.get("rn") or f"Bàn #{rep['rid']}"
        bet_text = f"${int(rep['b']):,}" if rep.get("b") else "--"

    return {
        "ok": True,
        "profile": "Account02" if is_acc2 else "Account01",
        "user": user_name,
        "dn": dn_target,
        "gold": gold,
        "room": room_text,
        "bet": bet_text,
        "players": [],
    }


# ---- trích xuất room id + template join từ capture WS (để test nhanh) ----
@router.get("/api/autoplay/join-capture")
async def autoplay_join_capture(request: Request, profile_name: str = ""):
    """Trích xuất nhanh room id + template join cmd=308 từ capture (ws_capture.jsonl).

    Quy trình test:
      1) Mở profile đã login -> gọi /api/autoplay/debug-ws-hook (bật capture + reload)
      2) Thao tác join 1 bàn bằng chuột (game sẽ gửi cmd=308)
      3) Gọi endpoint này (tuỳ chọn ?profile_name=... để drain page trước)
         -> trả về rooms[], last_room_id, join_template (sẵn sàng để SUPPORT join chung bàn).
    """
    from game_sim.ws_sniffer import WsSniffer
    from game_sim.adapters.hitclub import _find_cmd_payload

    save_dir = DATA_DIR / "game_sim_debug"
    sniffer = WsSniffer(save_dir)

    if profile_name:
        try:
            adapter = _active_adapter(request)
            page = await adapter._page(profile_name)
            if page:
                await sniffer.drain(page)
        except Exception:
            pass

    msgs = sniffer.recent(limit=30000)
    rooms = {}
    last_rid = None
    template = None
    for it in msgs:
        try:
            arr = json.loads(it.get("text", ""))
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        idx, p = _find_cmd_payload(arr)
        if not isinstance(p, dict):
            continue
        cmd = p.get("cmd")
        # danh sách bàn: cmd=300 recv -> rs[]
        if cmd == 300 and isinstance(p.get("rs"), list):
            for r in p["rs"]:
                if isinstance(r, dict) and isinstance(r.get("rid"), (int, float)):
                    rid = int(r["rid"])
                    rooms[rid] = {
                        "rid": rid,
                        "rn": r.get("rn"),
                        "uC": r.get("uC"),
                        "b": r.get("b"),
                        "gid": r.get("gid"),
                        "Mu": r.get("Mu"),
                    }
        # room id hiện tại: cmd=305/308 recv -> ri.rid
        if cmd in (305, 308) and isinstance(p.get("ri"), dict):
            r = p["ri"].get("rid")
            if isinstance(r, (int, float)) and r > 0:
                last_rid = int(r)
        # template join: cmd=308 SEND (bản gốc, chưa thay rid)
        if it.get("dir") in ("send", "inject") and cmd == 308:
            raw = dict(p)
            raw.pop("rid", None)
            raw["rid"] = "{room_id}"
            new_arr = list(arr)
            new_arr[idx] = raw
            template = json.dumps(new_arr, ensure_ascii=False)
    return {
        "message_count": len(msgs),
        "rooms": list(rooms.values()),
        "last_room_id": last_rid,
        "join_template": template,
        "has_template": template is not None,
    }


# ---- liệt kê bàn qua WS phụ (KHÔNG reload, không động session login) ----
@router.get("/api/autoplay/list-rooms")
async def autoplay_list_rooms(request: Request, profile_name: str = "", gid: int = 1):
    """Liệt kê các bàn (cmd=300) của profile đã login, dùng WS phụ — không reload."""
    if not profile_name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    adapter = _active_adapter(request)
    page = await adapter._page(profile_name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {profile_name}")
    result = await adapter.list_rooms_side(profile_name, gid=gid)
    return result


# ---- buộc game mở lại WS (offline->online) để bắt socket thật, KHÔNG reload ----
@router.post("/api/autoplay/reconnect-ws")
async def autoplay_reconnect_ws(body: dict, request: Request):
    """Buộc game mở lại WS bằng cách toggle offline->online.

    Game đang login giữ WS của nó được tạo TRƯỚC khi ta cắm hook, nên không bắt
    được. Toggle offline làm WS rớt; khi online game tự reconnect bằng session của
    nó -> socket mới được wrapper (window.__ws_map/__ws_last) bắt, ta gửi lệnh
    join qua chính socket authenticated đó. KHÔNG reload, KHÔNG logout.
    """
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    manager = request.app.state.manager
    session = None
    for s in manager.sessions.values():
        if s.account and s.account.get("name") == name and s.page:
            session = s
            break
    if not session:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy profile {name}")
    page = session.page
    ctx = page.context
    # bảo đảm hook Playwright + unified hook (constructor+prototype) active ở MỌI frame
    try:
        from game_sim.ws_sniffer import WsSniffer
        from models.config_model import DATA_DIR as _DATA

        sniffer = WsSniffer(_DATA / "game_sim_debug")
        await sniffer.inject_playwright(page)
        await sniffer.inject(page)
        await sniffer.inject_workers(page)
    except Exception as e:
        diag_ = {"inject_err": str(e)[:100]}
    diag = {}
    try:
        await ctx.set_offline(True)
        diag["offline_set"] = True
    except Exception as e:
        diag["offline_err"] = str(e)[:100]
    await asyncio.sleep(2)
    try:
        await ctx.set_offline(False)
        diag["online_restored"] = True
    except Exception as e:
        diag["online_err"] = str(e)[:100]
    await asyncio.sleep(10)
    try:
        diag["captured_urls"] = await page.evaluate("() => Object.keys(window.__ws_map || {})")
        diag["instances"] = await page.evaluate("() => (window.__ws_instances || []).map(s => (s && s.url) || '').slice(0, 8)")
    except Exception as e:
        diag["captured_err"] = str(e)[:100]
    return {"profile": name, "diag": diag}


# ---- Luồng WebSocket: Tìm bàn trống 100/500 & Ghép Account 2 ----
@router.post("/api/autoplay/find-and-match-ws")
async def autoplay_find_and_match_ws(body: dict, request: Request):
    """Tìm bàn trống (chỉ mức cược 100 hoặc 500) qua WebSocket và tự động
    ghép Account 2 vào cùng bàn mà không cần click UI / popup.

    Body:
      - profile_a: str (mặc định "Account01")
      - profile_b: str (tuỳ chọn "Account02")
      - bet_levels: list[int] (mặc định [100, 500])
      - gid: int (mặc định 1 = Tiến Lên Đếm Lá)
    """
    import random as _rand
    import json as _json

    profiles_input = body.get("profiles") or []
    if not profiles_input:
        p_a = (body.get("profile_a") or "").strip()
        p_b = (body.get("profile_b") or "").strip()
        profiles_input = [p for p in [p_a, p_b] if p]
    if not profiles_input:
        profiles_input = ["Account01", "Account02"]

    profile_a = profiles_input[0]
    profile_b = profiles_input[1] if len(profiles_input) > 1 else ""
    gid = int(body.get("gid", 1))
    target_bet = int(body.get("target_bet", 100) or 100)  # Mặc định $100
    target_mu = int(body.get("mu", 2) or 2)              # Mặc định 2 = Solo 2 người

    auto_xa = bool(body.get("auto_xa", True))
    auto_start_guest_ss = bool(body.get("auto_start_guest_ss", True))
    auto_leave_after = bool(body.get("auto_leave_after", True))

    adapter = _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})
    page_a = await adapter._page(profile_a)
    if not page_a:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {profile_a}")

    BET_RATIOS = {
        100: (0.290, 0.310),      # Hàng 1 - Cột 1 ($100)
        500: (0.500, 0.310),      # Hàng 1 - Cột 2 ($500)
        1000: (0.700, 0.310),     # Hàng 1 - Cột 3 ($1K / 1.000)
        2000: (0.290, 0.480),     # Hàng 2 - Cột 1 ($2K / 2.000)
        5000: (0.500, 0.480),     # Hàng 2 - Cột 2 ($5K / 5.000)
        10000: (0.700, 0.480),    # Hàng 2 - Cột 3 ($10K / 10.000)
        20000: (0.290, 0.650),    # Hàng 3 - Cột 1 ($20K / 20.000)
        50000: (0.500, 0.650),    # Hàng 3 - Cột 2 ($50K / 50.000)
        100000: (0.700, 0.650),   # Hàng 3 - Cột 3 ($100K / 100.000)
        200000: (0.290, 0.820),   # Hàng 4 - Cột 1 ($200K)
        500000: (0.500, 0.820),   # Hàng 4 - Cột 2 ($500K)
        1000000: (0.700, 0.820),  # Hàng 4 - Cột 3 ($1M)
    }

    bet_val = target_bet if target_bet in BET_RATIOS else 100
    rx, ry = BET_RATIOS[bet_val]

    from PIL import Image
    import io

    async def _get_screen_size(p):
        try:
            sz = await p.evaluate("({w: window.innerWidth, h: window.innerHeight})")
            return int(sz.get("w") or 784), int(sz.get("h") or 505)
        except Exception:
            return 784, 505

    async def _is_in_tldl_lobby(p):
        if not p:
            return False
        try:
            png_bytes = await p.screenshot(type="png")
            im = Image.open(io.BytesIO(png_bytes))
            w, h = im.size
            r1, g1, b1 = im.getpixel((int(w * 0.290), int(h * 0.310)))[:3]
            r2, g2, b2 = im.getpixel((int(w * 0.500), int(h * 0.310)))[:3]
            is_green_tables = (r1 < 40 and g1 > 70 and b1 < 40) and (r2 < 40 and g2 > 70 and b2 < 40)
            return is_green_tables
        except Exception:
            return False

    async def _ensure_in_tldl_lobby(p, name="Profile"):
        if not p:
            return False
        if await _is_in_tldl_lobby(p):
            # Chọn đúng tab Solo / 4 người
            try:
                sw, sh = await _get_screen_size(p)
                tab_x = 0.500 if target_mu == 2 else 0.690
                await p.mouse.click(int(sw * tab_x), int(sh * 0.175))
                await asyncio.sleep(0.4)
            except Exception:
                pass
            return True

        log.info("find-and-match: %s chưa ở sảnh Tiến Lên Đếm Lá -> Bắt đầu đưa về đúng sảnh...", name)
        sw, sh = await _get_screen_size(p)
        # Đóng popup nếu có (banner cảnh báo hoặc mời vào bàn)
        try:
            # 1. Click khoảng trống an toàn ngoài dialog (50, 50)
            await p.mouse.click(50, 50)
            await asyncio.sleep(0.3)
            # 2. Click nút TỪ CHỐI HẾT (364, 313) nếu có popup Mời Vào Bàn
            await p.mouse.click(364, 313)
            await asyncio.sleep(0.3)
            # 3. Click nút đóng đỏ trên modal nếu có
            await p.mouse.click(int(sw * 0.854), int(sh * 0.233))
            await asyncio.sleep(0.3)
        except Exception:
            pass

        # Bấm tab GAME BÀI (tọa độ chính xác x=335, y=128 trên canvas 784x505)
        try:
            await p.mouse.click(335, 128)
            await asyncio.sleep(1.0)
            # Bấm icon TIẾN LÊN ĐẾM LÁ (tọa độ chính xác x=235, y=239 trên canvas 784x505)
            await p.mouse.click(235, 239)
            await asyncio.sleep(2.0)
        except Exception as e:
            log.warning("find-and-match: Lỗi click vào Tiến Lên Đếm Lá: %s", e)

        # Chọn đúng tab Solo / 4 người
        try:
            tab_x = 0.500 if target_mu == 2 else 0.690
            await p.mouse.click(int(sw * tab_x), int(sh * 0.175))
            await asyncio.sleep(0.4)
        except Exception:
            pass

        return await _is_in_tldl_lobby(p)

    async def _do_leave_room(p):
        if not p:
            return
        # Nếu đã ở sảnh TLDL (nhìn thấy các bàn cược xanh lá) -> Tuyệt đối không bấm nút góc trái kẻo văng ra sảnh chính HitClub!
        if await _is_in_tldl_lobby(p):
            return
        sw, sh = await _get_screen_size(p)
        try:
            # 1. Bấm nút menu [>] góc trên bên trái trong bàn chơi (70, 120)
            await p.mouse.click(int(0.089 * sw), int(0.238 * sh))
            await asyncio.sleep(0.4)
            # 2. Bấm nút biểu tượng cửa [🚪] rời bàn
            await p.mouse.click(int(0.080 * sw), int(0.360 * sh))
        except Exception:
            pass
        # 3. Gửi lệnh WebSocket rời bàn đảm bảo 100%
        try:
            await p.evaluate("""(() => {
                try {
                    if (typeof window.__ws_send_channel === 'function') window.__ws_send_channel('Simms', '[4,\"Simms\",-1]');
                    else if (typeof window.__ws_send === 'function') window.__ws_send('[4,\"Simms\",-1]');
                } catch(e) {}
            })()""")
        except Exception:
            pass
        await asyncio.sleep(1.0)

    global _GOM_BAN_STOP
    _GOM_BAN_STOP = False

    async def _set_hud_status(p, msg):
        if not p:
            return
        try:
            await p.evaluate(f"window.__autotool_hud_status = {_json.dumps(msg)};")
        except Exception:
            pass

    # Chuẩn bị Playwright Page cho tất cả tài khoản tham gia (2 đến 5 tài khoản)
    pages = {}
    for p_name in profiles_input:
        try:
            p = await adapter._page(p_name)
            if p:
                pages[p_name] = p
                try:
                    await adapter.sniffer.inject_playwright(p)
                    await adapter.sniffer.inject(p)
                except Exception:
                    pass
        except Exception as e:
            log.warning("find-and-match: Không mở được trang cho %s: %s", p_name, e)

    if not pages:
        raise HTTPException(status_code=400, detail=f"Không có tài khoản nào trong {profiles_input} đang mở trình duyệt!")

    # Đảm bảo tất cả tài khoản tham gia đều đã vào đúng sảnh Tiến Lên Đếm Lá
    for p_name, p in pages.items():
        await _ensure_in_tldl_lobby(p, p_name)

    log.info("find-and-match: Khởi động tìm kiếm bàn đồng bộ cho %d tài khoản: %s (Cược $%s)", 
             len(pages), list(pages.keys()), bet_val)

    found_anchor = False
    anchor_name = None
    anchor_page = None
    anchor_rid = None

    # BƯỚC 1: THỬ TẠO PHÒNG TRỐNG TRƯỚC (NẾU HỆ THỐNG CHO PHÉP TẠO MỨC CƯỢC NÀY)
    first_name = list(pages.keys())[0]
    first_page = pages[first_name]
    log.info("find-and-match: [Bước 1] Thử tạo phòng cược $%s cho %s trước...", bet_val, first_name)
    try:
        w_f, h_f = await _get_screen_size(first_page)
        # Gửi packet cmd 308 tạo phòng (iJ: False, rid: 0)
        create_payload = {
            "cmd": 308, "aid": 1, "gid": gid, "b": bet_val, "Mu": target_mu,
            "iJ": False, "inc": False, "pwd": "1", "rid": 0
        }
        await adapter.sniffer.send_raw(first_page, _json.dumps([6, "Simms", "channelPlugin", create_payload]))
        await asyncio.sleep(1.2)
        if not await _is_in_tldl_lobby(first_page):
            # Kiểm tra xem có phải bàn trống không
            png_test = await first_page.screenshot(type="png")
            im_test = Image.open(io.BytesIO(png_test))
            w_curr, h_curr = im_test.size
            r_c, g_c, b_c = im_test.getpixel((int(w_curr * 0.50), int(h_curr * 0.238)))[:3]
            if r_c > 180 and g_c > 150 and b_c < 110:
                anchor_name = first_name
                anchor_page = first_page
                found_anchor = True
                log.info("find-and-match: >>> TẠO PHÒNG TRỐNG THÀNH CÔNG CHO %s! <<<", first_name)
    except Exception as e:
        log.info("find-and-match: Thử tạo phòng không thành công (%s), chuyển sang nhảy dò tìm bàn...", e)

    raw_tries = int(body.get("max_tries", 0) or 0)
    infinite_mode = (raw_tries <= 0)
    max_tries = 999999 if infinite_mode else raw_tries

    # BƯỚC 2: NẾU CHƯA TẠO ĐƯỢC -> CÁC TÀI KHOẢN CÙNG NHẢY DÒ TÌM BÀN TRỐNG
    if not found_anchor:
        for attempt in range(1, max_tries + 1):
            if _GOM_BAN_STOP:
                log.info("find-and-match: Người dùng đã bấm DỪNG! Hủy bỏ vòng lặp gom bàn ngay lập tức.")
                for p in pages.values():
                    await _do_leave_room(p)
                return {"ok": False, "error": "Đã dừng chu trình gom bàn theo lệnh của bạn.", "stopped": True}

            attempt_str = f"Lần {attempt} (Vô hạn)" if infinite_mode else f"Lần {attempt}/{max_tries}"
            log.info("find-and-match: [%s] Cho %d tài khoản cùng nhảy dò tìm bàn $%s...", attempt_str, len(pages), bet_val)

            # Cập nhật HUD cho các tài khoản
            for p_name, p in pages.items():
                await _set_hud_status(p, f"[{attempt_str}] Đang nhảy tìm bàn trống ${bet_val}...")

            # Tất cả các tài khoản bấm vào bàn cược với khoảng cách an toàn 350ms
            for p_name, p in pages.items():
                if _GOM_BAN_STOP:
                    break
                if not await _is_in_tldl_lobby(p):
                    await _ensure_in_tldl_lobby(p, p_name)
                w_p, h_p = await _get_screen_size(p)
                cx_p = int(w_p * rx)
                cy_p = int(h_p * ry)
                await p.mouse.click(cx_p, cy_p)
                await asyncio.sleep(0.35)

            await asyncio.sleep(1.8)

            # Kiểm tra lần lượt từng tài khoản: tài khoản nào thấy bàn trống trước thì trở thành Anchor
            for p_name, p in pages.items():
                if _GOM_BAN_STOP:
                    break
                if await _is_in_tldl_lobby(p):
                    continue

                try:
                    png_bytes = await p.screenshot(type="png")
                    im = Image.open(io.BytesIO(png_bytes))
                    w_curr, h_curr = im.size
                    check_x = int(w_curr * 0.50)
                    check_y = int(h_curr * 0.238)
                    r, g, b = im.getpixel((check_x, check_y))[:3]
                    is_empty = (r > 180 and g > 150 and b < 110)
                except Exception:
                    is_empty = False

                if is_empty:
                    anchor_name = p_name
                    anchor_page = p
                    found_anchor = True
                    log.info("find-and-match: >>> TÀI KHOẢN %s ĐÃ TÌM THẤY BÀN TRỐNG ĐẦU TIÊN! ĐỨNG LẠI GIỮ BÀN! <<<", anchor_name)
                    break
                else:
                    # Bàn có người lạ -> tài khoản này lập tức thoát ra sảnh ngay
                    log.info("find-and-match: %s vào bàn có người lạ (RGB=%s,%s,%s) -> out về sảnh ngay", p_name, r, g, b)
                    await _do_leave_room(p)

            if found_anchor:
                # Tất cả các tài khoản khác lập tức out về sảnh để chuẩn bị join vào bàn của Anchor
                for other_name, other_p in pages.items():
                    if other_name != anchor_name:
                        if not await _is_in_tldl_lobby(other_p):
                            await _do_leave_room(other_p)
                break
            else:
                # Không tài khoản nào tìm được bàn trống ở lượt này -> tất cả đảm bảo về sảnh và thử lại
                for other_name, other_p in pages.items():
                    if not await _is_in_tldl_lobby(other_p):
                        await _do_leave_room(other_p)
                await asyncio.sleep(0.8)

    if not found_anchor or not anchor_page:
        return {
            "ok": False,
            "error": f"Sau {max_tries} lần thử, tất cả bàn ${bet_val} đều đang có người. Vui lòng thử lại hoặc đổi mức cược.",
            "profiles": list(pages.keys()),
        }

    # BƯỚC 3: LẤY ROOM ID (RID) CHÍNH XÁC CỦA ANCHOR
    for _ in range(8):
        try:
            val = await anchor_page.evaluate("() => (window.__last_room_info && window.__last_room_info.rid) || window.__ws_last_room_id || null")
            if val and int(val) > 0 and int(val) != 100:
                anchor_rid = int(val)
                break
        except Exception:
            pass
        if not anchor_rid:
            cur = await adapter._page_current_room(anchor_page)
            if cur and int(cur) > 0 and int(cur) != 100:
                anchor_rid = int(cur)
                break
        await asyncio.sleep(0.2)

    selected_rid = anchor_rid if anchor_rid else bet_val
    log.info("find-and-match: Anchor=%s đang giữ bàn trống #%s ($%s). Điều phối các nick khác join vào...", 
             anchor_name, selected_rid, bet_val)
    await _set_hud_status(anchor_page, f"Đang giữ bàn #{selected_rid}! Đợi đồng đội vào...")

    # BƯỚC 4: ĐIỀU PHỐI CÁC TÀI KHOẢN CÒN LẠI JOIN VÀO BÀN CỦA ANCHOR
    other_profiles = [name for name in pages.keys() if name != anchor_name]
    for sub_name in other_profiles:
        sub_p = pages[sub_name]
        log.info("find-and-match: Cho %s join vào bàn #%s của anchor %s...", sub_name, selected_rid, anchor_name)
        await _set_hud_status(sub_p, f"Đang join vào bàn #{selected_rid} của {anchor_name}...")

        if anchor_rid:
            payload_join = {
                "cmd": 308, "aid": 1, "gid": gid, "b": bet_val, "Mu": target_mu,
                "iJ": True, "inc": False, "pwd": "1", "rid": int(anchor_rid)
            }
            try:
                await adapter.sniffer.send_raw(sub_p, _json.dumps([6, "Simms", "channelPlugin", payload_join]))
            except Exception:
                pass
            try:
                await adapter.sniffer.send_raw(sub_p, f'[3,"Simms",1,{{"rid":{anchor_rid}}}]')
            except Exception:
                pass

        # Click biểu tượng bàn cược trên canvas để đồng bộ giao diện
        w_s, h_s = await _get_screen_size(sub_p)
        await sub_p.mouse.click(int(w_s * rx), int(h_s * ry))
        await asyncio.sleep(0.5)

    # Chờ các tài khoản vào bàn đầy đủ (tối đa 5 giây)
    await asyncio.sleep(2.5)

    # Cập nhật thông tin phòng hiển thị lên Dashboard cho toàn bộ tài khoản
    bm = getattr(request.app.state, "manager", None)
    if bm and bm.sessions:
        for sid, s in list(bm.sessions.items()):
            acc_n = (s.account or {}).get("name")
            if acc_n == anchor_name:
                s.room_id = selected_rid
                s.log = f"Chủ bàn #{selected_rid} (${bet_val})"
            elif acc_n in pages:
                s.room_id = selected_rid
                s.log = f"Bàn #{selected_rid} (cùng {anchor_name})"

    # BƯỚC 5: NẾU TẮT 'TỰ ĐỘNG XẢ BÀI' -> DỪNG CHỜ THAO TÁC TAY
    if not auto_xa:
        log.info("find-and-match: Đã gom thành công các tài khoản vào bàn #%s! 'Tự động xả bài' TẮT -> Dừng chờ thao tác tay.", selected_rid)
        for p_name, p in pages.items():
            await _set_hud_status(p, f"Đã vào chung bàn #{selected_rid}! Đang chờ thao tác tay.")
        return {
            "ok": True,
            "anchor": anchor_name,
            "profiles": list(pages.keys()),
            "room_id": selected_rid,
            "bet": bet_val,
            "room_name": f"Bàn #{selected_rid} (${bet_val})",
        }

    # BƯỚC 6: TIẾN HÀNH SẴN SÀNG -> BẮT ĐẦU -> XẢ BÀI
    # 1. Các tài khoản phụ bấm [ SẴN SÀNG ]
    for sub_name in other_profiles:
        sub_p = pages[sub_name]
        sw_b, sh_b = await _get_screen_size(sub_p)
        log.info("find-and-match: %s bấm nút [ SẴN SÀNG ]...", sub_name)
        await sub_p.mouse.click(int(sw_b * 0.50), int(sh_b * 0.555))
        await asyncio.sleep(0.4)

    # 2. Anchor (Chủ bàn) bấm nút [ BẮT ĐẦU ]
    sw_a, sh_a = await _get_screen_size(anchor_page)
    start_x = int(sw_a * 0.50)
    start_y = int(sh_a * 0.555)
    log.info("find-and-match: Anchor=%s bấm nút [ BẮT ĐẦU ]...", anchor_name)
    await anchor_page.mouse.click(start_x, start_y)
    await asyncio.sleep(3.2)

    # 3. THUẬT TOÁN MỚM BÀI TỐI ƯU (GREEDY HAND DECOMPOSITION & JOINT UTILITY OPTIMIZATION)
    # -------------------------------------------------------------------------------------
    from core.card_strategy import CooperativeDiscardEngine, HandDecomposition

    primary_sub_page = pages[other_profiles[0]] if other_profiles else None
    primary_sub_name = other_profiles[0] if other_profiles else "Phụ"

    savings = HandDecomposition.compute_theoretical_savings(bet_val)
    log.info("find-and-match: Kích hoạt CooperativeDiscardEngine: Tiết kiệm %s%% phế bàn, Acc 2 thua tối thiểu %s", 
             savings["savings_percent"], savings["loss_optimal"])

    engine = CooperativeDiscardEngine(
        anchor_page=anchor_page,
        sub_page=primary_sub_page,
        anchor_name=anchor_name,
        sub_name=primary_sub_name
    )
    await engine.execute_optimal_discard()

    # BƯỚC 7: BẪY KHÁCH LẠ SẴN SÀNG (NẾU BẬT auto_start_guest_ss)
    if auto_start_guest_ss:
        log.info("find-and-match: Chế độ 'Bắt đầu nếu khách SS' đang bật, chủ bàn đứng giữ bàn...")
        for _ in range(20):
            if _GOM_BAN_STOP:
                break
            try:
                pls = await anchor_page.evaluate("() => window.__room_players || []")
                guest_ss = any(pl.get("aRd") is True or pl.get("ss") is True for pl in pls if pl.get("dn") not in pages and pl.get("u") not in pages)
                if guest_ss:
                    log.info("find-and-match: ⚡ PHÁT HIỆN KHÁCH LẠ SẴN SÀNG! Kích hoạt BẮT ĐẦU NGAY!")
                    await anchor_page.mouse.click(start_x, start_y)
                    await asyncio.sleep(1.0)
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)

    # BƯỚC 8: TỰ OUT VỀ SẢNH SAU KHI XẢ (NẾU BẬT auto_leave_after)
    if auto_leave_after:
        log.info("find-and-match: Chế độ 'Tự Out sau khi xả' đang bật -> Tất cả các nick rời bàn về sảnh...")
        await asyncio.sleep(1.0)
        for p_name, p in pages.items():
            await _do_leave_room(p)
        if bm and bm.sessions:
            for sid, s in list(bm.sessions.items()):
                acc_n = (s.account or {}).get("name")
                if acc_n in pages:
                    s.room_id = -1
                    s.log = "Hoàn thành xả bài, đã về sảnh"

    shot_a = await adapter._screenshot(anchor_page, f"matched_{anchor_name}")

    return {
        "ok": True,
        "anchor": anchor_name,
        "profiles": list(pages.keys()),
        "room_id": selected_rid,
        "bet": bet_val,
        "room_name": f"Bàn #{selected_rid} (${bet_val})",
        "theoretical_savings": savings if 'savings' in locals() else None,
        "screenshot": shot_a,
    }


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




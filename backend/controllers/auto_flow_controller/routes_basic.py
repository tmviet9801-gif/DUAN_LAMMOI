"""Route Auto Flow đơn lẻ: debug, start/stop, config, join theo rid, sniffer..."""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Body, HTTPException, Request

from models.config_model import load_accounts

from .constants import AUTOPLAY_CONFIG_FILE, FIXED_TABLE_RIDS
from .check_live import check_live, check_one_profile
from .context import resolve_profile_name
from .deps import _active_adapter, _build_adapter, _load_game_config
from .lobby import (
    _clear_hunt_state,
    _do_leave_room,
    _ensure_in_tldl_lobby_util,
)
from core.page_world import eval_page

log = logging.getLogger("auto_flow_controller")
router = APIRouter()


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

    # Chuẩn hoá về TÊN PROFILE trong accounts.json. Trước đây chuỗi thô của
    # client chảy thẳng xuống `adapter.join()` -> `token_store.save(<chuỗi thô>)`.
    # Vì `account_lookup` nhận cả username, gửi "nicktestxabai1" vẫn mở đúng
    # Chrome (không lỗi gì) nhưng ghi token dưới khoá username, trong khi
    # đường đọc tra khoá khác -> profile phải đăng nhập lại dù token còn sống.
    _accounts = load_accounts()
    profile_names = [resolve_profile_name(n.strip(), _accounts)
                     for n in (body.get("profile_names") or []) if n.strip()]
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


# Tương thích trạng thái cũ. Việc dừng thực tế dùng stop_epoch trên app state
# để nhiều cặp có thể chạy đồng thời mà không vô hiệu hoá lẫn nhau.
_GOM_BAN_STOP = False
_GOM_BAN_RUN_ID = 0
_GOM_BAN_ACTIVE_RUN_ID = None


def _pham_vi_dung(request, body):
    """Những profile nào được phép đụng tới khi bấm Dừng.

    Bản trước dừng MỌI session đang mở. Người dùng mở 6 Chrome, tích 2 cái để
    gom bàn, 4 cái còn lại đang tự tay chơi bài — bấm Dừng là cả 4 nick kia bị
    gửi lệnh rời bàn GIỮA VÁN, mất tiền cược.

    Thứ tự: tên do người gọi chỉ định (nút trên từng dòng) -> các profile của
    lượt chạy đang hoạt động -> nếu không biết gì thì mới đụng tất cả.

    Trả `(ten_set, toan_bo)`. `toan_bo=True` nghĩa là không giới hạn.
    """
    ten = set()
    if isinstance(body, dict):
        mot = str(body.get("profile_name") or "").strip()
        if mot:
            ten.add(mot)
        for x in (body.get("profile_names") or []):
            x = str(x or "").strip()
            if x:
                ten.add(x)
    if ten:
        return ten, False

    dang_chay = getattr(request.app.state, "gom_ban_profiles", None)
    if dang_chay:
        return set(dang_chay), False

    return set(), True


def _thuoc_pham_vi(session, sid, ten, toan_bo):
    if toan_bo:
        return True
    acc = session.account or {}
    goc = {str(acc.get("name") or "").strip().lower(),
           str(acc.get("username") or "").strip().lower(),
           str(acc.get("character_name") or "").strip().lower(),
           str(acc.get("id") or "").strip().lower(),
           str(sid or "").strip().lower()}
    goc.discard("")
    return any(str(t).strip().lower() in goc for t in ten)


@router.post("/api/autoplay/leave-all")
async def autoplay_leave_all(request: Request):
    """Dừng auto và thoát TẤT CẢ profile đang mở khỏi bàn. Không giới hạn phạm vi."""
    return await _dung_auto(request, None, ep_toan_bo=True)


@router.post("/api/autoplay/stop")
async def autoplay_stop(request: Request, body: dict | None = Body(default=None)):
    """Dừng auto — CHỈ trong phạm vi liên quan.

    Body (tuỳ chọn):
      - profile_name / profile_names: chỉ dừng đúng những profile này.
      - bỏ trống: chỉ dừng các profile thuộc lượt gom bàn đang chạy.

    Trước đây hàm này KHÔNG đọc body, nên nút "Dừng"/"Thoát.P" trên từng dòng
    (vốn đã gửi `profile_name`) vẫn dừng toàn bộ nhóm.
    """
    return await _dung_auto(request, body, ep_toan_bo=False)


async def _dung_auto(request: Request, body, ep_toan_bo=False):
    global _GOM_BAN_STOP, _GOM_BAN_ACTIVE_RUN_ID
    ten_pham_vi, toan_bo = _pham_vi_dung(request, body)
    if ep_toan_bo:
        ten_pham_vi, toan_bo = set(), True
    _GOM_BAN_STOP = True
    _GOM_BAN_ACTIVE_RUN_ID = None  # invalidate run_id: chặn mọi lệnh/task mang run_id cũ
    request.app.state.gom_ban_stop_epoch = int(getattr(request.app.state, "gom_ban_stop_epoch", 0)) + 1

    # 1. KHOÁ cơ chế chia sẻ bàn + broadcast STOP_HUNT NGAY (trước khi cancel task)
    #    để không còn JOIN_ROOM "zombie" phát ra trong lúc task đang thoát.
    ext_hub = getattr(request.app.state, "ext_hub", None)
    if ext_hub:
        try:
            ext_hub.set_room_share(False)
            if toan_bo:
                await ext_hub.broadcast_command("STOP_HUNT", {"reset": True})
                log.info("autoplay_stop: Đã broadcast STOP_HUNT tới tất cả các extensions!")
            else:
                # Broadcast chạm tới MỌI extension đang online, kể cả profile
                # người dùng đang tự chơi. Trong phạm vi hẹp thì gửi đích danh.
                for t in ten_pham_vi:
                    try:
                        if ext_hub.is_connected(t):
                            await ext_hub.send_command(t, "STOP_HUNT", {"reset": True})
                    except Exception:
                        pass
                log.info("autoplay_stop: Đã gửi STOP_HUNT tới %d profile trong phạm vi: %s",
                         len(ten_pham_vi), sorted(ten_pham_vi))
        except Exception as e:
            log.warning("autoplay_stop broadcast error: %s", e)

    # 2. Dập tắt NGAY toàn bộ trạng thái auto-hunt & timers trên tất cả các trang Chrome
    manager = getattr(request.app.state, "manager", None)
    if manager and manager.sessions:
        for sid, s in list(manager.sessions.items()):
            if not _thuoc_pham_vi(s, sid, ten_pham_vi, toan_bo):
                continue
            if s.page:
                try:
                    await _clear_hunt_state(s.page)
                except Exception:
                    pass

    # 3. Ngắt tiến trình gom bàn / tìm bàn đang chạy NGAY LẬP TỨC (không chờ 15s nữa)
    active_tasks = set(getattr(request.app.state, "active_match_tasks", set()))
    active_match_task = getattr(request.app.state, "active_match_task", None)
    if active_match_task:
        active_tasks.add(active_match_task)
    for task in active_tasks:
        if task and not task.done():
            try:
                task.cancel()
            except Exception as e:
                log.warning("autoplay_stop: Lỗi cancel task gom bàn: %s", e)
    if active_tasks:
        log.info("autoplay_stop: Đã cancel %d task gom bàn ngay lập tức!", len(active_tasks))
    request.app.state.active_match_tasks = set()
    request.app.state.active_match_task = None

    # 4. Dừng flow cũ nếu có
    cur = getattr(request.app.state, "auto_flow", None)
    if cur:
        try:
            cur["flow"].stop()
            cur["task"].cancel()
        except Exception:
            pass
        request.app.state.auto_flow = None

    # 5. Dừng là thao tác tức thì: tuyệt đối không gọi luồng click/điều hướng
    # về sảnh ở đây. Các thao tác đó có sleep + OpenCV và khiến người dùng thấy
    # auto vẫn chạy nhiều giây sau khi đã bấm Dừng.
    stopped_profiles = []
    if manager and manager.sessions:
        for sid, s in list(manager.sessions.items()):
            if not _thuoc_pham_vi(s, sid, ten_pham_vi, toan_bo):
                continue
            acc_name = (s.account or {}).get("name") or sid
            s.room_id = -1
            s.log = "Đã dừng tự động"
            stopped_profiles.append(acc_name)

    log.info("autoplay_stop: Đã dừng tức thì %d profile, không chạy thêm điều hướng/click: %s", len(stopped_profiles), stopped_profiles)
    return {
        "ok": True, 
        "count": len(stopped_profiles),
        "profiles": stopped_profiles,
        "message": f"Đã dừng tức thì {len(stopped_profiles)} tài khoản; không gửi thêm lệnh join/click."
    }


@router.post("/api/autoplay/leave-room")
async def autoplay_leave_room(body: dict, request: Request):
    """Thoát 1 account chỉ định (hoặc tất cả) ra khỏi bàn về sảnh bàn Đếm Lá.

    Body:
      - profile_name: str (tuỳ chọn, nếu bỏ trống thì thoát tất cả)
      - ws_only: bool (mặc định True = thuần WebSocket không click chuột)
    """
    profile_name = (body.get("profile_name") or "").strip()
    ws_only = bool(body.get("ws_only", True))

    manager = getattr(request.app.state, "manager", None)
    if not manager or not manager.sessions:
        return {"ok": True, "count": 0, "ws_command": '[4,"Simms",-1]', "message": "Không có session nào đang mở."}

    left_list = []
    for sid, s in list(manager.sessions.items()):
        acc_n = (s.account or {}).get("name") or sid
        if profile_name and acc_n != profile_name and sid != profile_name:
            continue
        if s.page:
            try:
                # Gửi lệnh WebSocket thoát phòng trực tiếp
                await eval_page(s.page, """(() => {
                    try {
                        if (typeof window.__ws_send_channel === 'function') {
                            window.__ws_send_channel('Simms', '[4,"Simms",-1]');
                            window.__ws_send_channel('Simms', '[6,"Simms","channelPlugin",{"cmd":203}]');
                        }
                        if (typeof window.__ws_send === 'function') {
                            window.__ws_send('[4,"Simms",-1]');
                            window.__ws_send('[6,"Simms","channelPlugin",{"cmd":203}]');
                        }
                        (window.__ws_instances || []).forEach(ws => {
                            try {
                                if (ws.readyState === 1) {
                                    ws.send('[4,"Simms",-1]');
                                    ws.send('[6,"Simms","channelPlugin",{"cmd":203}]');
                                }
                            } catch(e) {}
                        });
                    } catch(e) {}
                })()""")
                await asyncio.sleep(0.4)
                if not ws_only:
                    await _do_leave_room(s.page, name=acc_n)
                await _ensure_in_tldl_lobby_util(s.page, name=acc_n)
            except Exception as e:
                log.warning("Thoát phòng WS cho %s lỗi: %s", acc_n, e)
        s.room_id = -1
        s.log = "Đang ở sảnh bàn Đếm Lá"
        left_list.append(acc_n)

    return {
        "ok": True,
        "count": len(left_list),
        "profiles": left_list,
        "ws_command": '[4,"Simms",-1]',
        "message": f"Đã đưa {len(left_list)} tài khoản về đứng trước sảnh bàn Tiến Lên Đếm Lá."
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

    # Cùng lý do như /api/autoplay/start: tên thô của client sinh khoá token lạ.
    _accounts = load_accounts()
    profile_names = [resolve_profile_name(n.strip(), _accounts)
                     for n in (body.get("profile_names") or []) if n.strip()]
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
    3. Gửi RID cố định tương ứng (mặc định 100); không click toạ độ canvas.
    4. Trích xuất Room ID thật.
    5. Cập nhật Room ID vào session để giao diện chính hiển thị ngay lập tức.
    """
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    bet = int(body.get("bet", 100) or 100)
    mu = int(body.get("mu", 2) or 2)
    pwd = ""

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

    # 3. Join bằng RID cố định; từ chối nếu socket chưa sẵn sàng thay vì click
    # mù sang $500 do trạng thái chọn bàn cũ của Cocos.
    rid_expected = FIXED_TABLE_RIDS.get(f"{bet}_{mu}")
    if not rid_expected:
        raise HTTPException(status_code=400, detail=f"Chưa có RID xác minh cho mức ${bet}, bàn {mu} người")
    joined = False
    try:
        joined = bool(await eval_page(page, """(rid) => {
            const s = (window.__ws_get_simms && window.__ws_get_simms()) || null;
            if (!s || s.readyState !== 1) return false;
            s.send(JSON.stringify([3, 'Simms', Number(rid), '']));
            return true;
        }""", rid_expected))
    except Exception:
        joined = False
    if not joined:
        raise HTTPException(status_code=503, detail="Chưa bắt được socket game để join đúng RID; không click fallback để tránh vào sai bàn")
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
            val = await eval_page(page, "() => (window.__last_room_info && window.__last_room_info.rid) || window.__ws_last_room_id || null")
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

    final_rid = rid if rid else rid_expected

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
        "iJ": True, "inc": False, "pwd": "", "rid": int(rid),
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
                hooked = bool(await eval_page(page, "() => !!(window.__ws_hooked)"))
            except Exception:
                pass
            try:
                count = int(await eval_page(page, "() => (window.__ws_capture || []).length") or 0)
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
                        diag = await eval_page(f, 
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
        data = await eval_page(page, js)
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

            _acc = next(
                (a for a in load_accounts()
                 if str(a.get("name") or "").strip().lower() == name.strip().lower()),
                None)
            store = TokenStore(DATA_DIR / "game_sim_token.json")
            if _acc:
                store.save_for_account(_acc, token)
            else:
                store.save(name, token)
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
        diag["hooked_after"] = bool(await eval_page(page, "() => !!(window.__ws_hooked)"))
    except Exception:
        diag["hooked_after"] = "err"
    return {"ok": True, "reloaded": name, "diag": diag}


# ---- số dư THẬT của profile ----
@router.get("/api/autoplay/gold")
async def autoplay_gold(request: Request):
    """Số dư hiện tại của một profile, đọc từ trang đang mở hoặc Extension Hub.

    Bản trước ĐOÁN account theo việc tên có chứa chữ "2" rồi trả số dư HARDCODE
    (77607 / 57377), chỉ dò ws_capture.jsonl như một cải thiện may rủi. Nghĩa là
    giao diện có thể hiển thị số dư của account khác, hoặc số bịa hoàn toàn.
    """
    name = (request.query_params.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")

    accounts = load_accounts()
    acc = next((a for a in accounts
                if (a.get("name") or "").strip().lower() == name.lower()), None)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"Không có account tên {name}")

    live = await check_one_profile(
        _active_adapter(request), getattr(request.app.state, "ext_hub", None), acc)
    return {
        "profile": acc.get("name"),
        "gold": live.get("so_du"),      # None nếu chưa đọc được — KHÔNG bịa
        "dn": live.get("ten_in_game"),
        "mo": live.get("mo"),
        "loi": live.get("loi"),
    }


_REPORTED_ROOMS = {}


@router.post("/api/autoplay/report-room")
async def autoplay_report_room(body: dict, request: Request):
    """Extension tự động báo cáo thông tin bàn cược hiện tại lên Backend."""
    import time as _time
    p_name = str(body.get("profile_name") or "").strip().lower()
    rid = int(body.get("rid") or 0)
    if rid > 0:
        _REPORTED_ROOMS[p_name] = {
            "rid": rid,
            "b": body.get("b"),
            "rn": body.get("rn"),
            "ts": _time.time(),
            "data": body,
        }
        # Nếu có cả tên nick thì map thêm key Account01/Account02
        if "1" in p_name or "acc01" in p_name or "xabai1" in p_name:
            _REPORTED_ROOMS["account01"] = _REPORTED_ROOMS[p_name]
        elif "2" in p_name or "acc02" in p_name or "xabai2" in p_name:
            _REPORTED_ROOMS["account02"] = _REPORTED_ROOMS[p_name]
        log.info("report-room: Đã ghi nhận bàn #%s cho profile='%s' (cược %s)!", rid, p_name, body.get("b"))
    return {"ok": True, "reported": _REPORTED_ROOMS.get(p_name)}


@router.post("/api/autoplay/check-live")
async def autoplay_check_live(body: dict, request: Request):
    """Đọc trạng thái THẬT của profile rồi cập nhật lại accounts.json.

    Body: {"profiles": ["Account 01", ...], "ep_ws": false}
          — `profiles` bỏ trống = kiểm tra tất cả.

    KHÔNG mở Chrome. Thứ tự nguồn: trang đang mở (nếu profile đã bật) -> Extension
    Hub -> WebSocket bằng token đã lưu. Đường WebSocket là cách đọc được số dư và
    tên in-game của profile đang ĐÓNG; nó xác thực bằng token trong kho rồi đọc
    khung `cmd 100`.

    `ep_ws=true` ép dùng WebSocket cả khi profile đang mở. Mặc định tắt: phiên WS
    thứ hai song song với trình duyệt cùng account có thể đá phiên kia ra.

    Ghi lại vào `character_name` / `uid` / `balance`.

    Cơ chế ghép bàn xác minh đồng đội bằng cách khớp `dn` với `character_name`,
    nên trường đó cũ hoặc thiếu là ghép bàn hỏng — hoặc khớp nhầm sang TÊN ĐĂNG
    NHẬP (hai tên chỉ khác một ký tự), dẫn tới ngồi xả bài với khách lạ.
    """
    names = body.get("profiles") or body.get("profile_names") or None
    if isinstance(names, str):
        names = [names]
    adapter = _active_adapter(request)
    hub = getattr(request.app.state, "ext_hub", None)
    return await check_live(adapter, hub, names, ep_ws=bool(body.get("ep_ws")))


@router.get("/api/autoplay/profile-info")
async def autoplay_profile_info(request: Request):
    """Thông tin sống của MỘT profile: tên in-game, số dư, bàn đang ngồi.

    Bản trước SUY ĐOÁN danh tính theo việc tên profile có chứa chữ "2"
    (`is_acc2 = "2" in name.lower()`) rồi trả về SỐ DƯ HARDCODE (77607 / 57377).
    Đó là giàn giáo thử nghiệm còn sót: sai account là chuyện thường, và số dư
    hiển thị không liên quan gì tới thực tế. Nay đọc thẳng từ trang/Hub, không
    có thì báo không có.
    """
    name = (request.query_params.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")

    adapter = _active_adapter(request)
    hub = getattr(request.app.state, "ext_hub", None)
    accounts = load_accounts()
    acc = next((a for a in accounts
                if (a.get("name") or "").strip().lower() == name.lower()), None)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"Không có account tên {name}")

    live = await check_one_profile(adapter, hub, acc)

    room_text = "Ở sảnh (Chưa vào bàn)"
    bet_text = "--"
    rep = _REPORTED_ROOMS.get((name or "").lower())
    if not rep and live.get("ten_in_game"):
        rep = _REPORTED_ROOMS.get(live["ten_in_game"].lower())
    if rep and rep.get("rid"):
        room_text = rep.get("rn") or f"Bàn #{rep['rid']}"
        bet_text = f"${int(rep['b']):,}" if rep.get("b") else "--"

    return {
        "ok": True,
        "profile": acc.get("name"),
        "user": acc.get("username"),          # tên ĐĂNG NHẬP
        "dn": live.get("ten_in_game"),        # tên IN-GAME (khoá xác minh)
        "gold": live.get("so_du"),
        "mo": live.get("mo"),
        "dang_nhap": live.get("dang_nhap"),
        "loi": live.get("loi"),
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
        diag["captured_urls"] = await eval_page(page, "() => Object.keys(window.__ws_map || {})")
        diag["instances"] = await eval_page(page, "() => (window.__ws_instances || []).map(s => (s && s.url) || '').slice(0, 8)")
    except Exception as e:
        diag["captured_err"] = str(e)[:100]
    return {"profile": name, "diag": diag}

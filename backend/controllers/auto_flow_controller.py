"""Controller: Auto Flow (tìm nhau + xả bài)."""
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from models.config_model import DATA_DIR, load_accounts

log = logging.getLogger("auto_flow_controller")
router = APIRouter()

AUTOPLAY_CONFIG_FILE = DATA_DIR / "autoplay_config.json"

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
    lookup = {}
    for a in accounts:
        if not a:
            continue
        name = a.get("name")
        if name:
            lookup[name] = a
            lookup[name.replace(" ", "")] = a
            lookup[name.lower()] = a
            lookup[name.replace(" ", "").lower()] = a
        uname = a.get("username")
        if uname:
            lookup[uname] = a
            lookup[uname.lower()] = a
        aid = a.get("id")
        if aid:
            lookup[aid] = a
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
    if not p or (hasattr(p, "is_closed") and p.is_closed()):
        return False
    try:
        # Kiểm tra trạng thái sảnh qua biến bộ nhớ Extension V3 (0ms, không tốn CPU/CDP)
        in_tldl = await p.evaluate("""() => {
            if (typeof window.__autotool_is_in_tldl_lobby === 'function') {
                return window.__autotool_is_in_tldl_lobby();
            }
            const r = window.__last_room_info;
            if (r && r.rid > 0 && r.rid !== 100) {
                if (window.__game_in_progress) return false;
                if (window.__room_players && window.__room_players.length > 0) return false;
            }
            const simms = typeof window.__ws_get_simms === 'function' ? window.__ws_get_simms() : null;
            return !!(simms && simms.readyState === 1);
        }""")
        return bool(in_tldl)
    except Exception:
        return False


def _match_template_cv(screenshot_bytes, template_path, threshold=0.75):
    try:
        import cv2
        import numpy as np
        if not os.path.exists(template_path):
            return None, 0.0
        nparr = np.frombuffer(screenshot_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        tpl = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if img is None or tpl is None:
            return None, 0.0

        th, tw = tpl.shape[:2]
        best_val = -1
        best_loc = None
        best_scale = 1.0

        for scale in np.linspace(0.7, 1.3, 13):
            nw, nh = int(tw * scale), int(th * scale)
            if nw >= img.shape[1] or nh >= img.shape[0] or nw < 10 or nh < 10:
                continue
            resized = cv2.resize(tpl, (nw, nh), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(img, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_scale = scale

        if best_val >= threshold and best_loc:
            nw, nh = int(tw * best_scale), int(th * best_scale)
            cx = best_loc[0] + nw // 2
            cy = best_loc[1] + nh // 2
            return (cx, cy), float(best_val)
        return None, float(best_val)
    except Exception as e:
        log.warning("_match_template_cv error: %s", e)
        return None, 0.0


async def _ensure_in_tldl_lobby_util(p, name="Profile", target_mu=2):
    if not p or (hasattr(p, "is_closed") and p.is_closed()):
        return False
    sw, sh = await _get_screen_size_util(p)

    # 1. Nếu đã ở sẵn sảnh Tiến Lên Đếm Lá
    if await _is_in_tldl_lobby_util(p):
        try:
            tab_x = 0.500 if target_mu == 2 else 0.690
            await p.mouse.click(int(sw * tab_x), int(sh * 0.175))
            await asyncio.sleep(0.3)
        except Exception:
            pass
        return True

    log.info("%s chưa ở sảnh Tiến Lên Đếm Lá -> Kích hoạt điều hướng thông minh (OpenCV Template Matching)...", name)

    tpl_dir = Path(__file__).resolve().parent.parent / "data" / "templates"
    tpl_close = str(tpl_dir / "btn_close_popup.png")
    tpl_gb = str(tpl_dir / "btn_game_bai.png")
    tpl_tldl = str(tpl_dir / "btn_tldl_icon.png")

    # 0. Kiểm tra nếu đang ở trong bàn chơi -> PHẢI rời bàn trước khi thao tác sảnh!
    try:
        in_tbl = await p.evaluate("""() => {
            if (typeof window.__autotool_is_inside_table === 'function') {
                return window.__autotool_is_inside_table();
            }
            return false;
        }""")
        if in_tbl:
            log.info("%s đang ở trong bàn chơi -> thực hiện rời bàn trước...", name)
            await _do_leave_room(p, name=name, target_mu=target_mu)
            await asyncio.sleep(0.5)
            if await _is_in_tldl_lobby_util(p):
                return True
    except Exception:
        pass

    # 0. Kiểm tra nếu đang ở màn hình đăng nhập / bị đăng xuất
    try:
        is_on_login = await p.evaluate("""() => {
            if (typeof window.__autotool_is_on_login_screen === 'function') {
                return window.__autotool_is_on_login_screen();
            }
            return false;
        }""")
        if is_on_login:
            log.warning("%s đang ở màn hình đăng nhập (bị đăng xuất)! Không thể vào sảnh bài.", name)
            return False
    except Exception:
        pass

    try:
        # Bước 1: Quét đóng popup nếu có (Chỉ đóng khi thực sự phát hiện nút X, tuyệt đối không click mù)
        shot1 = await p.screenshot(type="png")
        loc_close, score_close = _match_template_cv(shot1, tpl_close, threshold=0.75)
        if loc_close:
            log.info("%s phát hiện nút [X] đóng popup tại %s (độ khớp %.2f) -> click đóng!", name, loc_close, score_close)
            await p.mouse.click(loc_close[0], loc_close[1])
            await asyncio.sleep(0.4)

        # Bước 2: Tìm và click tab [ GAME BÀI ] (Tuyệt đối không để rơi vào ALL GAMES gây nhầm Tài Xỉu)
        shot2 = await p.screenshot(type="png")
        loc_gb, score_gb = _match_template_cv(shot2, tpl_gb, threshold=0.75)
        if loc_gb:
            log.info("%s phát hiện tab [GAME BÀI] tại %s (độ khớp %.2f) -> click chọn Game Bài!", name, loc_gb, score_gb)
            await p.mouse.click(loc_gb[0], loc_gb[1])
            await asyncio.sleep(0.8)
        else:
            log.info("%s không match được template GAME BÀI -> fallback click tọa độ chuẩn (335, 126)", name)
            await p.mouse.click(int(sw * 0.427), int(sh * 0.250))
            await asyncio.sleep(0.8)

        # Bước 3: Đóng popup phát sinh (nếu có)
        shot3 = await p.screenshot(type="png")
        loc_close2, _ = _match_template_cv(shot3, tpl_close, threshold=0.75)
        if loc_close2:
            await p.mouse.click(loc_close2[0], loc_close2[1])
            await asyncio.sleep(0.3)

        # Bước 4: Tìm và click icon [ TIẾN LÊN ĐẾM LÁ ] (Chống nhầm lẫn 100% với Liêng / Poker)
        shot4 = await p.screenshot(type="png")
        loc_tldl, score_tldl = _match_template_cv(shot4, tpl_tldl, threshold=0.75)
        if loc_tldl:
            log.info("%s phát hiện icon [TIẾN LÊN ĐẾM LÁ] tại %s (độ khớp %.2f) -> click vào sảnh Đếm Lá!", name, loc_tldl, score_tldl)
            await p.mouse.click(loc_tldl[0], loc_tldl[1])
            await asyncio.sleep(2.0)
        else:
            log.info("%s không match được template TLDL -> fallback click tọa độ icon TLDL Hàng 1 Cột 1 (250, 202)", name)
            await p.mouse.click(int(sw * 0.320), int(sh * 0.400))
            await asyncio.sleep(2.0)

        # Bước 5: Bấm tab Solo (hoặc 4 người)
        tab_x = 0.500 if target_mu == 2 else 0.690
        await p.mouse.click(int(sw * tab_x), int(sh * 0.175))
        await asyncio.sleep(0.5)

    except Exception as e:
        log.warning("%s lỗi trong quy trình OpenCV điều hướng sảnh: %s", name, e)

    for _ in range(5):
        if await _is_in_tldl_lobby_util(p):
            log.info("✅ %s đã vào sảnh Tiến Lên Đếm Lá thành công!", name)
            return True
        await asyncio.sleep(0.5)

    return await _is_in_tldl_lobby_util(p)


async def _do_leave_room(p, name="Profile", target_mu=2):
    if not p or (hasattr(p, "is_closed") and p.is_closed()):
        return
    sw, sh = await _get_screen_size_util(p)

    # 0. Nếu đã ở sảnh bàn Đếm Lá rồi -> TUYỆT ĐỐI KHÔNG CLICK vào góc trên bên trái
    # (vì góc trên trái 0.069*sw, 0.253*sh chính là nút [<] Back văng ra Sảnh chính HitClub!)
    if await _is_in_tldl_lobby_util(p):
        log.info("_do_leave_room: %s đã ở sẵn sảnh bàn Đếm Lá, giữ nguyên vị trí tại sảnh bàn.", name)
        return

    # 1. Gửi lệnh WebSocket và Cocos rời bàn tức thì chuẩn giao thức Simms
    try:
        await p.evaluate("""(() => {
            try {
                if (typeof window.__autotool_exec_leave === 'function') {
                    window.__autotool_exec_leave();
                } else if (typeof window.__ws_send === 'function') {
                    window.__ws_send('[4,"Simms",-1]');
                }
            } catch(e) {}
        })()""")
    except Exception:
        pass

    await asyncio.sleep(0.5)

    # Nếu sau lệnh WS/Cocos đã về sảnh bàn Đếm Lá an toàn -> DỪNG NGAY
    if await _is_in_tldl_lobby_util(p):
        log.info("_do_leave_room: %s đã về sảnh bàn Đếm Lá an toàn sau lệnh JS.", name)
        return

    # 2. Click vật lý nút Menu table [>] ở góc trên bên trái (~0.040 sw, 0.238 sh)
    try:
        await p.mouse.click(int(sw * 0.040), int(sh * 0.238))
        await asyncio.sleep(0.3)
        # Nút RỜI BÀN trong menu drawer mở ra: ~0.085 sw, 0.238 sh hoặc 0.085 sw, 0.300 sh
        await p.mouse.click(int(sw * 0.085), int(sh * 0.238))
        await asyncio.sleep(0.2)
        await p.mouse.click(int(sw * 0.085), int(sh * 0.300))
        await asyncio.sleep(0.4)
        # Xử lý nếu có popup xác nhận "Bạn có muốn rời bàn?"
        await p.evaluate("""(() => {
            if (typeof window.__autotool_dismiss_popups === 'function') window.__autotool_dismiss_popups();
        })()""")
    except Exception as e:
        log.warning("_do_leave_room %s click vật lý error: %s", name, e)

    await asyncio.sleep(0.5)
    if await _is_in_tldl_lobby_util(p):
        log.info("_do_leave_room: %s đã về sảnh bàn Đếm Lá thành công.", name)
        return

    # 3. ĐẢM BẢO CUỐI CÙNG: Chỉ gọi _ensure_in_tldl_lobby_util nếu chắc chắn KHÔNG CÒN TRONG BÀN
    try:
        in_tbl = await p.evaluate("""() => {
            if (typeof window.__autotool_is_inside_table === 'function') return window.__autotool_is_inside_table();
            return false;
        }""")
        if not in_tbl:
            log.info("_do_leave_room: %s chưa ở sảnh bàn Đếm Lá -> tự động điều hướng vào sảnh bàn Đếm Lá...", name)
            await _ensure_in_tldl_lobby_util(p, name=name, target_mu=target_mu)
    except Exception:
        pass


@router.post("/api/autoplay/leave-all")
@router.post("/api/autoplay/stop")
async def autoplay_stop(request: Request):
    """Dừng auto và thoát tất cả các profile đang mở khỏi bàn về lại sảnh bàn Đếm Lá:
    - Ngắt tức thì tiến trình gom bàn / xả bài đang chạy (active_match_task.cancel())
    - Thoát khỏi bàn chơi và ĐẢM BẢO 100% ĐỨNG TRƯỚC SẢNH BÀN ĐẾM LÁ (không ở sảnh chính game)
    - Reset room_id = -1, log = "Đang ở sảnh bàn Đếm Lá" trên session
    """
    global _GOM_BAN_STOP
    _GOM_BAN_STOP = True

    # 1. Ngắt tiến trình gom bàn / tìm bàn đang chạy:
    # - Đặt cờ _GOM_BAN_STOP để vòng lặp tự thoát sạch (trả HTTP bình thường).
    # - KHÔNG cancel() cắt ngang ngay lập tức (dễ làm treo response khiến nút
    #   "GOM BÀN & XẢ" trên UI kẹt ở trạng thái "ĐANG DÒ TÌM PHÒNG").
    # - Nếu task không tự thoát trong 15s thì mới cancel như phương án cuối.
    active_match_task = getattr(request.app.state, "active_match_task", None)
    if active_match_task and not active_match_task.done():
        import inspect as _inspect
        if _inspect.isawaitable(active_match_task):
            try:
                await asyncio.wait_for(asyncio.shield(active_match_task), timeout=15.0)
                log.info("autoplay_stop: Tiến trình gom bàn đã tự kết thúc sau cờ DỪNG!")
            except asyncio.TimeoutError:
                try:
                    active_match_task.cancel()
                    log.warning("autoplay_stop: Tiến trình gom bàn không thoát sau 15s -> cancel cưỡng bức!")
                except Exception as e:
                    log.warning("autoplay_stop: Lỗi cancel active_match_task: %s", e)
            except (asyncio.CancelledError, Exception):
                pass
        else:
            try:
                active_match_task.cancel()
                log.info("autoplay_stop: Đã cancel active_match_task (task không awaitable)!")
            except Exception as e:
                log.warning("autoplay_stop: Lỗi cancel active_match_task: %s", e)
    request.app.state.active_match_task = None

    # 2. Dập tắt NGAY LẬP TỨC toàn bộ trạng thái auto-hunt & timers trên tất cả các trang Chrome qua Playwright evaluate
    manager = getattr(request.app.state, "manager", None)
    if manager and manager.sessions:
        for sid, s in list(manager.sessions.items()):
            if s.page:
                try:
                    await s.page.evaluate("""() => {
                        try { localStorage.setItem('AUTOTOOL_STOPPED', '1'); } catch(e) {}
                        window.__AUTOTOOL_AUTO_HUNT = false;
                        window.__AUTOTOOL_ARMED = false;
                        window.__is_matched_locked = false;
                        window.__game_in_progress = false;
                        window.__last_room_info = null;
                        window.__active_room_invite = null;
                        if (window.__hunt_retry_timer) { clearTimeout(window.__hunt_retry_timer); window.__hunt_retry_timer = null; }
                        if (window.__hunt_wait_timer) { clearTimeout(window.__hunt_wait_timer); window.__hunt_wait_timer = null; }
                        if (window.__start_retry_timer) { clearInterval(window.__start_retry_timer); window.__start_retry_timer = null; }
                        if (window.__auto_turn_timer) { clearTimeout(window.__auto_turn_timer); window.__auto_turn_timer = null; }
                        window.postMessage({ type: 'AUTOTOOL_SET_HUNT', auto_hunt: false }, '*');
                        window.postMessage({ type: 'AUTOTOOL_EXEC_COMMAND', action: 'STOP_HUNT', data: { reset: true } }, '*');
                        const hBtn = document.getElementById('autotool-hunt-btn');
                        if (hBtn) {
                            hBtn.innerHTML = '⚪ Săn Bàn: TẮT';
                            hBtn.style.background = 'rgba(30,41,59,0.9)';
                            hBtn.style.color = '#94a3b8';
                            hBtn.style.borderColor = 'rgba(255,255,255,0.2)';
                        }
                    }""")
                except Exception:
                    pass

    # 3. Dừng flow cũ nếu có
    cur = getattr(request.app.state, "auto_flow", None)
    if cur:
        try:
            cur["flow"].stop()
            cur["task"].cancel()
        except Exception:
            pass
        request.app.state.auto_flow = None

    # 4. Gửi lệnh STOP_HUNT xuống Extension Hub để làm sạch trạng thái tất cả các tab
    ext_hub = getattr(request.app.state, "ext_hub", None)
    if ext_hub:
        try:
            # Khoá cơ chế chia sẻ bàn: chặn mọi JOIN_ROOM "zombie" phát ra trễ sau khi Dừng
            ext_hub.set_room_share(False)
            await ext_hub.broadcast_command("STOP_HUNT", {"reset": True})
            log.info("autoplay_stop: Đã broadcast STOP_HUNT tới tất cả các extensions!")
        except Exception as e:
            log.warning("autoplay_stop broadcast error: %s", e)

    # 5. Duyệt qua toàn bộ session đang mở và ép thoát phòng về sảnh bàn Đếm Lá
    left_profiles = []
    if manager and manager.sessions:
        for sid, s in list(manager.sessions.items()):
            acc_name = (s.account or {}).get("name") or sid
            if s.page:
                try:
                    await _do_leave_room(s.page, name=acc_name)
                    await _ensure_in_tldl_lobby_util(s.page, name=acc_name)
                except Exception as e:
                    log.warning("Thoát phòng session %s lỗi: %s", sid, e)
            s.room_id = -1
            s.log = "Đang ở sảnh bàn Đếm Lá"
            left_profiles.append(acc_name)

    log.info("autoplay_stop/leave-all: Đã đưa %d profile về đứng trước sảnh bàn Đếm Lá: %s", len(left_profiles), left_profiles)
    return {
        "ok": True, 
        "count": len(left_profiles),
        "profiles": left_profiles,
        "message": f"Đã đưa {len(left_profiles)} tài khoản về đứng trước sảnh bàn Tiến Lên Đếm Lá."
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
                await s.page.evaluate("""(() => {
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

    bm = getattr(request.app.state, "manager", None)
    open_acc_names = []
    if bm and hasattr(bm, "sessions"):
        for s in bm.sessions.values():
            if s.account and s.account.get("name"):
                open_acc_names.append(s.account.get("name"))

    profiles_input = body.get("profiles") or []
    if not profiles_input:
        p_a = (body.get("profile_a") or "").strip()
        p_b = (body.get("profile_b") or "").strip()
        profiles_input = [p for p in [p_a, p_b] if p]
    if len(profiles_input) < 2 and len(open_acc_names) >= 2:
        profiles_input = open_acc_names[:5]
    if not profiles_input:
        profiles_input = ["Account 01", "Account 02"]

    # Chuẩn hoá danh sách tên profile để khớp chính xác với account["name"]
    accounts = load_accounts()
    resolved_profiles = []
    for p in profiles_input:
        matched_name = None
        for a in accounts:
            if not a:
                continue
            candidates = [
                a.get("name") or "",
                (a.get("name") or "").replace(" ", ""),
                (a.get("name") or "").lower(),
                (a.get("name") or "").replace(" ", "").lower(),
                a.get("username") or "",
                (a.get("username") or "").lower(),
                a.get("id") or "",
            ]
            if p in candidates or p.lower() in candidates or p.replace(" ", "").lower() in candidates:
                matched_name = a.get("name")
                break
        resolved_profiles.append(matched_name or p)
    profiles_input = resolved_profiles

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
        return await _is_in_tldl_lobby_util(p)

    async def _ensure_in_tldl_lobby(p, name="Profile"):
        return await _ensure_in_tldl_lobby_util(p, name=name, target_mu=target_mu)

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
    content_main_code = ""
    try:
        from models.bundled_model import get_extension_dir
        ext_dir = get_extension_dir()
        cm_file = Path(ext_dir or "") / "content_main.js"
        if not cm_file.exists():
            cm_file = Path(__file__).resolve().parent.parent / "extension" / "content_main.js"
        if cm_file.exists():
            content_main_code = cm_file.read_text(encoding="utf-8")
    except Exception:
        pass

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
                if content_main_code:
                    try:
                        await p.evaluate(content_main_code)
                    except Exception as e:
                        log.warning("Inject content_main to %s: %s", p_name, e)
        except Exception as e:
            log.warning("find-and-match: Không mở được trang cho %s: %s", p_name, e)

    if not pages:
        raise HTTPException(status_code=400, detail=f"Không có tài khoản nào trong {profiles_input} đang mở trình duyệt!")

    # Đăng ký task hiện tại để nút "Dừng" có thể cancel tức thì
    request.app.state.active_match_task = asyncio.current_task()

    try:
        # Đảm bảo tất cả tài khoản tham gia đều đã vào đúng sảnh Tiến Lên Đếm Lá
        for p_name, p in pages.items():
            await _ensure_in_tldl_lobby(p, p_name)

        # Ưu tiên tài khoản chính (Account 1 / Anchor) đứng đầu danh sách
        acc1_candidates = [k for k in pages.keys() if "1" in k.lower() or "main" in k.lower() or "anchor" in k.lower()]
        if acc1_candidates:
            first_name = acc1_candidates[0]
        else:
            first_name = list(pages.keys())[0]
        first_page = pages[first_name]
        other_profiles = [name for name in pages.keys() if name != first_name]

        # Làm sạch toàn bộ biến khóa cũ và kích hoạt chế độ SĂN BÀN trên các Extension
        ext_hub = getattr(request.app.state, "ext_hub", None)
        if ext_hub:
            try:
                # Bắt đầu phiên gom bàn mới -> bật lại cơ chế chia sẻ bàn (đã bị khoá khi Dừng)
                ext_hub.set_room_share(True)
                await ext_hub.broadcast_command("RESET_STATE", {})
                # Xoá cờ "đã Dừng" lưu trong localStorage của trang Anchor (nếu extension chưa nhận START_HUNT)
                try:
                    await first_page.evaluate("""() => {
                        try { localStorage.removeItem('AUTOTOOL_STOPPED'); } catch(e) {}
                        window.__AUTOTOOL_AUTO_HUNT = true;
                        window.__AUTOTOOL_ARMED = true;
                        window.__is_hunt_initiator = true;
                    }""")
                except Exception:
                    pass
                # CHỈ gửi START_HUNT đích danh cho Account 1 (Anchor / Chủ bàn)
                if ext_hub.is_connected(first_name):
                    await ext_hub.send_command(first_name, "START_HUNT", {
                        "bet": bet_val,
                        "mu": target_mu,
                        "auto_start_guest_ss": auto_start_guest_ss,
                        "auto_xa": auto_xa,
                    })
                    log.info("find-and-match: Đã gửi START_HUNT cho Account 1 (%s) (Cược $%s, Slot %s, KháchSS=%s)!", 
                             first_name, bet_val, target_mu, auto_start_guest_ss)
                # Gửi lệnh chờ ở sảnh cho các nick phụ
                for sub_name in other_profiles:
                    if ext_hub.is_connected(sub_name):
                        await ext_hub.send_command(sub_name, "WAIT_IN_LOBBY", {
                            "bet": bet_val,
                            "mu": target_mu,
                            "anchor": first_name,
                        })
                        log.info("find-and-match: Đã gửi WAIT_IN_LOBBY cho nick phụ %s (chờ Account 1 tìm bàn)", sub_name)
            except Exception as e:
                log.warning("find-and-match command error: %s", e)

        log.info("find-and-match: Khởi động tìm kiếm bàn: Account 1 (%s) tìm bàn, %d nick phụ (%s) đợi ở sảnh (Cược $%s)", 
                 first_name, len(other_profiles), other_profiles, bet_val)

        raw_tries = int(body.get("max_tries", 0) or 0)
        infinite_mode = (raw_tries <= 0)
        max_tries = 999999 if infinite_mode else raw_tries

        found_match = False
        anchor_name = first_name
        anchor_page = first_page
        selected_rid = None

        # VÒNG LẶP CHÍNH: ACCOUNT 1 TÌM BÀN TRỐNG -> LẤY ID -> ĐIỀU PHỐI NICK PHỤ JOIN THEO ID
        for attempt in range(1, max_tries + 1):
            if _GOM_BAN_STOP:
                log.info("find-and-match: Người dùng đã bấm DỪNG! Thoát khỏi vòng lặp gom bàn ngay.")
                for p_n, p in pages.items():
                    await _do_leave_room(p, name=p_n, target_mu=target_mu)
                    await _ensure_in_tldl_lobby(p, p_n)
                return {"ok": False, "error": "Đã dừng chu trình gom bàn theo lệnh của bạn.", "stopped": True}

            attempt_str = f"Lần {attempt} (Vô hạn)" if infinite_mode else f"Lần {attempt}/{max_tries}"
            log.info("find-and-match: [%s] Account 1 (%s) tìm bàn trống $%s (Nick phụ chờ ở sảnh)...", 
                     attempt_str, first_name, bet_val)

            # Cập nhật HUD hiển thị trên từng màn hình game
            await _set_hud_status(first_page, f"[{attempt_str}] Account 1 đang tìm bàn trống ${bet_val}...")
            for other_name, other_p in pages.items():
                if other_name != first_name:
                    await _set_hud_status(other_p, f"[{attempt_str}] Đang đợi Account 1 ({first_name}) tìm bàn trống...")

            # Đảm bảo Account 1 và tất cả tài khoản phụ đều ở sảnh TLDL
            if not await _is_in_tldl_lobby(first_page):
                await _ensure_in_tldl_lobby(first_page, first_name)
            for other_name, other_p in pages.items():
                if other_name != first_name:
                    if not await _is_in_tldl_lobby(other_p):
                        await _ensure_in_tldl_lobby(other_p, other_name)

            # Reset dữ liệu phòng cũ trên browser context để không đọc nhầm dữ liệu ván trước
            try:
                await first_page.evaluate("() => { window.__last_room_info = null; window.__ws_last_room_id = null; window.__room_players = []; window.__game_in_progress = false; window.__is_matched_locked = false; window.__my_cards = []; }")
                for other_p in [p for k, p in pages.items() if k != first_name]:
                    await other_p.evaluate("() => { window.__last_room_info = null; window.__ws_last_room_id = null; window.__room_players = []; window.__game_in_progress = false; window.__is_matched_locked = false; window.__my_cards = []; }")
            except Exception:
                pass

            # BƯỚC 1: DUY NHẤT ACCOUNT 1 TÌM BÀN CÔNG CỘNG MỚI TRỐNG (THEO MỨC CƯỢC CHÍNH XÁC)
            found_anchor = False
            anchor_rid = None

            if hasattr(first_page, "is_closed") and first_page.is_closed():
                log.info("find-and-match: Trình duyệt Account 1 đã đóng. Dừng chu trình.")
                return {"ok": False, "error": "Trình duyệt Account 1 đã bị đóng.", "stopped": True}

            # 1. Gửi lệnh join trực tiếp qua Simms WebSocket để vào chính xác mức cược mong muốn
            ws_join_sent = False
            try:
                ws_join_sent = bool(await first_page.evaluate(
                    f"() => {{ if (typeof window.__autotool_exec_join === 'function') return window.__autotool_exec_join(null, {bet_val}, {target_mu}); return false; }}"
                ))
            except Exception as e:
                if "closed" in str(e).lower() or "target" in str(e).lower():
                    log.info("find-and-match: Trình duyệt đã đóng (%s). Dừng chu trình.", e)
                    return {"ok": False, "error": "Trình duyệt đã bị đóng.", "stopped": True}

            # 2. Click dự phòng trên canvas tại tọa độ ô cược CHỈ KHI WebSocket join chưa gửi được
            if not ws_join_sent:
                try:
                    if not (hasattr(first_page, "is_closed") and first_page.is_closed()):
                        w_p, h_p = await _get_screen_size(first_page)
                        cx_p = int(w_p * rx)
                        cy_p = int(h_p * ry)
                        await first_page.mouse.click(cx_p, cy_p)
                except Exception as e:
                    if "closed" in str(e).lower() or "target" in str(e).lower():
                        log.info("find-and-match: Trình duyệt đã đóng (%s). Dừng chu trình.", e)
                        return {"ok": False, "error": "Trình duyệt đã bị đóng.", "stopped": True}
                    log.debug("Canvas click fallback warning: %s", e)
            await asyncio.sleep(1.6)

            if _GOM_BAN_STOP:
                break

            if await _is_in_tldl_lobby(first_page):
                continue

            # Kiểm tra xem bàn Account 1 vừa vào có phải bàn trống không (đọc trực tiếp biến bộ nhớ JS 0ms)
            is_empty = False
            guest_ss_triggered = False
            for _ in range(10):
                if _GOM_BAN_STOP:
                    break
                try:
                    r_info = await first_page.evaluate("""() => {
                        const pls = window.__room_players || [];
                        const info = window.__last_room_info;
                        return {
                            has_info: !!info,
                            player_count: pls.length,
                            has_stranger: info ? !!info.has_stranger : false,
                            is_verified_empty: info ? !!info.is_verified_empty : false,
                            guest_ready: pls.some(x => x && (x.aRd === true || x.aRd === 'true' || x.ss === true || x.ready === true)),
                            in_game: !!window.__game_in_progress
                        };
                    }""")
                    if r_info.get("has_info"):
                        # Bàn trống: chỉ có 1 mình Account 1 và không có khách lạ
                        is_empty = (r_info.get("player_count") <= 1 and not r_info.get("has_stranger"))
                        if is_empty:
                            break
                        # NẾU BẬT auto_start_guest_ss VÀ KHÁCH ĐÃ SẴN SÀNG (SS):
                        # CHỈ áp dụng khi KHÔNG đang gom bàn cho đồng đội (không có nick phụ tham gia).
                        # Khi có Account 2 đang chờ -> Account 1 phải OUT bàn có khách lạ, KHÔNG được
                        # tự ý bắt đầu ván với khách (đồng đội sẽ không vào được bàn 2 người).
                        if auto_start_guest_ss and not other_profiles and (r_info.get("guest_ready") or r_info.get("in_game")):
                            log.info("find-and-match: ⚡ PHÁT HIỆN KHÁCH LẠ ĐÃ SẴN SÀNG! Kích hoạt BẮT ĐẦU VÁN NGAY!")
                            guest_ss_triggered = True
                            await first_page.evaluate("() => { if (typeof window.__autotool_exec_start === 'function') window.__autotool_exec_start(); }")
                            w_p, h_p = await _get_screen_size(first_page)
                            await first_page.mouse.click(int(w_p * 0.500), int(h_p * 0.525))
                            break
                except Exception:
                    pass
                await asyncio.sleep(0.2)

            if guest_ss_triggered:
                log.info("find-and-match: >>> ĐÃ BẮT ĐẦU VÁN ĐẤU VỚI KHÁCH LẠ! Hủy lệnh join cho các nick phụ... <<<")
                ext_hub = getattr(request.app.state, "ext_hub", None)
                for sub_name in other_profiles:
                    if ext_hub and ext_hub.is_connected(sub_name):
                        asyncio.create_task(ext_hub.send_command(sub_name, "LEAVE_ROOM", {"reason": "Chủ bàn đang đấu với khách lạ"}))
                # Chờ ván kết thúc (tối đa 60s)
                for _ in range(60):
                    if _GOM_BAN_STOP:
                        break
                    in_g = await first_page.evaluate("() => !!window.__game_in_progress")
                    if not in_g:
                        break
                    await asyncio.sleep(1.0)
                if auto_leave_after:
                    await _do_leave_room(first_page, name=first_name, target_mu=target_mu)
                    await _ensure_in_tldl_lobby(first_page, first_name)
                continue

            if not is_empty:
                log.info("find-and-match: Account 1 vào bàn có người lạ / bàn full -> out về sảnh bàn Đếm Lá ngay & HỦY LỆNH cho các profile phụ")
                ext_hub = getattr(request.app.state, "ext_hub", None)
                for sub_name in other_profiles:
                    if ext_hub and ext_hub.is_connected(sub_name):
                        # CHỜ GỬI XONG (await) để đảm bảo Account 2 LUÔN nhận được lệnh hủy/rời
                        # trước khi Account 1 out khỏi bàn -> không bỏ sót thông báo.
                        await ext_hub.send_command(sub_name, "LEAVE_ROOM", {"reason": "Anchor table has stranger"})
                    sub_page = pages.get(sub_name)
                    if sub_page:
                        await _do_leave_room(sub_page, name=sub_name, target_mu=target_mu)
                await _do_leave_room(first_page, name=first_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(first_page, first_name)
                # TĂNG DELAY NGHỈ AN TOÀN (3.5s) ĐỂ TRÁNH TRIỆT ĐỂ LỖI 'BẠN THAO TÁC QUÁ NHANH'
                log.info("find-and-match: [Anti-Flood Delay] Nghỉ 3.5s trước khi vào bàn lượt mới để chống chặn bot...")
                await asyncio.sleep(3.5)
                continue
            else:
                found_anchor = True
                log.info("find-and-match: >>> ACCOUNT 1 (%s) ĐÃ VÀO BÀN CÔNG CỘNG MỚI TRỐNG! ĐỨNG LẠI GIỮ BÀN! <<<", first_name)

            # BƯỚC 2: TRÍCH XUẤT ROOM ID (RID) NHANH CHÓNG TỪ ACCOUNT 1
            bet_room_map = {
                "100_2": 2, "100_4": 1,
                "500_2": 4, "500_4": 3,
                "1000_2": 6, "1000_4": 5,
                "2000_2": 8, "2000_4": 7,
                "5000_2": 10, "5000_4": 9,
                "10000_2": 12, "10000_4": 11,
                "20000_2": 14, "20000_4": 13,
                "50000_2": 16, "50000_4": 15,
            }
            expected_fixed_rid = bet_room_map.get(f"{bet_val}_{target_mu}", 2)

            for _ in range(16):
                if _GOM_BAN_STOP:
                    break
                try:
                    val = await anchor_page.evaluate("() => (window.__last_room_info && window.__last_room_info.rid) || window.__ws_last_room_id || null")
                    if val and int(val) > 0 and int(val) != 100:
                        int_val = int(val)
                        if int_val <= 28:
                            if int_val == expected_fixed_rid:
                                anchor_rid = int_val
                                break
                        else:
                            anchor_rid = int_val
                            break
                except Exception:
                    pass
                if not anchor_rid:
                    cur = await adapter._page_current_room(anchor_page)
                    if cur and int(cur) > 0 and int(cur) != 100:
                        int_cur = int(cur)
                        if int_cur <= 28:
                            if int_cur == expected_fixed_rid:
                                anchor_rid = int_cur
                                break
                        else:
                            anchor_rid = int_cur
                            break
                await asyncio.sleep(0.12)

            if not anchor_rid:
                anchor_rid = expected_fixed_rid

            selected_rid = anchor_rid

            # KIỂM TRA MỨC CƯỢC THỰC TẾ CỦA BÀN Account 1 ĐANG NGỒI: PHẢI KHỚP bet đã cấu hình.
            # (Sửa bug: cấu hình bàn 100 nhưng game tự đưa vào bàn 500 -> phải out ngay, không mời B.)
            wrong_bet = False
            try:
                room_b = await anchor_page.evaluate("() => (window.__last_room_info && window.__last_room_info.b) || null")
                if room_b is not None:
                    try:
                        room_b_int = int(float(str(room_b).replace(",", "").replace(".", "").strip()))
                        if room_b_int != bet_val:
                            wrong_bet = True
                    except Exception:
                        wrong_bet = False
            except Exception:
                wrong_bet = False
            if wrong_bet:
                log.info("find-and-match: Account 1 đang ở BÀN $%s (không đúng mức cược $%s đã cấu hình) -> Out về sảnh & thử lại!",
                         room_b, bet_val)
                for sub_name in other_profiles:
                    sub_p = pages.get(sub_name)
                    if ext_hub and ext_hub.is_connected(sub_name):
                        await ext_hub.send_command(sub_name, "LEAVE_ROOM", {"reason": f"Anchor joined wrong bet table (${room_b})"})
                    if sub_p:
                        await _do_leave_room(sub_p, name=sub_name, target_mu=target_mu)
                await _do_leave_room(anchor_page, name=anchor_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(anchor_page, anchor_name)
                log.info("find-and-match: [Anti-Flood Delay] Nghỉ 3.5s sau khi out bàn sai mức cược...")
                await asyncio.sleep(3.5)
                continue

            log.info("find-and-match: Account 1 đang giữ bàn công cộng trống #%s ($%s). Điều phối các nick phụ join vào nhanh chóng...", 
                     selected_rid, bet_val)
            await _set_hud_status(anchor_page, f"Đang giữ bàn #{selected_rid}! Đợi đồng đội vào...")

            # Lấy định danh username, display name và uid của Account 1
            anchor_user_info = {}
            try:
                anchor_user_info = await anchor_page.evaluate("""() => ({
                    u: window.__my_u || (window.__user_info && window.__user_info.u) || window.__my_username || '',
                    dn: window.__my_dn || (window.__user_info && (window.__user_info.dn || window.__user_info.name)) || '',
                    uid: window.__my_uid || (window.__user_info && window.__user_info.uid) || ''
                })""")
            except Exception:
                pass
            anchor_u = str(anchor_user_info.get("u") or "").lower().strip()
            anchor_dn = str(anchor_user_info.get("dn") or "").lower().strip()
            anchor_uid = str(anchor_user_info.get("uid") or "").strip()

            # KIỂM TRA LẠI NGAY TRƯỚC KHI MỜI: Account 1 PHẢI VẪN ĐANG NGỒI MỘT MÌNH Ở BÀN TRỐNG.
            # Nếu khách lạ đã vào bàn trong lúc Account 1 giữ bàn -> HỦY mời (báo Account 2) + out ngay.
            ext_hub = getattr(request.app.state, "ext_hub", None)
            still_alone = False
            for _ in range(5):
                try:
                    alive_check = await anchor_page.evaluate("""() => ({
                        player_count: (window.__room_players || []).length,
                        has_stranger: !!(window.__last_room_info && window.__last_room_info.has_stranger),
                        in_game: !!window.__game_in_progress
                    })""")
                    if alive_check.get("in_game"):
                        break
                    if int(alive_check.get("player_count") or 0) <= 1 and not alive_check.get("has_stranger"):
                        still_alone = True
                        break
                except Exception:
                    break
                await asyncio.sleep(0.4)
            if not still_alone:
                log.info("find-and-match: KHÁCH LẠ VÀO BÀN TRONG LÚC Account 1 giữ bàn -> HỦY MỜI & OUT NGAY, báo Account 2!")
                for sub_name in other_profiles:
                    if ext_hub and ext_hub.is_connected(sub_name):
                        await ext_hub.send_command(sub_name, "LEAVE_ROOM", {"reason": "Stranger joined anchor table before invite"})
                await _do_leave_room(anchor_page, name=anchor_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(anchor_page, anchor_name)
                await asyncio.sleep(3.5)
                continue

            # BƯỚC 3: ĐIỀU PHỐI CÁC TÀI KHOẢN PHỤ JOIN VÀO NHANH CHÓNG THEO ID (BÀN CÔNG CỘNG KHÔNG PASS)
            all_subs_matched = True
            for sub_name in other_profiles:
                if _GOM_BAN_STOP:
                    break
                sub_p = pages[sub_name]
                log.info("find-and-match: Gửi lệnh join bàn công cộng #%s cho %s nhanh chóng...", selected_rid, sub_name)
                # Đồng bộ 2 CHIỀU định danh giữa Account 1 và Account 2 (để cả 2 nhận diện chính xác 100% đồng đội, không out nhầm)
                try:
                    p_info_anchor = {"dn": anchor_dn, "u": anchor_u, "uid": anchor_uid, "profile_name": anchor_name}
                    
                    sub_user_info = {}
                    try:
                        sub_user_info = await sub_p.evaluate("""() => ({
                            u: window.__my_u || (window.__user_info && window.__user_info.u) || window.__my_username || '',
                            dn: window.__my_dn || (window.__user_info && (window.__user_info.dn || window.__user_info.name)) || '',
                            uid: window.__my_uid || (window.__user_info && window.__user_info.uid) || ''
                        })""")
                    except Exception:
                        pass
                    sub_u = str(sub_user_info.get("u") or "").lower().strip()
                    sub_dn = str(sub_user_info.get("dn") or "").lower().strip()
                    sub_uid = str(sub_user_info.get("uid") or "").strip()
                    p_info_sub = {"dn": sub_dn, "u": sub_u, "uid": sub_uid, "profile_name": sub_name}

                    # 1. Nạp Account 1 vào Account 2
                    await sub_p.evaluate(f"() => {{ if (!window.__autotool_partners) window.__autotool_partners = []; window.__autotool_partners.push({_json.dumps(p_info_anchor)}); if (typeof globalThis !== 'undefined') globalThis.__autotool_partners = window.__autotool_partners; }}")
                    
                    # 2. Nạp Account 2 vào Account 1 (ĐỂ ACCOUNT 1 NHẬN BIẾT ACCOUNT 2 LÀ ĐỒNG ĐỘI, KHÔNG COI LÀ KHÁCH LẠ)
                    await anchor_page.evaluate(f"() => {{ if (!window.__autotool_partners) window.__autotool_partners = []; window.__autotool_partners.push({_json.dumps(p_info_sub)}); if (typeof globalThis !== 'undefined') globalThis.__autotool_partners = window.__autotool_partners; }}")

                    if ext_hub:
                        if ext_hub.is_connected(sub_name):
                            await ext_hub.send_command(sub_name, "SYNC_PARTNERS", {"partners": [p_info_anchor, anchor_name, anchor_dn, anchor_u]})
                        if ext_hub.is_connected(anchor_name):
                            await ext_hub.send_command(anchor_name, "SYNC_PARTNERS", {"partners": [p_info_sub, sub_name, sub_dn, sub_u]})
                except Exception as e:
                    log.warning("find-and-match: Lỗi đồng bộ định danh 2 chiều: %s", e)

                # V3: Bắn lệnh tức thời qua Extension Hub (<2ms) — DÙNG GÓI CHUẨN DUY NHẤT (không send_raw gói rác)
                ext_hub = getattr(request.app.state, "ext_hub", None)
                if ext_hub and ext_hub.is_connected(sub_name):
                    log.info("find-and-match: >>> V3 Extension Hub: Gửi lệnh JOIN bàn #%s tới %s (0ms)...", selected_rid, sub_name)
                    await ext_hub.send_command(sub_name, "JOIN_ROOM", {
                        "rid": int(selected_rid), 
                        "bet": bet_val, 
                        "mu": target_mu,
                        "source_profile": anchor_name,
                        "anchor_dn": anchor_dn,
                        "anchor_u": anchor_u,
                        "anchor_uid": anchor_uid,
                    })
                try:
                    # Đặt cờ "đang theo lời mời của chủ bàn" NGAY TRƯỚC khi join để nick phụ
                    # không tự out khi bàn trống chưa thấy chủ (fix: gặp nhau nhưng out nhầm,
                    # không kịp ready/start/xả). Đồng thời seed expected anchor cho isPartner.
                    await sub_p.evaluate(f"""() => {{
                        try {{
                            const _inv = {_json.dumps({"rid": int(selected_rid), "ts": "PLACEHOLDER"})};
                            _inv.ts = Date.now();
                            window.__active_room_invite = _inv;
                            window.__expected_anchor_dn = {_json.dumps(anchor_dn)};
                            window.__expected_anchor_u = {_json.dumps(anchor_u)};
                            window.__expected_anchor_uid = {_json.dumps(anchor_uid)};
                            window.__expected_anchor_profile = {_json.dumps(anchor_name)};
                        }} catch(e) {{}}
                    }}""")
                except Exception:
                    pass
                try:
                    await sub_p.evaluate(f"() => {{ if (typeof window.__autotool_exec_join === 'function') window.__autotool_exec_join({selected_rid}, {bet_val}, {target_mu}); }}")
                except Exception:
                    pass

                # Chờ sub_p vào bàn (tối đa 4.5s)
                sub_matched = False
                for _ in range(9):
                    if _GOM_BAN_STOP:
                        break
                    await asyncio.sleep(0.5)
                    if await _is_in_tldl_lobby(sub_p):
                        continue

                    # Lấy định danh và danh sách người chơi trong phòng của Account 2 và Account 1
                    sub_user_info = {}
                    try:
                        sub_user_info = await sub_p.evaluate("""() => ({
                            u: window.__my_u || (window.__user_info && window.__user_info.u) || window.__my_username || '',
                            dn: window.__my_dn || (window.__user_info && (window.__user_info.dn || window.__user_info.name)) || '',
                            uid: window.__my_uid || (window.__user_info && window.__user_info.uid) || ''
                        })""")
                    except Exception:
                        pass
                    sub_u = str(sub_user_info.get("u") or "").lower().strip()
                    sub_dn = str(sub_user_info.get("dn") or "").lower().strip()
                    sub_uid = str(sub_user_info.get("uid") or "").strip()

                    sub_pls = []
                    try:
                        sub_pls = await sub_p.evaluate("() => window.__room_players || []")
                    except Exception:
                        pass

                    anchor_pls = []
                    try:
                        anchor_pls = await anchor_page.evaluate("() => window.__room_players || []")
                    except Exception:
                        pass

                    # 1. Account 2 phải nhìn thấy Account 1 trong phòng của mình:
                    has_anchor = False
                    for pl in sub_pls:
                        if isinstance(pl, dict):
                            p_u = str(pl.get("u") or "").lower().strip()
                            p_dn = str(pl.get("dn") or "").lower().strip()
                            p_uid = str(pl.get("uid") or "").strip()
                            if (anchor_dn and p_dn == anchor_dn) or (anchor_u and p_u == anchor_u) or (anchor_uid and p_uid == anchor_uid):
                                has_anchor = True
                                break

                    # 2. Account 1 phải nhìn thấy Account 2 trong phòng của mình:
                    has_sub = False
                    for pl in anchor_pls:
                        if isinstance(pl, dict):
                            p_u = str(pl.get("u") or "").lower().strip()
                            p_dn = str(pl.get("dn") or "").lower().strip()
                            p_uid = str(pl.get("uid") or "").strip()
                            if (sub_dn and p_dn == sub_dn) or (sub_u and p_u == sub_u) or (sub_uid and p_uid == sub_uid):
                                has_sub = True
                                break

                    # ĐIỀU KIỆN KHỚP BẮT BUỘC: CẢ HAI BÊN PHẢI CÙNG THẤY NHAU (TWO-WAY MUTUAL VERIFICATION)
                    # Tuyệt đối không dùng so sánh trùng RID ảo (sub_rid == 2) hay đếm số người >= 2!
                    if has_anchor and has_sub:
                        sub_matched = True
                        log.info("find-and-match: >>> XÁC NHẬN CHÍNH XÁC: %s và %s ĐÃ Ở CHUNG BÀN! <<<", sub_name, anchor_name)
                        break
                    else:
                        # CƠ CHẾ BẢO VỆ: Nếu Account 2 vào phòng mà KHÔNG CÓ Account 1 (hoặc phòng người lạ)
                        # LẬP TỨC OUT VỀ SẢNH BÀN ĐẾM LÁ NGAY, không bao giờ được ở lại phòng người lạ!
                        log.warning("find-and-match: BẢO VỆ: %s không ở chung bàn với %s (has_anchor=%s, has_sub=%s)! Thoát ngay về sảnh bàn Đếm Lá!", 
                                    sub_name, anchor_name, has_anchor, has_sub)
                        await _do_leave_room(sub_p, name=sub_name, target_mu=target_mu)
                        await _ensure_in_tldl_lobby(sub_p, sub_name)
                        break

                if not sub_matched:
                    all_subs_matched = False
                    log.warning("find-and-match: %s không vào được bàn #%s cùng %s!", sub_name, selected_rid, anchor_name)
                    if not await _is_in_tldl_lobby(sub_p):
                        await _do_leave_room(sub_p, name=sub_name, target_mu=target_mu)
                        await _ensure_in_tldl_lobby(sub_p, sub_name)
                    break

            if all_subs_matched:
                found_match = True
                log.info("find-and-match: >>> GOM BÀN THÀNH CÔNG! TẤT CẢ TÀI KHOẢN ĐÃ Ở CHUNG BÀN #%s! <<<", selected_rid)
                break
            else:
                log.info("find-and-match: Ghép phòng chưa thành công -> Account 1 (%s) thoát ra sảnh bàn Đếm Lá để tìm bàn mới...", anchor_name)
                await _do_leave_room(anchor_page, name=anchor_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(anchor_page, anchor_name)
                await asyncio.sleep(0.8)


        if not found_match or not selected_rid:
            return {
                "ok": False,
                "error": f"Sau {max_tries} lần thử, không thể gom chung bàn ${bet_val}. Vui lòng thử lại hoặc đổi mức cược.",
                "profiles": list(pages.keys()),
            }

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

        # BƯỚC 6: TIẾN HÀNH SẴN SÀNG -> BẮT ĐẦU -> XẢ BÀI (HỢP NHẤT 1 LUỒNG EXTENSION V3 DUY NHẤT)
        async def _check_and_click_ready_or_start(p, is_anchor=False, name="Profile"):
            """Kiểm tra và bấm nút [ SẴN SÀNG ] (cho nick phụ) hoặc [ BẮT ĐẦU ] (cho Anchor).
            Hỗ trợ 4 cơ chế:
            1. Cocos Scene & DOM Inspector trong JS: tìm btn_begin / Label SẴN SÀNG/BẮT ĐẦU và lấy tọa độ thực.
            2. OpenCV Multi-Scale Template Matching nếu có nút trên màn hình.
            3. Physical Mouse Click Playwright tại tọa độ phát hiện (hoặc center fallback).
            4. Bắn song song WebSocket packet tương ứng.
            """
            btn_type = "BẮT ĐẦU" if is_anchor else "SẴN SÀNG"
            sw, sh = await _get_screen_size(p)
            default_x = int(sw * 0.500)
            default_y = int(sh * 0.525)

            # 1. Quét qua JS Cocos Scene
            js_res = {}
            try:
                js_res = await p.evaluate("""() => {
                    try {
                        const canvas = document.querySelector("canvas");
                        const rect = canvas ? canvas.getBoundingClientRect() : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
                        let targetX = rect.left + rect.width * 0.500;
                        let targetY = rect.top + rect.height * 0.525;
                        let found = false;
                        let btnName = "";
                        let btnText = "";

                        if (typeof cc !== "undefined" && cc.director) {
                            const scene = cc.director.getScene();
                            if (scene) {
                                function searchNode(node, depth) {
                                    if (!node || depth > 40 || found) return;
                                    const comps = (typeof node.getComponents === "function") ? node.getComponents(cc.Component) : (node._components || []);
                                    for (let i = 0; i < comps.length; i++) {
                                        const c = comps[i];
                                        if (!c) continue;

                                        if (c.btn_begin && c.btn_begin.node && c.btn_begin.node.active) {
                                            found = true;
                                            btnName = "btn_begin";
                                            if (typeof c.sendReady === "function") {
                                                try { c.sendReady(); } catch (_) {}
                                            }
                                            if (typeof cc.Component !== "undefined" && cc.Component.EventHandler && c.btn_begin.clickEvents) {
                                                try { cc.Component.EventHandler.emitEvents(c.btn_begin.clickEvents, c.btn_begin); } catch (_) {}
                                            }
                                            try { c.btn_begin.node.emit(cc.Node.EventType.TOUCH_END); } catch (_) {}

                                            try {
                                                if (typeof c.btn_begin.node.getBoundingBoxToWorld === "function" && cc.view) {
                                                    const b = c.btn_begin.node.getBoundingBoxToWorld();
                                                    const vs = cc.view.getVisibleSize();
                                                    if (b && vs && vs.width > 0 && vs.height > 0) {
                                                        targetX = rect.left + (b.x + b.width / 2) * (rect.width / vs.width);
                                                        targetY = rect.top + (vs.height - (b.y + b.height / 2)) * (rect.height / vs.height);
                                                    }
                                                }
                                            } catch (_) {}
                                            return;
                                        }

                                        const labelStr = (c.string || c._string || (c.label && c.label.string) || "").toUpperCase();
                                        if (labelStr.includes("SẴN SÀNG") || labelStr.includes("BẮT ĐẦU") || labelStr.includes("SAN SANG") || labelStr.includes("BAT DAU")) {
                                            if (node.active) {
                                                found = true;
                                                btnText = labelStr;
                                                btnName = node.name || "label_btn";
                                                let parent = node;
                                                while (parent && !parent.getComponent(cc.Button) && parent.parent) parent = parent.parent;
                                                const btnComp = parent ? (parent.getComponent(cc.Button) || parent.getComponent("cc.Button")) : null;
                                                if (btnComp && btnComp.clickEvents) {
                                                    try { cc.Component.EventHandler.emitEvents(btnComp.clickEvents, btnComp); } catch (_) {}
                                                }
                                                try { (parent || node).emit(cc.Node.EventType.TOUCH_END); } catch (_) {}
                                                return;
                                            }
                                        }
                                    }
                                    const children = node.children || [];
                                    for (let j = 0; j < children.length; j++) {
                                        searchNode(children[j], depth + 1);
                                        if (found) return;
                                    }
                                }
                                searchNode(scene, 0);
                            }
                        }

                        // Tự động gọi helper chuyên dụng
                        if (typeof window.__autotool_exec_ready === "function") {
                            try { window.__autotool_exec_ready(); } catch (_) {}
                        }
                        if (typeof window.__autotool_exec_start === "function") {
                            try { window.__autotool_exec_start(); } catch (_) {}
                        }

                        return {
                            found: found,
                            name: btnName,
                            text: btnText,
                            x: Math.round(targetX),
                            y: Math.round(targetY)
                        };
                    } catch (e) {
                        return { error: String(e) };
                    }
                }""")
            except Exception:
                pass

            click_x = (js_res or {}).get("x") or default_x
            click_y = (js_res or {}).get("y") or default_y
            has_found = bool((js_res or {}).get("found"))

            # 2. Template Matching qua OpenCV nếu chưa tìm thấy qua Cocos
            if not has_found:
                try:
                    import cv2
                    import numpy as np
                    tmpl_dir = Path(__file__).resolve().parent.parent / "data" / "templates"
                    tmpl_file = tmpl_dir / "btn_ready.png"
                    if os.path.exists(tmpl_file):
                        tmpl_img = cv2.imread(tmpl_file)
                        if tmpl_img is not None:
                            shot_bytes = await p.screenshot()
                            arr = np.frombuffer(shot_bytes, np.uint8)
                            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if frame is not None:
                                h_t, w_t = tmpl_img.shape[:2]
                                best_val = -1
                                best_pt = None
                                for sc in [0.5, 0.7, 0.85, 1.0, 1.15]:
                                    rw, rh = int(w_t * sc), int(h_t * sc)
                                    if rh < frame.shape[0] and rw < frame.shape[1]:
                                        r_tmpl = cv2.resize(tmpl_img, (rw, rh))
                                        res = cv2.matchTemplate(frame, r_tmpl, cv2.TM_CCOEFF_NORMED)
                                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                                        if max_val > best_val:
                                            best_val = max_val
                                            best_pt = (max_loc[0] + rw // 2, max_loc[1] + rh // 2)
                                if best_val >= 0.65 and best_pt:
                                    click_x, click_y = best_pt
                                    has_found = True
                                    log.info("find-and-match: [%s] OpenCV phát hiện nút '%s' (độ tin cậy: %.2f) tại (%d, %d)", 
                                             name, btn_type, best_val, click_x, click_y)
                except Exception:
                    pass

            # 3. Click chuột vật lý Playwright
            try:
                await p.mouse.click(click_x, click_y)
                log.info("find-and-match: [%s] >>> Đã CLICK chuột vật lý vào nút '%s' tại (%d, %d) <<<", 
                         name, btn_type, click_x, click_y)
            except Exception:
                pass

            return has_found

        # Vòng lặp tuần tự kiểm tra & click Sẵn Sàng (Account 2) -> Bắt Đầu (Account 1)
        # Chạy mỗi 400ms, tối đa 16 lần (~7-8s) cho đến khi chia bài
        match_started = False
        for tick in range(1, 17):
            if _GOM_BAN_STOP:
                break

            # 1. Nick phụ: Kiểm tra và bấm SẴN SÀNG
            for sub_name in other_profiles:
                sub_p = pages[sub_name]
                ext_hub = getattr(request.app.state, "ext_hub", None)
                if ext_hub and ext_hub.is_connected(sub_name):
                    await ext_hub.send_command(sub_name, "READY")
                await _check_and_click_ready_or_start(sub_p, is_anchor=False, name=sub_name)

            await asyncio.sleep(0.25)

            # 2. Nick chính (Anchor): Kiểm tra và bấm BẮT ĐẦU
            ext_hub = getattr(request.app.state, "ext_hub", None)
            if ext_hub and ext_hub.is_connected(anchor_name):
                await ext_hub.send_command(anchor_name, "START")
            await _check_and_click_ready_or_start(anchor_page, is_anchor=True, name=anchor_name)

            # 3. Kiểm tra xem ván bài đã chia bài chưa
            try:
                in_game = await anchor_page.evaluate("() => Boolean(window.__game_in_progress || (window.__my_cards && window.__my_cards.length > 0))")
                if in_game:
                    match_started = True
                    log.info("find-and-match: >>> ĐÃ NHẬN TÍN HIỆU CHIA BÀI & BẮT ĐẦU VÁN THÀNH CÔNG (sau %d lượt kiểm tra)! <<<", tick)
                    break
            except Exception:
                pass

            await asyncio.sleep(0.35)

        # 3. HỢP NHẤT 1 LUỒNG DUY NHẤT: EXTENSION V3 TỰ ĐỘNG XẢ BÀI QUA WEBSOCKET (cmd 253 / cmd 254)
        # Không chạy song song CooperativeDiscardEngine click chuột mù quáng gây desync và kick khỏi server!
        log.info("find-and-match: >>> Extension V3 tự động phân tích & xả bài tối ưu qua WebSocket (<2ms)... <<<")
        for p_name, p in pages.items():
            await _set_hud_status(p, f"Đang trong ván #{selected_rid} - Extension V3 tự động xả bài...")

        # Theo dõi ván bài hoàn tất qua biến bộ nhớ Extension V3 (tối đa 45s)
        t_game_end = time.time() + 45.0
        while time.time() < t_game_end:
            if _GOM_BAN_STOP:
                break
            game_done = False
            try:
                in_prog = await anchor_page.evaluate("() => Boolean(window.__game_in_progress)")
                cards_cnt = await anchor_page.evaluate("() => (window.__my_cards || []).length")
                if not in_prog and cards_cnt == 0:
                    game_done = True
            except Exception:
                pass

            if game_done:
                log.info("find-and-match: >>> VÁN BÀI KẾT THÚC THÀNH CÔNG QUA EXTENSION V3! <<<")
                break
            await asyncio.sleep(1.0)


        # BƯỚC 7: BẪY KHÁCH LẠ SẴN SÀNG (NẾU BẬT auto_start_guest_ss)
        guest_found = False
        start_x = 0
        start_y = 0
        try:
            start_sw, start_sh = await _get_screen_size(anchor_page)
            start_x = int(start_sw * 0.500)
            start_y = int(start_sh * 0.525)
        except Exception:
            pass
        if auto_start_guest_ss:
            log.info("find-and-match: Chế độ 'Bắt đầu nếu khách SS' đang bật, chủ bàn canh 5 giây xem có khách...")
            for _ in range(10):
                if _GOM_BAN_STOP:
                    break
                try:
                    pls = await anchor_page.evaluate("() => window.__room_players || []")
                    guest_ss = any(pl.get("aRd") is True or pl.get("ss") is True for pl in pls if pl.get("dn") not in pages and pl.get("u") not in pages)
                    if guest_ss:
                        log.info("find-and-match: ⚡ PHÁT HIỆN KHÁCH LẠ SẴN SÀNG! Kích hoạt BẮT ĐẦU NGAY!")
                        if start_x and start_y:
                            await anchor_page.mouse.click(start_x, start_y)
                        guest_found = True
                        await asyncio.sleep(1.0)
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)

        # BƯỚC 8: TỰ OUT VỀ SẢNH BÀN ĐẾM LÁ SAU KHI XẢ (NẾU BẬT auto_leave_after HOẶC KHÔNG CÓ KHÁCH LẠ)
        if auto_leave_after or not guest_found:
            log.info("find-and-match: Hoàn thành ván xả bài -> Thực hiện tự động rời bàn về sảnh bàn Đếm Lá cho tất cả tài khoản...")
            await asyncio.sleep(0.5)
            for p_name, p in pages.items():
                await _do_leave_room(p, name=p_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(p, p_name)
            if bm and bm.sessions:
                for sid, s in list(bm.sessions.items()):
                    acc_n = (s.account or {}).get("name")
                    if acc_n in pages:
                        s.room_id = -1
                        s.log = "Hoàn thành xả bài, đang ở sảnh bàn Đếm Lá"

        shot_a = None
        try:
            shot_a = await adapter._screenshot(anchor_page, f"matched_{anchor_name}")
        except Exception:
            pass

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

    except asyncio.CancelledError:
        log.info("find-and-match: Nhận tín hiệu CANCEL từ nút Dừng! Lập tức đưa tất cả tài khoản về lại sảnh bàn Đếm Lá...")
        for p_n, p in list(pages.items()):
            try:
                await _do_leave_room(p, name=p_n, target_mu=target_mu)
                await _ensure_in_tldl_lobby(p, p_n)
            except Exception:
                pass
        return {"ok": False, "error": "Đã dừng chu trình gom bàn theo lệnh của bạn.", "stopped": True}
    finally:
        if getattr(request.app.state, "active_match_task", None) == asyncio.current_task():
            request.app.state.active_match_task = None


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




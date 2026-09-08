"""Luồng GOM BÀN: tìm bàn trống theo RID cố định rồi ghép nick phụ vào cùng bàn."""
import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from models.config_model import load_accounts

from .constants import BET_RATIOS, FIXED_TABLE_RIDS
from .deps import _build_adapter, _notify_all
from .lobby import (
    _clear_hunt_state,
    _do_leave_room,
    _ensure_in_tldl_lobby_util,
    _is_in_tldl_lobby_util,
)

log = logging.getLogger("auto_flow_controller")
router = APIRouter()


# ---- Luồng WebSocket: Tìm bàn trống 100/500 & Ghép Account 2 ----
@router.post("/api/autoplay/find-and-match-pairs-ws")
async def autoplay_find_and_match_pairs_ws(body: dict, request: Request):
    """Chạy nhiều cặp độc lập song song.

    ``pairs`` là danh sách các cặp [anchor, sub], ví dụ
    [["Account01", "Account02"], ["Account03", "Account04"]]. Mỗi cặp dùng
    một bàn/RID riêng và không đưa profile của cặp khác vào danh sách partner.
    """
    raw_pairs = body.get("pairs") or []
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise HTTPException(status_code=400, detail="Cần truyền pairs, ví dụ [[Account01, Account02], [Account03, Account04]]")
    if len(raw_pairs) > 3:
        raise HTTPException(status_code=400, detail="Tối đa 3 cặp (6 profile) trong một lần chạy")

    pairs = []
    used = set()
    for index, pair in enumerate(raw_pairs, start=1):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise HTTPException(status_code=400, detail=f"Cặp {index} phải gồm đúng Account chính và Account phụ")
        anchor, sub = (str(pair[0] or "").strip(), str(pair[1] or "").strip())
        if not anchor or not sub or anchor == sub:
            raise HTTPException(status_code=400, detail=f"Cặp {index} có profile không hợp lệ hoặc bị trùng")
        if anchor in used or sub in used:
            raise HTTPException(status_code=400, detail="Một profile chỉ được xuất hiện trong một cặp")
        used.update((anchor, sub))
        pairs.append((anchor, sub))

    async def _run_pair(index, anchor, sub):
        pair_body = dict(body)
        pair_body.pop("pairs", None)
        pair_body.update({"profiles": [anchor, sub], "profile_a": anchor, "profile_b": sub})
        try:
            result = await autoplay_find_and_match_ws(pair_body, request)
            return {"pair": index, "anchor": anchor, "sub": sub, **result}
        except HTTPException as e:
            return {"pair": index, "anchor": anchor, "sub": sub, "ok": False, "error": str(e.detail)}
        except Exception as e:
            log.exception("multi-pair %s (%s/%s) failed", index, anchor, sub)
            return {"pair": index, "anchor": anchor, "sub": sub, "ok": False, "error": str(e)}

    results = await asyncio.gather(*[
        _run_pair(index, anchor, sub) for index, (anchor, sub) in enumerate(pairs, start=1)
    ])
    return {"ok": all(item.get("ok") for item in results), "pairs": results}


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
    import json as _json
    import time

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

    # Chuẩn hoá tên profile để khớp chính xác với account["name"].
    # `profile_a` là lựa chọn "Tài khoản chính" từ UI, không được suy đoán
    # lại từ tên có chứa số 1/2.
    accounts = load_accounts()
    def _resolve_profile_name(p):
        p = str(p or "").strip()
        if not p:
            return ""
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
        return matched_name or p

    profiles_input = [_resolve_profile_name(p) for p in profiles_input]
    requested_anchor = _resolve_profile_name(body.get("profile_a"))
    if requested_anchor:
        if requested_anchor not in profiles_input:
            raise HTTPException(
                status_code=400,
                detail=f"Tài khoản chính {requested_anchor} phải nằm trong danh sách profiles đang chạy",
            )
        # Bảo toàn thứ tự còn lại, nhưng account chính luôn đứng đầu.
        profiles_input = [requested_anchor] + [p for p in profiles_input if p != requested_anchor]

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

    bet_val = target_bet if target_bet in BET_RATIOS else 100

    # RID cố định đã xác nhận từ frame cmd=300 của HITCLUB.  Bắt buộc gửi rid
    # trong cmd=308: nếu chỉ gửi b/Mu, server có thể dùng lựa chọn bàn còn lưu
    # trong client và nhảy sang mức $500.
    requested_rid = FIXED_TABLE_RIDS.get(f"{bet_val}_{target_mu}")

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

    # Mỗi cặp giữ token dừng riêng theo epoch. Không reset cờ toàn cục ở đây:
    # reset đó từng khiến pair thứ hai làm pair thứ nhất tự dừng.
    stop_epoch = int(getattr(request.app.state, "gom_ban_stop_epoch", 0))
    run_id = f"gom_{uuid.uuid4().hex[:8]}"

    def _should_stop():
        return int(getattr(request.app.state, "gom_ban_stop_epoch", 0)) != stop_epoch

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
    if profile_a not in pages:
        raise HTTPException(status_code=400, detail=f"Không mở được trình duyệt tài khoản chính {profile_a}")

    # Đăng ký task hiện tại để nút "Dừng" có thể cancel tức thì
    current_match_task = asyncio.current_task()
    active_match_tasks = getattr(request.app.state, "active_match_tasks", None)
    if active_match_tasks is None:
        active_match_tasks = set()
        request.app.state.active_match_tasks = active_match_tasks
    active_match_tasks.add(current_match_task)
    # Giữ field cũ để tương thích các điểm gọi khác; Stop sử dụng cả tập task.
    request.app.state.active_match_task = current_match_task

    try:
        # PRE-FLIGHT BẮT BUỘC: phiên trước có thể còn ngồi trong một bàn sai
        # cược (ví dụ $500). Tắt engine cũ trước khi kiểm tra sảnh để nó không
        # tự join lại, sau đó _prepare_lobby luôn gửi lệnh rời bàn — không dựa
        # vào nhận diện ảnh/scene vốn có thể trượt khi đang ở gameplay.
        preflight_code = f"""() => {{
            window.__AUTOTOOL_AUTO_HUNT = false;
            window.__AUTOTOOL_ARMED = false;
            window.__target_hunt_bet = {bet_val};
            window.__target_hunt_mu = {target_mu};
            if (window.__hunt_retry_timer) {{ clearTimeout(window.__hunt_retry_timer); window.__hunt_retry_timer = null; }}
            if (window.__hunt_wait_timer) {{ clearTimeout(window.__hunt_wait_timer); window.__hunt_wait_timer = null; }}
            if (window.__start_retry_timer) {{ clearInterval(window.__start_retry_timer); window.__start_retry_timer = null; }}
        }}"""
        for p_name, p in pages.items():
            try:
                await p.evaluate(preflight_code)
            except Exception:
                pass

        # Đảm bảo TẤT CẢ tài khoản tham gia (Account chính + nick phụ) đều vào đúng
        # sảnh Tiến Lên Đếm Lá TRƯỚC khi bắt đầu tìm bàn. Điều hướng OpenCV có thể
        # flaky (popup chặn, template match rớt) -> retry nhiều lần trước khi abort,
        # tránh bỏ cuộc quá sớm (lỗi "Không đưa được profile vào sảnh").
        async def _prepare_lobby(p_name, p):
            """Đưa một profile vào sảnh chọn bàn và chỉ xác nhận khi đã vào thật."""
            entered = False
            # Gửi leave một lần ngay cả khi extension không nhìn ra table. Đây
            # là điều kiện cần để thoát bàn $500 còn sót trước khi chọn bàn $100.
            await _do_leave_room(p, name=p_name, target_mu=target_mu)
            await asyncio.sleep(0.7)
            deadline = time.time() + 45.0
            while time.time() < deadline:
                if _should_stop():
                    break
                ok_lobby = await _ensure_in_tldl_lobby(p, p_name)
                if ok_lobby:
                    entered = True
                    break
                log.warning("find-and-match: %s chưa vào được sảnh bàn Đếm Lá -> thử lại...", p_name)
                await asyncio.sleep(1.5)
            return p_name, entered

        # Chuẩn bị toàn bộ account SONG SONG. Không cho Anchor gửi cmd=308 cho
        # tới khi tất cả nick phụ đã xác nhận đang đứng ở đúng sảnh chọn bàn.
        lobby_results = await asyncio.gather(
            *[_prepare_lobby(p_name, p) for p_name, p in pages.items()]
        )
        if _should_stop():
            return {"ok": False, "error": "Đã dừng chu trình gom bàn theo lệnh của bạn.", "stopped": True}
        not_ready = [p_name for p_name, entered in lobby_results if not entered]
        if not_ready:
            err_msg = f"Không đưa được các profile vào sảnh bàn Đếm Lá: {not_ready}"
            log.warning("find-and-match: %s", err_msg)
            await _notify_all(getattr(request.app.state, "ext_hub", None), f"❌ {err_msg}", "error", "❌ Lỗi sảnh")
            return {"ok": False, "error": err_msg, "stopped": False}

        # Anchor duy nhất là profile_a do UI/API chỉ định. Không suy đoán từ
        # tên để tránh đảo chiều: chính phải tìm/giữ bàn, phụ phải lắng nghe.
        first_name = profile_a
        first_page = pages[first_name]
        other_profiles = [name for name in pages.keys() if name != first_name]

        # Làm sạch toàn bộ biến khóa cũ và kích hoạt chế độ SĂN BÀN trên các Extension
        ext_hub = getattr(request.app.state, "ext_hub", None)
        if ext_hub:
            try:
                # CỐ ĐỊNH QUYỀN ĐIỀU PHỐI VỀ CONTROLLER: tắt auto-forward của Hub (Hub
                # forward theo ri.get('b') -> dễ nhầm bàn 100->500). Controller tự gửi
                # JOIN_ROOM chuẩn (bet_val chính xác) cho từng nick phụ.
                ext_hub.set_room_share(False)
                await ext_hub.broadcast_command("RESET_STATE", {})
                # Cấu hình Anchor (Chủ bàn) chạy CHẾ ĐỘ BACKEND-DRIVEN:
                # - TẮT tự săn/self-join (__AUTOTOOL_AUTO_HUNT=false) -> không còn 2 engine
                #   join song song (nguồn gốc lỗi nhầm bàn 100->500 & join zombie sau Dừng).
                # - Vẫn bật auto-xả bài (__AUTOTOOL_AUTO_DISCARD) theo auto_xa để đánh khi tới lượt.
                try:
                    await first_page.evaluate(f"""() => {{
                        try {{ localStorage.removeItem('AUTOTOOL_STOPPED'); }} catch(e) {{}}
                        window.__AUTOTOOL_AUTO_HUNT = false;
                        window.__AUTOTOOL_ARMED = true;
                        window.__AUTOTOOL_MATCH_ROLE = 'anchor';
                        window.__is_hunt_initiator = true;
                        window.__AUTOTOOL_AUTO_DISCARD = {_json.dumps(auto_xa)};
                        window.__auto_start_guest_ss = {_json.dumps(auto_start_guest_ss)};
                        window.__target_hunt_bet = {bet_val};
                        window.__target_hunt_mu = {target_mu};
                    }}""")
                except Exception:
                    pass
                log.info("find-and-match: Đã cấu hình Anchor (%s) chạy backend-driven (Cược $%s, Slot %s, KháchSS=%s, Xả=%s)!",
                         first_name, bet_val, target_mu, auto_start_guest_ss, auto_xa)
                # Gửi lệnh chờ ở sảnh cho các nick phụ + TẮT engine tự săn của phụ
                # (phụ chỉ nhận lệnh JOIN_ROOM/LEAVE_ROOM từ controller, không tự join).
                for sub_name in other_profiles:
                    if ext_hub.is_connected(sub_name):
                        await ext_hub.send_command(sub_name, "WAIT_IN_LOBBY", {
                            "bet": bet_val,
                            "mu": target_mu,
                            "anchor": first_name,
                        })
                        log.info("find-and-match: Đã gửi WAIT_IN_LOBBY cho nick phụ %s (chờ Account 1 tìm bàn)", sub_name)
                    sub_p = pages.get(sub_name)
                    if sub_p:
                        try:
                            await sub_p.evaluate("""() => {
                                window.__AUTOTOOL_AUTO_HUNT = false;
                                window.__AUTOTOOL_ARMED = false;
                                window.__AUTOTOOL_MATCH_ROLE = 'sub';
                                window.__is_hunt_initiator = false;
                            }""")
                        except Exception:
                            pass
            except Exception as e:
                log.warning("find-and-match command error: %s", e)

        # Page state phải được gán kể cả khi Extension Bridge chưa kết nối. Nếu
        # không, nick phụ có thể giữ role mặc định và không tự đánh khi tới lượt.
        try:
            await first_page.evaluate(f"""() => {{
                window.__AUTOTOOL_MATCH_ROLE = 'anchor';
                window.__AUTOTOOL_ROLE = 'winner';
                window.__AUTOTOOL_PARTNER_PROFILES = {_json.dumps(other_profiles)};
                window.__AUTOTOOL_AUTO_DISCARD = {_json.dumps(auto_xa)};
                window.__AUTOTOOL_AUTO_HUNT = false;
            }}""")
            for sub_name in other_profiles:
                sub_page = pages[sub_name]
                await sub_page.evaluate(f"""() => {{
                    window.__AUTOTOOL_MATCH_ROLE = 'sub';
                    window.__AUTOTOOL_ROLE = 'dump';
                    window.__AUTOTOOL_PARTNER_PROFILES = {_json.dumps([first_name])};
                    window.__AUTOTOOL_AUTO_DISCARD = {_json.dumps(auto_xa)};
                    window.__AUTOTOOL_AUTO_HUNT = false;
                    window.__AUTOTOOL_ARMED = false;
                }}""")
        except Exception as e:
            log.warning("find-and-match: Không gán được role/xả bài rõ ràng: %s", e)

        log.info("find-and-match: Khởi động tìm kiếm bàn: Account 1 (%s) tìm bàn, %d nick phụ (%s) đợi ở sảnh (Cược $%s)", 
                 first_name, len(other_profiles), other_profiles, bet_val)
        await _notify_all(ext_hub,
                          f"🚀 Bắt đầu GOM BÀN ${bet_val}: {first_name} quét tìm bàn TRỐNG, {', '.join(other_profiles) or 'không có phụ'} đứng chờ ở sảnh...",
                          "active", f"🚀 Gom bàn ${bet_val}")

        # Protocol thật từ WS capture: game join bàn cố định bằng
        # [3,"Simms",<rid>,""] (Solo $100=2, $500=4). Không dùng auto-join
        # theo b/Mu vì server có thể lấy state cược cũ và vào sai $500.
        server_join_fn = """(function (rid, bet, mu) {
            const now = Date.now();
            if (window.__last_join_ts && (now - window.__last_join_ts) < 2500) {
                console.warn('[AutoTool V3][SRV] [Anti-Flood] Bỏ qua join (mới cách ' + (now - window.__last_join_ts) + 'ms)');
                return false;
            }
            window.__last_join_ts = now;
            const specificRid = (rid && !isNaN(Number(rid)) && Number(rid) > 0) ? Number(rid) : null;
            if (!specificRid) {
                console.warn('[AutoTool V3][SRV] Thiếu RID cố định, từ chối auto-join để tránh nhầm mức cược.');
                return false;
            }
            const simms = (window.__ws_get_simms && window.__ws_get_simms()) || null;
            if (simms && simms.readyState === 1) {
                try {
                    simms.send(JSON.stringify([3, 'Simms', specificRid, '']));
                    console.log('[AutoTool V3][SRV] Đã gửi join protocol thật rid=' + specificRid + ', bet=' + bet + ', Mu=' + mu);
                    return true;
                } catch (e) {
                    console.error('[AutoTool V3][SRV] Lỗi gửi join:', e);
                }
            }
            // Không fallback bằng click Cocos/toạ độ: node có nhãn 100 có thể
            // thuộc UI khác, còn game dùng state cược cũ và đưa vào $500. Chỉ
            // join khi có socket để gửi RID đã xác minh; nếu không có thì thử
            // lại sau, tuyệt đối không vào nhầm bàn.
            console.warn('[AutoTool V3][SRV] Không thấy socket game; từ chối click fallback để tránh vào sai mức cược.');
            return false;
        })"""
        # LEAVE → JOIN LIỀN MẠCH (chống game tự rejoin bàn cũ).
        # Bằng chứng ws_capture: sau khi tool rời bàn, CHÍNH CLIENT GAME tự gửi
        # [3,"Simms",4,""] để vào lại bàn $500 của phiên trước — 40 frame rid=4
        # đều là `send` thuần, không có bản `inject` (extension luôn push inject)
        # và 5 cặp cách nhau <2500ms nên cũng không thể do controller gửi.
        # Cửa sổ trước khi game kịp rejoin chỉ ~100-600ms, trong khi cổng cũ tiêu
        # 0.8s chỉ để kiểm tra -> không bao giờ lọt, tool không gửi nổi lệnh join
        # nào (phiên lỗi 09-08 02:40 và 03:34: 0 frame rid=2).
        # Chuỗi đã chứng minh chạy đúng (09-08 01:46:30, LEAVE→JOIN 123ms):
        #   [4,"Simms",-1] + cmd 203 -> [4,true,...] -> [3,"Simms",2,""] -> b=100
        # Nên phải chờ ack rời bàn NGAY TRONG TRANG rồi bắn join, không quay vòng
        # qua Python (mỗi evaluate là một round-trip CDP).
        leave_then_join_fn = """(function (rid, bet, mu) {
            return new Promise(function (resolve) {
                const simms = (window.__ws_get_simms && window.__ws_get_simms()) || null;
                if (!simms || simms.readyState !== 1) {
                    resolve({ ok: false, reason: 'no_socket' });
                    return;
                }
                const specificRid = (rid && !isNaN(Number(rid)) && Number(rid) > 0) ? Number(rid) : null;
                if (!specificRid) {
                    console.warn('[AutoTool V3][SRV] Thiếu RID cố định, từ chối join để tránh nhầm mức cược.');
                    resolve({ ok: false, reason: 'no_rid' });
                    return;
                }
                // Chống flood: có RID cụ thể thì 1200ms là đủ (khớp extension).
                // 2500ms của bản cũ còn rộng hơn cả chu kỳ auto-rejoin của game.
                const now = Date.now();
                if (window.__last_join_ts && (now - window.__last_join_ts) < 1200) {
                    resolve({ ok: false, reason: 'anti_flood' });
                    return;
                }

                let done = false;
                function fireJoin(via) {
                    if (done) return;
                    done = true;
                    try { simms.removeEventListener('message', onMsg); } catch (e) {}
                    try {
                        simms.send(JSON.stringify([3, 'Simms', specificRid, '']));
                        window.__last_join_ts = Date.now();
                        console.log('[AutoTool V3][SRV] JOIN rid=' + specificRid + ' ($' + bet + ') qua ' + via);
                        resolve({ ok: true, via: via, rid: specificRid });
                    } catch (e) {
                        resolve({ ok: false, reason: 'send_fail' });
                    }
                }
                function onMsg(ev) {
                    const d = (typeof ev.data === 'string') ? ev.data : '';
                    // Server xác nhận đã rời bàn: [4,true,1,-1,0,""]
                    if (d.indexOf('[4,true') === 0) fireJoin('leave_ack');
                }

                const inside = (typeof window.__autotool_is_inside_table === 'function')
                    ? !!window.__autotool_is_inside_table()
                    : !!(window.__room_players && window.__room_players.length > 0);
                if (!inside) { fireJoin('already_lobby'); return; }

                try { simms.addEventListener('message', onMsg); } catch (e) {}
                try {
                    simms.send('[4,"Simms",-1]');
                    simms.send('[6,"Simms","channelPlugin",{"cmd":203}]');
                } catch (e) {}
                // Không thấy ack (có thể đã ở sảnh sẵn) -> vẫn join sau 700ms.
                setTimeout(function () { fireJoin('timeout'); }, 700);
            });
        })"""
        for p_n, p in pages.items():
            try:
                await p.evaluate(
                    f"() => {{ window.__autotool_exec_join = {server_join_fn};"
                    f" window.__autotool_leave_then_join = {leave_then_join_fn};"
                    f" window.__last_join_ts = 0; }}"
                )
                log.info("find-and-match: Đã cài đè hàm join chuẩn (b/Mu đầy đủ) cho %s", p_n)
            except Exception as e:
                log.warning("find-and-match: Cài đè join cho %s thất bại: %s", p_n, e)

        raw_tries = int(body.get("max_tries", 0) or 0)
        infinite_mode = (raw_tries <= 0)
        max_tries = 999999 if infinite_mode else raw_tries

        found_match = False
        anchor_name = first_name
        anchor_page = first_page
        selected_rid = None

        # VÒNG LẶP CHÍNH: ACCOUNT 1 TÌM BÀN TRỐNG -> LẤY ID -> ĐIỀU PHỐI NICK PHỤ JOIN THEO ID
        for attempt in range(1, max_tries + 1):
            if _should_stop():
                log.info("find-and-match: Người dùng đã bấm DỪNG! Thoát khỏi vòng lặp gom bàn ngay.")
                for p_n, p in pages.items():
                    await _do_leave_room(p, name=p_n, target_mu=target_mu)
                    await _ensure_in_tldl_lobby(p, p_n)
                return {"ok": False, "error": "Đã dừng chu trình gom bàn theo lệnh của bạn.", "stopped": True}

            # ACCOUNT BỊ ĐĂNG XUẤT? -> DỪNG GOM BÀN NGAY, KHÔNG GỬI THÊM LỆNH WS
            # (nguyên nhân đăng xuất trước đây: bot vẫn bắn lệnh khi đã bị kick
            # -> server game đăng xuất phiên). Giữ phiên đăng nhập cho user.
            try:
                on_login = await first_page.evaluate("""() => {
                    if (typeof window.__autotool_is_on_login_screen === 'function') {
                        return window.__autotool_is_on_login_screen();
                    }
                    return false;
                }""")
            except Exception:
                on_login = False
            if on_login:
                log.warning("find-and-match: Account 1 (%s) đang ở MÀN HÌNH ĐĂNG NHẬP (bị đăng xuất) -> DỪNG chu trình ngay!", first_name)
                await _notify_all(ext_hub,
                                  f"❌ {first_name} bị ĐĂNG XUẤT! Vui lòng đăng nhập lại rồi mới chạy Gom bàn.",
                                  "error", "❌ Đăng xuất")
                for p_n, p in pages.items():
                    try:
                        await p.evaluate("() => { if (typeof window.__autotool_check_logged_out === 'function') window.__autotool_check_logged_out(); }")
                    except Exception:
                        pass
                return {"ok": False, "error": f"{first_name} bị đăng xuất, hãy đăng nhập lại tài khoản rồi chạy lại.", "stopped": True}

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

            # SÀNG LỌC "KẸT BÀN CŨ" TRƯỚC MỖI LẦN JOIN (Nguồn gốc lỗi vào nhầm bàn 500):
            # Sau khi reset biến nhớ ở trên, nếu client ĐANG THỰC SỰ NGỒI TRONG BÀN CŨ
            # (vd bàn $500 từ ván trước) thì lệnh cmd 308 b=100 mới sẽ bị game bỏ qua
            # hoặc tự rejoin ĐÚNG bàn cũ $500. Hàm __autotool_is_inside_table đọc scene
            # Cocos TRỰC TIẾP (không phụ thuộc biến nhớ vừa reset) -> phát hiện kẹt bàn
            # và LEAVE TRƯỚC, đảm bảo join lần sau vào ĐÚNG mức cược đã cấu hình.
            # CỔNG XÁC NHẬN: chỉ được gửi cmd 308 khi CHẮC CHẮN đang ở sảnh bàn TLDL
            # (lobby && KHÔNG ngồi trong bàn && không còn room cũ). Capture cho thấy:
            # khi còn ngồi bàn 500 mà gửi 308 -> game trả [4,false,...,102] từ chối,
            # spam 18 lần/2s càng làm kẹt vĩnh viễn.
            try:
                stuck_in_old_table = await first_page.evaluate("""() => {
                    if (typeof window.__autotool_is_inside_table === 'function') {
                        return window.__autotool_is_inside_table();
                    }
                    return !!(window.__room_players && window.__room_players.length > 0);
                }""")
            except Exception:
                stuck_in_old_table = False
            if stuck_in_old_table:
                # KHÔNG bỏ lượt join nữa. Trước đây chỗ này lặp LEAVE + sleep(0.8)
                # tối đa 6 lần rồi `continue`; nhưng game tự rejoin bàn cũ nhanh hơn
                # 0.8s nên cờ này luôn bật -> tool không bao giờ gửi được lệnh join.
                # Nay để __autotool_leave_then_join xử lý liền mạch bên dưới.
                log.info("find-and-match: [Chống nhầm bàn] Account 1 đang trong bàn cũ -> LEAVE và JOIN liền mạch sang bàn $%s.", bet_val)
                await _set_hud_status(first_page, "Đang thoát bàn cũ & vào thẳng bàn đúng cược...")

            # BƯỚC 1: DUY NHẤT ACCOUNT 1 TÌM BÀN CÔNG CỘNG MỚI TRỐNG (THEO MỨC CƯỢC CHÍNH XÁC)
            found_anchor = False
            anchor_rid = None

            if hasattr(first_page, "is_closed") and first_page.is_closed():
                log.info("find-and-match: Trình duyệt Account 1 đã đóng. Dừng chu trình.")
                return {"ok": False, "error": "Trình duyệt Account 1 đã bị đóng.", "stopped": True}

            # 1. Rời bàn cũ (nếu còn) rồi JOIN đúng RID trong cùng một nhịp, ngay
            # khi server ack — không để hở cửa sổ cho game tự rejoin bàn $500.
            join_res = {}
            try:
                join_res = await first_page.evaluate(
                    f"() => {{ if (typeof window.__autotool_leave_then_join === 'function') return window.__autotool_leave_then_join({requested_rid or 'null'}, {bet_val}, {target_mu}); return {{ok: false, reason: 'no_fn'}}; }}"
                ) or {}
            except Exception as e:
                if "closed" in str(e).lower() or "target" in str(e).lower():
                    log.info("find-and-match: Trình duyệt đã đóng (%s). Dừng chu trình.", e)
                    return {"ok": False, "error": "Trình duyệt đã bị đóng.", "stopped": True}

            ws_join_sent = bool(join_res.get("ok"))
            if not ws_join_sent:
                log.warning("find-and-match: Không gửi được join RID=%s cho $%s (lý do: %s). Bỏ lượt thay vì click mù sang bàn khác.",
                            requested_rid, bet_val, join_res.get("reason"))
                await asyncio.sleep(1.0)
                continue
            log.info("find-and-match: Đã gửi JOIN rid=%s ($%s) qua '%s'", requested_rid, bet_val, join_res.get("via"))
            await asyncio.sleep(1.6)

            if _should_stop():
                break

            if await _is_in_tldl_lobby(first_page):
                continue

            # Kiểm tra xem bàn Account 1 vừa vào có phải bàn trống không (đọc trực tiếp biến bộ nhớ JS 0ms)
            is_empty = False
            guest_ss_triggered = False
            for _ in range(10):
                if _should_stop():
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
                    if _should_stop():
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
                await _notify_all(ext_hub,
                                  f"⚠️ {first_name} vào bàn có NGƯỜI LẠ/BÀN FULL → đang OUT về sảnh; {', '.join(other_profiles) or 'đồng đội'} đứng yên chờ bàn trống khác",
                                  "warn", f"⚠️ {first_name}")
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
            expected_fixed_rid = requested_rid or 2

            for _ in range(16):
                if _should_stop():
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
                await _notify_all(ext_hub,
                                  f"⚠️ {anchor_name} lọt vào bàn ${room_b} ≠ cấu hình ${bet_val} → đang OUT để quét lại bàn ${bet_val}",
                                  "warn", f"⚠️ Nhầm mức cược")
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
            await _notify_all(ext_hub,
                              f"🎯 {anchor_name} ĐANG GIỮ bàn #{selected_rid} TRỐNG (${bet_val}) → đồng đội vào ghép NGAY!",
                              "active", f"🎯 {anchor_name}")
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
                await _notify_all(ext_hub,
                                  f"🔄 Khách lạ vào bàn #{selected_rid} lúc {anchor_name} đang giữ → HỦY lệnh, out tìm bàn trống khác",
                                  "warn", f"🔄 {anchor_name}")
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
                if _should_stop():
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

                # Chốt lần cuối ngay trước khi cấp vé: Account 1 phải vẫn là
                # người duy nhất ở đúng RID đã chọn. Nếu khách lạ chen vào,
                # tuyệt đối không cho Account 2 join vào bàn đó.
                try:
                    anchor_gate = await anchor_page.evaluate("""() => ({
                        rid: Number((window.__last_room_info && window.__last_room_info.rid) || window.__ws_last_room_id || 0),
                        bet: Number((window.__last_room_info && window.__last_room_info.b) || 0),
                        players: (window.__room_players || []).length,
                        in_game: !!window.__game_in_progress,
                        stranger: !!(window.__last_room_info && window.__last_room_info.has_stranger)
                    })""")
                    gate_rid = int(anchor_gate.get("rid") or 0)
                    gate_bet = int(anchor_gate.get("bet") or 0)
                    gate_players = int(anchor_gate.get("players") or 0)
                    if gate_rid != int(selected_rid) or gate_bet != int(bet_val) or gate_players != 1 or anchor_gate.get("in_game") or anchor_gate.get("stranger"):
                        log.warning("find-and-match: HỦY vé join %s — Anchor không còn một mình đúng bàn (rid=%s/$%s, players=%s).",
                                    sub_name, gate_rid, gate_bet, gate_players)
                        if ext_hub and ext_hub.is_connected(sub_name):
                            await ext_hub.send_command(sub_name, "LEAVE_ROOM", {"reason": "Anchor không còn một mình ở bàn trống"})
                        continue
                except Exception as e:
                    log.warning("find-and-match: Không xác minh được Anchor ngay trước khi cấp vé: %s", e)
                    continue

                # Cấp vé trước mọi command tới Sub. JOIN_ROOM của Hub chỉ là
                # thông báo; lệnh WS thật bên dưới chỉ chạy khi vé hợp lệ.
                try:
                    await sub_p.evaluate(f"""() => {{
                        window.__AUTOTOOL_SUB_JOIN_TICKET = {{
                            rid: {int(selected_rid)}, bet: {bet_val}, mu: {target_mu},
                            anchor: {_json.dumps(anchor_name)}, used: false,
                            expires_at: Date.now() + 8000
                        }};
                    }}""")
                except Exception:
                    log.warning("find-and-match: Không cấp được vé join cho %s", sub_name)
                    continue

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
                    # không kịp ready/start/xả). Đồng thời seed expected anchor cho isPartner
                    # và cấp VÉ JOIN dùng một lần: phụ không có quyền tự vào bàn.
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
                # Nick phụ dùng CÙNG protocol RID thật với anchor. Không phát
                # cmd=308 auto-join để không bị game đổi sang mức cược khác.
                # Cũng dùng leave→join liền mạch: nếu phụ còn kẹt trong bàn cũ thì
                # lệnh join thẳng sẽ bị game từ chối, phụ lỡ mất bàn anchor đang giữ.
                # Phụ đang đứng sẵn ở sảnh (trường hợp thường) đi nhánh
                # 'already_lobby' -> bắn join ngay, không chậm thêm nhịp nào.
                try:
                    join_res = await sub_p.evaluate(f"""() => {{
                        window.__last_join_ts = 0;
                        const _rid = {int(selected_rid)};
                        if (typeof window.__autotool_leave_then_join !== 'function') return {{ok: false, reason: 'no_join_fn'}};
                        return window.__autotool_leave_then_join(_rid, {bet_val}, {target_mu});
                    }}""")
                    log.info("find-and-match: [%s] Gửi lệnh JOIN trực tiếp bàn #%s -> %s", sub_name, selected_rid, join_res)
                except Exception as e:
                    log.warning("find-and-match: [%s] Lỗi gửi lệnh JOIN trực tiếp: %s", sub_name, e)

                # Chờ sub_p vào bàn (tối đa 4.5s)
                sub_matched = False
                for _ in range(9):
                    if _should_stop():
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
                await _notify_all(ext_hub,
                                  f"✅ {anchor_name} và {', '.join(other_profiles)} ĐÃ NGỒI CHUNG bàn #{selected_rid} (${bet_val}) → Sẵn sàng → Bắt đầu → Xả bài!",
                                  "success", "✅ Gặp nhau thành công")
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
                js_res = await p.evaluate("""(wantStart) => {
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

                                        // btn_begin chỉ thuộc quyền chủ bàn. Nick phụ không
                                        // được kích nó vì có thể là nút Start của Account 1.
                                        if (wantStart && c.btn_begin && c.btn_begin.node && c.btn_begin.node.active) {
                                            found = true;
                                            btnName = "btn_begin";
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
                                        const labelMatchesRole = wantStart
                                            ? (labelStr.includes("BẮT ĐẦU") || labelStr.includes("BAT DAU"))
                                            : (labelStr.includes("SẴN SÀNG") || labelStr.includes("SAN SANG"));
                                        if (labelMatchesRole) {
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

                        // Gọi DUY NHẤT helper đúng vai trò, không bắn Ready/Start
                        // lẫn nhau trên cả hai account.
                        if (wantStart && typeof window.__autotool_exec_start === "function") {
                            try { window.__autotool_exec_start(); } catch (_) {}
                        } else if (!wantStart && typeof window.__autotool_exec_ready === "function") {
                            try { window.__autotool_exec_ready(); } catch (_) {}
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
                }""", bool(is_anchor))
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

            # 3. Chỉ click khi Cocos/OpenCV xác định đúng nút. Không click tâm
            # màn hình khi không thấy nút vì dễ click vào UI bàn/cược khác.
            if has_found:
                try:
                    await p.mouse.click(click_x, click_y)
                    log.info("find-and-match: [%s] >>> Đã CLICK nút '%s' đã xác minh tại (%d, %d) <<<",
                             name, btn_type, click_x, click_y)
                except Exception:
                    pass
            else:
                log.warning("find-and-match: [%s] Không thấy nút '%s'; chỉ dùng WS helper đúng vai trò, không click mù.", name, btn_type)

            return has_found

        # Vòng lặp tuần tự kiểm tra & click Sẵn Sàng (Account 2) -> Bắt Đầu (Account 1)
        # Chạy mỗi 400ms, tối đa 16 lần (~7-8s) cho đến khi chia bài
        match_started = False
        for tick in range(1, 17):
            if _should_stop():
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

        # Nếu sau đủ lượt vẫn chưa chia bài (chưa Ready/Start thành công) -> hủy bàn,
        # đưa về sảnh bàn Đếm Lá, KHÔNG treo chờ xả bài.
        if not match_started:
            log.warning("find-and-match: KHÔNG thể bắt đầu ván (chưa Sẵn Sàng/Bắt Đầu) sau 16 lượt -> hủy bàn & về sảnh bàn Đếm Lá.")
            await _notify_all(ext_hub,
                              f"⚠️ Chưa Sẵn Sàng/Bắt Đầu được bàn #{selected_rid} → hủy, về sảnh bàn Đếm Lá",
                              "warn", "⚠️ Chưa bắt đầu")
            for p_name, p in pages.items():
                await _do_leave_room(p, name=p_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(p, p_name)
            return {"ok": False, "error": "Chưa thể bắt đầu ván bài (Ready/Start thất bại).", "stopped": False}

        # 3. HỢP NHẤT 1 LUỒNG DUY NHẤT: EXTENSION V3 TỰ ĐỘNG XẢ BÀI QUA WEBSOCKET (cmd 253 / cmd 254)
        # Không chạy song song CooperativeDiscardEngine click chuột mù quáng gây desync và kick khỏi server!
        log.info("find-and-match: >>> Extension V3 tự động phân tích & xả bài tối ưu qua WebSocket (<2ms)... <<<")
        for p_name, p in pages.items():
            await _set_hud_status(p, f"Đang trong ván #{selected_rid} - Extension V3 tự động xả bài...")

        # Theo dõi ván bài hoàn tất qua biến bộ nhớ Extension V3 (tối đa 45s)
        game_completed = False
        t_game_end = time.time() + 45.0
        while time.time() < t_game_end:
            if _should_stop():
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
                game_completed = True
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
        if auto_start_guest_ss and not game_completed:
            log.info("find-and-match: Chế độ 'Bắt đầu nếu khách SS' đang bật, chủ bàn canh 5 giây xem có khách...")
            for _ in range(10):
                if _should_stop():
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

        # BƯỚC 8: Sau ván đã xác nhận, nick phụ luôn out về sảnh. Account chính
        # chỉ out khi người dùng bật auto_leave_after; như vậy UI/log thể hiện
        # chính xác nick nào đã rời bàn và không tự rời khi ván bị timeout.
        if game_completed:
            # KILL quy trình xả/gom sau khi ván kết thúc nhưng giữ Anchor trong
            # phòng: tắt toàn bộ timer săn bàn, timer bắt đầu lại và auto-xả;
            # tuyệt đối không dùng STOP_HUNT cho Anchor vì lệnh đó có LEAVE.
            log.info("find-and-match: Ván đã xong -> kill engine/timer, giữ Account chính trong phòng cho khách ngoài.")
            if ext_hub:
                ext_hub.set_room_share(False)
            try:
                await anchor_page.evaluate("""() => {
                    window.__AUTOTOOL_AUTO_HUNT = false;
                    window.__AUTOTOOL_ARMED = false;
                    window.__AUTOTOOL_AUTO_DISCARD = false;
                    window.__is_hunt_initiator = false;
                    if (window.__hunt_retry_timer) { clearTimeout(window.__hunt_retry_timer); window.__hunt_retry_timer = null; }
                    if (window.__hunt_wait_timer) { clearTimeout(window.__hunt_wait_timer); window.__hunt_wait_timer = null; }
                    if (window.__start_retry_timer) { clearInterval(window.__start_retry_timer); window.__start_retry_timer = null; }
                    if (window.__auto_turn_timer) { clearTimeout(window.__auto_turn_timer); window.__auto_turn_timer = null; }
                    window.__autotool_hud_status = 'Đã xả bài xong — Account chính giữ phòng, chờ khách ngoài.';
                }""")
            except Exception as e:
                log.warning("find-and-match: không kill được timer Anchor sau khi xả: %s", e)
            log.info("find-and-match: Ván xả bài hoàn tất -> đưa các nick phụ về sảnh bàn Đếm Lá...")
            await asyncio.sleep(0.5)
            for p_name in other_profiles:
                p = pages.get(p_name)
                if not p:
                    continue
                await _do_leave_room(p, name=p_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(p, p_name)
                await _set_hud_status(p, "Đã xả bài xong — Account phụ đã rời bàn, đang ở sảnh chọn bàn.")
            if bm and bm.sessions:
                for sid, s in list(bm.sessions.items()):
                    acc_n = (s.account or {}).get("name")
                    if acc_n in other_profiles:
                        s.room_id = -1
                        s.log = "Đã xả bài xong — Account phụ đã rời bàn về sảnh chọn bàn"
            await _notify_all(ext_hub,
                              f"✅ Xả bài hoàn tất: {', '.join(other_profiles) or 'Account phụ'} đã out; Account chính giữ phòng chờ khách ngoài.",
                              "success", "✅ Account phụ đã out")

            if auto_leave_after:
                log.info("find-and-match: auto_leave_after bật -> đưa Account chính về sảnh.")
                await _do_leave_room(first_page, name=first_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(first_page, first_name)
                await _set_hud_status(first_page, "Đã hoàn tất xả bài — đang ở sảnh chọn bàn.")
                if bm and bm.sessions:
                    for sid, s in list(bm.sessions.items()):
                        if (s.account or {}).get("name") == first_name:
                            s.room_id = -1
                            s.log = "Đã hoàn tất xả bài, đang ở sảnh chọn bàn"
            else:
                await _set_hud_status(first_page, "Đã xả bài xong — Account phụ đã out, Account chính giữ phòng chờ khách ngoài.")
        elif not _should_stop():
            log.warning("find-and-match: Hết thời gian theo dõi ván; không tự out Account phụ để tránh mất trạng thái chưa xác minh.")
            await _notify_all(ext_hub,
                              "⚠️ Chưa xác nhận kết thúc ván trong 45 giây; giữ nguyên bàn để kiểm tra, không tự out Account phụ.",
                              "warn", "⚠️ Chờ xác nhận ván")

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
            "screenshot": shot_a,
        }

    except asyncio.CancelledError:
        log.info("find-and-match: Nhận tín hiệu CANCEL từ nút Dừng! Kill triệt để mọi engine săn bàn...")
        try:
            ext_hub = getattr(request.app.state, "ext_hub", None)
            if ext_hub:
                ext_hub.set_room_share(False)
                await ext_hub.broadcast_command("STOP_HUNT", {"reset": True})
        except Exception:
            pass
        # Tắt engine tự săn + clear toàn bộ timers trên MỌI page tham gia (chống join zombie)
        for p_n, p in list(pages.items()):
            try:
                await _clear_hunt_state(p)
            except Exception:
                pass
        # Không điều hướng/click sau cancellation: Stop phải thực sự dừng ngay.
        return {"ok": False, "error": "Đã dừng chu trình gom bàn theo lệnh của bạn.", "stopped": True}
    finally:
        active_match_tasks = getattr(request.app.state, "active_match_tasks", None)
        if active_match_tasks is not None:
            active_match_tasks.discard(asyncio.current_task())
        if getattr(request.app.state, "active_match_task", None) == asyncio.current_task():
            request.app.state.active_match_task = None

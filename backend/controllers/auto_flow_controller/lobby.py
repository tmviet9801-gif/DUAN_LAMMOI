"""Điều hướng sảnh Tiến Lên Đếm Lá + rời bàn.

Toàn bộ hàm ở đây thao tác trên một Playwright Page và không phụ thuộc
`request`, nên dùng lại được ở mọi route."""
import asyncio
import logging
import os
from pathlib import Path
from core.page_world import eval_page

log = logging.getLogger("auto_flow_controller")


async def _get_screen_size_util(p):
    try:
        sz = await eval_page(p, "({w: window.innerWidth, h: window.innerHeight})")
        return int(sz.get("w") or 784), int(sz.get("h") or 505)
    except Exception:
        return 784, 505


async def _clear_hunt_state(p):
    """Dập tắt toàn bộ engine săn bàn & timers trên 1 page (chống join zombie sau Dừng)."""
    if not p or (hasattr(p, "is_closed") and p.is_closed()):
        return
    try:
        await eval_page(p, """() => {
            try { localStorage.setItem('AUTOTOOL_STOPPED', '1'); } catch(e) {}
            // Đóng cổng kích hoạt + xoá cấu hình lượt chạy. Nếu còn sót
            // __target_hunt_bet thì lần sau người dùng chơi tay, vào bàn khác
            // mức cược sẽ bị extension tự out.
            window.__AUTOTOOL_ENGAGED = false;
            window.__AUTOTOOL_AUTO_DISCARD = false;
            window.__auto_start_guest_ss = false;
            window.__target_hunt_bet = 0;
            window.__target_hunt_mu = 0;
            window.__AUTOTOOL_MATCH_ROLE = null;
            window.__AUTOTOOL_ROLE = null;
            window.__AUTOTOOL_SUB_JOIN_TICKET = null;
            window.__autotool_partners = [];
            window.__AUTOTOOL_AUTO_HUNT = false;
            window.__AUTOTOOL_ARMED = false;
            window.__is_hunt_initiator = false;
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


async def _is_in_tldl_lobby_util(p):
    if not p or (hasattr(p, "is_closed") and p.is_closed()):
        return False
    try:
        # Kiểm tra trạng thái sảnh qua biến bộ nhớ Extension V3 (0ms, không tốn CPU/CDP).
        # TUYỆT ĐỐI KHÔNG dùng simms.readyState làm fallback: socket kết nối không đồng
        # nghĩa đang ở sảnh bàn Đếm Lá (vẫn có thể đang ở sảnh chính HitClub). Nếu hàm
        # Extension chưa được inject -> coi là CHƯA ở sảnh để buộc điều hướng.
        in_tldl = await eval_page(p, """() => {
            if (typeof window.__autotool_is_in_tldl_lobby === 'function') {
                return window.__autotool_is_in_tldl_lobby();
            }
            return false;
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

    # ƯU TIÊN: dùng chính hàm điều hướng của extension. Nó DẸP POPUP trước rồi
    # click bằng node Cocos (Game Bài -> Tiến Lên Đếm Lá -> tab Solo/4 người),
    # nên không phụ thuộc ảnh mẫu hay độ phân giải.
    #
    # Đường OpenCV bên dưới KHÔNG dẹp popup: gặp banner "CẢNH BÁO LỪA ĐẢO" của
    # game là kẹt luôn ở sảnh chính — đúng tình huống nick phụ đứng ngoài trong
    # khi nick chính đã vào sảnh chọn bàn, làm hỏng cả lượt gom bàn.
    try:
        entered = await eval_page(p, """(mu) => {
            if (typeof window.__autotool_dismiss_popups === 'function') {
                try { window.__autotool_dismiss_popups(); } catch (e) {}
            }
            if (typeof window.__autotool_auto_enter_tldl === 'function') {
                return window.__autotool_auto_enter_tldl(mu);
            }
            return null;
        }""", int(target_mu))
        if entered is not None:
            await asyncio.sleep(0.5)
            if await _is_in_tldl_lobby_util(p):
                log.info("%s đã vào sảnh Tiến Lên Đếm Lá qua điều hướng của extension.", name)
                return True
            log.info("%s: điều hướng extension chưa vào được sảnh -> thử tiếp bằng OpenCV.", name)
    except Exception as e:
        log.warning("%s: gọi điều hướng extension lỗi (%s) -> dùng OpenCV.", name, e)

    log.info("%s chưa ở sảnh Tiến Lên Đếm Lá -> Kích hoạt điều hướng thông minh (OpenCV Template Matching)...", name)

    tpl_dir = Path(__file__).resolve().parent.parent / "data" / "templates"
    tpl_close = str(tpl_dir / "btn_close_popup.png")
    tpl_gb = str(tpl_dir / "btn_game_bai.png")
    tpl_tldl = str(tpl_dir / "btn_tldl_icon.png")

    # 0. Kiểm tra nếu đang ở trong bàn chơi -> PHẢI rời bàn trước khi thao tác sảnh!
    try:
        in_tbl = await eval_page(p, """() => {
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
        is_on_login = await eval_page(p, """() => {
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

    # ƯU TIÊN: dùng engine Cocos-native của Extension (__autotool_auto_enter_tldl) —
    # chính xác và nhanh hơn OpenCV template matching (vốn hay rớt khi popup/resolution lệch).
    try:
        native_res = await eval_page(p, 
            f"() => (typeof window.__autotool_auto_enter_tldl === 'function') ? window.__autotool_auto_enter_tldl({target_mu}) : null"
        )
        if isinstance(native_res, dict) and native_res.get("ok"):
            log.info("✅ %s đã vào sảnh Tiến Lên Đếm Lá qua engine Cocos-native!", name)
            return True
    except Exception as e:
        log.warning("%s engine Cocos-native điều hướng sảnh lỗi (fallback OpenCV): %s", name, e)

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
        await eval_page(p, """(() => {
            try {
                let sent = false;
                if (typeof window.__autotool_exec_leave === 'function') {
                    sent = window.__autotool_exec_leave() !== false;
                }
                if (!sent && typeof window.__ws_send === 'function') {
                    window.__ws_send('[4,"Simms",-1]');
                    sent = true;
                }
                // Fallback cuối cho extension/script cũ chưa export helper.
                if (!sent && Array.isArray(window.__ws_instances)) {
                    const ws = window.__ws_instances.find((item) => item && item.readyState === 1);
                    if (ws) ws.send('[4,"Simms",-1]');
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
        await eval_page(p, """(() => {
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
        in_tbl = await eval_page(p, """() => {
            if (typeof window.__autotool_is_inside_table === 'function') return window.__autotool_is_inside_table();
            return false;
        }""")
        if not in_tbl:
            log.info("_do_leave_room: %s chưa ở sảnh bàn Đếm Lá -> tự động điều hướng vào sảnh bàn Đếm Lá...", name)
            await _ensure_in_tldl_lobby_util(p, name=name, target_mu=target_mu)
    except Exception:
        pass

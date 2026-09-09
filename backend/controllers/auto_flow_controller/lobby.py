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


async def dong_luot_chay(pages, ly_do=""):
    """Tắt chế độ tự động trên MỌI trang khi lượt chạy kết thúc.

    Khác `_clear_hunt_state` (dùng cho nút Dừng): hàm này KHÔNG đặt cờ
    `AUTOTOOL_STOPPED`. Lượt chạy kết thúc bình thường không phải là "người
    dùng đã bấm Dừng"; đặt cờ đó sẽ làm lượt sau phải tự xoá và dễ sinh lại
    đúng lỗi "nick phụ không bao giờ đánh bài" đã từng gặp.

    Vì sao cần: khối kết thúc cũ chỉ chạy trên trang anchor và chỉ tắt vài cờ.
    `__AUTOTOOL_ENGAGED` không được tắt ở BẤT KỲ trang nào, `__target_hunt_bet`
    còn nguyên. Người dùng không bấm Dừng (chẳng có lý do gì phải bấm — lượt
    chạy đã xong), tự tay vào bàn khác chơi, và:
      - nick phụ còn `__AUTOTOOL_AUTO_DISCARD` -> tool TỰ ĐÁNH BÀI hộ;
      - hết ván nick phụ TỰ RỜI BÀN;
      - vào bàn khác mức cược -> bị TỰ OUT sau ~150ms vì `__target_hunt_bet`
        vẫn là mức của lượt trước.
    Nguyên tắc đã thống nhất: chưa kích hoạt thì phải hành xử như người dùng
    bình thường — đã chạy xong cũng vậy.
    """
    js = """() => {
        window.__AUTOTOOL_ENGAGED = false;
        window.__AUTOTOOL_ARMED = false;
        window.__AUTOTOOL_AUTO_HUNT = false;
        window.__AUTOTOOL_AUTO_DISCARD = false;
        window.__auto_start_guest_ss = false;
        window.__is_hunt_initiator = false;
        window.__is_matched_locked = false;
        window.__target_hunt_bet = 0;
        window.__target_hunt_mu = 0;
        window.__AUTOTOOL_MATCH_ROLE = null;
        window.__AUTOTOOL_ROLE = null;
        window.__AUTOTOOL_SUB_JOIN_TICKET = null;
        window.__expected_anchor_profile = null;
        window.__expected_anchor_dn = null;
        window.__expected_anchor_u = null;
        window.__expected_anchor_uid = null;
        window.__active_room_invite = null;
        // Bài của đồng đội từ lượt trước: không xoá thì ván đầu lượt sau đánh
        // theo bài cũ.
        window.__partner_cards = null;
        window.__autotool_partners = [];
        if (window.__hunt_retry_timer) { clearTimeout(window.__hunt_retry_timer); window.__hunt_retry_timer = null; }
        if (window.__hunt_wait_timer) { clearTimeout(window.__hunt_wait_timer); window.__hunt_wait_timer = null; }
        if (window.__start_retry_timer) { clearInterval(window.__start_retry_timer); window.__start_retry_timer = null; }
        if (window.__auto_turn_timer) { clearTimeout(window.__auto_turn_timer); window.__auto_turn_timer = null; }
        if (window.__guest_ss_wait_timer) { clearTimeout(window.__guest_ss_wait_timer); window.__guest_ss_wait_timer = null; }
    }"""
    for ten, p in list((pages or {}).items()):
        if not p or (hasattr(p, "is_closed") and p.is_closed()):
            continue
        try:
            await eval_page(p, js)
        except Exception as e:
            log.warning("đóng lượt chạy trên %s lỗi: %s", ten, e)
    log.info("đã đóng lượt chạy trên %d trang%s", len(pages or {}),
             f" ({ly_do})" if ly_do else "")


async def man_hinh_hien_tai(p):
    """Profile đang ở màn nào: sanh_chinh / game_bai / chon_ban / trong_ban."""
    if not p or (hasattr(p, "is_closed") and p.is_closed()):
        return "dong"
    try:
        return await eval_page(p, """() => {
            return (typeof window.__autotool_man_hinh === 'function')
                ? window.__autotool_man_hinh() : 'chua_nap';
        }""") or "?"
    except Exception:
        return "?"


async def bam_muc(p, muc, name="Profile", target_mu=2):
    """Bấm một mục điều hướng: JS TÍNH VỊ TRÍ, Playwright BẤM THẬT.

    Vì sao tách đôi: đo trên sảnh thật cho thấy sự kiện chuột/cảm ứng TỔNG HỢP
    bằng JS KHÔNG tới được Cocos. Đã thử năm kiểu — mouse trên canvas, touch,
    pointer kiểu touch, mouse trên document, emit thẳng vào node — không kiểu
    nào chuyển được tab. Chỉ `page.mouse.click` của Playwright (sự kiện thật,
    `isTrusted`) mới ăn.

    Đó cũng là lý do bản cũ "bấm" tab Game Bài mà màn không đổi: hàm JS báo
    thành công nên luồng đi tiếp, rồi bước sau bấm mù vào vị trí ô Đếm Lá —
    nhưng vẫn đang ở tab ALL GAMES, nên trúng ô Tài Xỉu.

    Toạ độ lấy TỪ CHÍNH NODE nên đúng ở mọi kích thước cửa sổ.
    """
    if not p or (hasattr(p, "is_closed") and p.is_closed()):
        return False, "trang đã đóng"
    try:
        vt = await eval_page(p, """(muc) => {
            if (typeof window.__autotool_vi_tri_muc !== 'function') {
                return { ok: false, loi: 'extension chưa nạp' };
            }
            return window.__autotool_vi_tri_muc(muc);
        }""", muc) or {}
    except Exception as e:
        return False, f"không hỏi được vị trí: {e}"

    if not vt.get("ok"):
        return False, vt.get("loi") or "không xác định được vị trí"

    sw, sh = await _get_screen_size_util(p)
    x = int(sw * float(vt["nx"]))
    y = int(sh * float(vt["ny"]))
    try:
        await p.mouse.click(x, y)
    except Exception as e:
        return False, f"bấm lỗi: {e}"
    log.info("%s: bấm '%s' tại (%d, %d) — node=%s sprite=%s",
             name, muc, x, y, vt.get("node"), vt.get("sprite"))
    return True, ""


async def ly_do_chua_o_sanh(p):
    """Vì sao profile này chưa ở sảnh chọn bàn — câu nói thẳng cho người dùng.

    Chỉ báo tên profile là không đủ: người dùng không biết phải làm gì. Ba
    nguyên nhân hay gặp khác hẳn nhau — popup quảng cáo che màn, đứng ở sảnh
    chính, hoặc extension chưa nạp.
    """
    if not p or (hasattr(p, "is_closed") and p.is_closed()):
        return "trang đã đóng"
    try:
        return await eval_page(p, """() => {
            if (typeof window.__autotool_is_in_tldl_lobby !== 'function') {
                return 'extension chưa nạp — đóng và mở lại profile';
            }
            if (typeof window.__autotool_has_popup === 'function'
                    && window.__autotool_has_popup()) {
                return 'có popup/quảng cáo che màn hình';
            }
            // Nói rõ đang KẸT Ở ĐÂU, không chỉ "chưa vào được".
            const man = (typeof window.__autotool_man_hinh === 'function')
                ? window.__autotool_man_hinh() : '?';
            const mo_ta = {
                sanh_chinh: 'còn đứng ở sảnh chính (chưa bấm được tab Game Bài)',
                game_bai: 'đã vào màn Game Bài nhưng chưa bấm được ô Tiến Lên Đếm Lá',
                trong_ban: 'đang ngồi trong một bàn — cần rời bàn trước',
                tldl_khac: 'đang ở khu Đếm Lá nhưng không phải màn chọn bàn',
                chon_ban: 'đã ở sảnh chọn bàn',
            };
            return mo_ta[man] || (window.__autotool_ly_do_chua_o_sanh || 'chưa rõ');
        }""") or "chưa rõ"
    except Exception as e:
        return f"không đọc được trạng thái ({type(e).__name__})"


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

    # DẸP POPUP TRƯỚC KHI HỎI "đã ở sảnh chưa". Thứ tự cũ hỏi trước, nên khi
    # nhận nhầm (nick phụ đứng ở sảnh chính có popup quảng cáo) thì hàm trả
    # True ngay và KHÔNG BAO GIỜ chạy tới bước dẹp popup / điều hướng bên dưới.
    try:
        await eval_page(p, """() => {
            if (typeof window.__autotool_dismiss_popups === 'function') {
                try { window.__autotool_dismiss_popups(); } catch (e) {}
            }
        }""")
        await asyncio.sleep(0.35)
    except Exception:
        pass

    # 1. Nếu đã ở sẵn sảnh Tiến Lên Đếm Lá
    if await _is_in_tldl_lobby_util(p):
        try:
            tab_x = 0.500 if target_mu == 2 else 0.690
            await p.mouse.click(int(sw * tab_x), int(sh * 0.175))
            await asyncio.sleep(0.3)
        except Exception:
            pass
        return True

    # ĐƯỜNG CHÍNH: JS tính vị trí từ chính node, Playwright bấm bằng chuột THẬT.
    #
    # Bản trước gọi `__autotool_auto_enter_tldl()` để extension tự bấm. Đo trên
    # sảnh thật: sự kiện chuột/cảm ứng TỔNG HỢP bằng JS không tới được Cocos —
    # đã thử năm kiểu, không kiểu nào chuyển được tab. Hàm JS vẫn báo thành
    # công nên luồng đi tiếp, rồi bấm mù vào vị trí ô Đếm Lá trong khi màn vẫn
    # là tab ALL GAMES — trúng ô Tài Xỉu.
    #
    # Mỗi bước đều XÁC MINH bằng `__autotool_man_hinh()` trước khi đi tiếp.
    dep_popup_js = """() => {
        if (typeof window.__autotool_dismiss_popups === 'function') {
            try { window.__autotool_dismiss_popups(); } catch (e) {}
        }
    }"""
    muc_tab_cho = "tab_solo" if int(target_mu) == 2 else "tab_4nguoi"

    for vong in range(3):
        try:
            await eval_page(p, dep_popup_js)
            await asyncio.sleep(0.4)
        except Exception:
            pass

        man = await man_hinh_hien_tai(p)
        if man == "chua_nap":
            log.warning("%s: extension chưa nạp -> không điều hướng được.", name)
            break
        if man == "trong_ban":
            log.info("%s: đang trong bàn -> rời bàn trước khi vào sảnh.", name)
            break

        if man == "sanh_chinh":
            ok, ly_do = await bam_muc(p, "tab_game_bai", name)
            if not ok:
                log.warning("%s: chưa bấm được tab GAME BÀI — %s", name, ly_do)
            await asyncio.sleep(1.0)
            man = await man_hinh_hien_tai(p)

        if man == "game_bai":
            ok, ly_do = await bam_muc(p, "o_dem_la", name)
            if not ok:
                log.warning("%s: chưa bấm được ô TIẾN LÊN ĐẾM LÁ — %s", name, ly_do)
            await asyncio.sleep(2.0)
            man = await man_hinh_hien_tai(p)

        if man == "chon_ban":
            # Tab Solo / 4 người. Không bấm được theo node thì lùi về toạ độ
            # tỉ lệ — rủi ro thấp vì đã ở trong sảnh Đếm Lá, và bước join sau
            # còn đối chiếu rid theo mức cược.
            ok, _ = await bam_muc(p, muc_tab_cho, name)
            if not ok:
                tab_x = 0.500 if int(target_mu) == 2 else 0.690
                try:
                    await p.mouse.click(int(sw * tab_x), int(sh * 0.175))
                except Exception:
                    pass
            await asyncio.sleep(0.5)
            log.info("%s: đã đứng ở sảnh chọn bàn Tiến Lên Đếm Lá.", name)
            return True

        log.info("%s: sau vòng %d vẫn ở màn '%s' -> thử lại.", name, vong + 1, man)
        await asyncio.sleep(0.8)

    log.info("%s: đường chính chưa vào được sảnh -> thử tiếp bằng OpenCV.", name)

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

        # Bước 2: Tìm và click tab [ GAME BÀI ].
        # Không nhận ra thì DỪNG chứ không click theo toạ độ: sai vài chục pixel
        # là rơi vào ô game khác, và người dùng thấy tool vào sảnh Tài/Xỉu.
        shot2 = await p.screenshot(type="png")
        loc_gb, score_gb = _match_template_cv(shot2, tpl_gb, threshold=0.75)
        if loc_gb:
            log.info("%s phát hiện tab [GAME BÀI] tại %s (độ khớp %.2f) -> click chọn Game Bài!", name, loc_gb, score_gb)
            await p.mouse.click(loc_gb[0], loc_gb[1])
            await asyncio.sleep(0.8)
        else:
            # KHÔNG click mù. Toạ độ tỉ lệ trượt là trúng ô game bên cạnh —
            # đúng triệu chứng "bấm vào sảnh cược Tài/Xỉu chứ không vào được
            # Game Bài". Chú thích ở bước 1 đã ghi "tuyệt đối không click mù"
            # nhưng chính bước này lại làm thế.
            log.warning("%s: không nhận ra tab GAME BÀI (độ khớp cao nhất %.2f < 0.75) "
                        "-> DỪNG, không click mò. Sẽ thử lại lượt sau.", name, score_gb)
            return False

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
            log.warning("%s: không nhận ra ô TIẾN LÊN ĐẾM LÁ (độ khớp cao nhất %.2f < 0.75) "
                        "-> DỪNG, không click mò.", name, score_tldl)
            return False

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

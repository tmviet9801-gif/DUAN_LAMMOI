"""Luồng GOM BÀN: tìm bàn trống theo RID cố định rồi ghép nick phụ vào cùng bàn."""
import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from models.config_model import load_accounts

from core.page_world import eval_page

from .constants import BET_RATIOS, FIXED_TABLE_RIDS
from .context import (
    MatchContext,
    danh_sach_dong_doi,
    load_extension_scripts,
    resolve_profile_name,
)
from .preflight import loc_profile_du_dieu_kien, so_du_toi_thieu
from .deps import _build_adapter, _notify_all
from .lobby import (
    _clear_hunt_state,
    _do_leave_room,
    dong_luot_chay,
    ly_do_chua_o_sanh,
)
from .rounds import check_and_click_ready_or_start

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
        # KHÔNG tự chọn thay người dùng. Bản trước lùi về ["Account 01",
        # "Account 02"] — chạy trên hai tài khoản có tiền thật mà không ai yêu cầu.
        raise HTTPException(
            status_code=400,
            detail="Chưa chọn profile nào. Hãy tích ít nhất 2 profile trên bảng danh sách.",
        )

    accounts = load_accounts()
    profiles_input = [resolve_profile_name(p, accounts) for p in profiles_input]
    requested_anchor = resolve_profile_name(body.get("profile_a"), accounts)
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

    adapter = _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})

    # ---- KIỂM ĐIỀU KIỆN TRƯỚC KHI MỞ CHROME ----
    # Mở profile rồi mới phát hiện hết tiền / token hết hạn là quá muộn: lúc đó
    # đã ngồi vào bàn. Account thiếu tiền còn bị server đá ra giữa chừng, để
    # account giữ tiền ngồi lại một mình với người lạ.
    # Kiểm bằng token + WebSocket, KHÔNG mở Chrome (profile đang mở thì đọc
    # thẳng từ trang).
    # Chan tham so vo nghia NGAY, truoc khi ton cong mo Chrome.
    # Truoc day: target_bet la -> am tham ha xuong 100 (nguoi dung tin la dang
    # choi muc minh chon); mu ngoai {2,4} -> FIXED_TABLE_RIDS khong co rid ->
    # requested_rid = None -> moi vong deu tu choi join voi ly do 'no_rid', ngu
    # 1s, lap lai 999999 lan. Giao dien dung yen o "DANG DO TIM PHONG" vinh vien,
    # khong mot thong bao nao. O Slot la o nhap SO TU DO nen go 3 la dinh.
    _bet_kiem = int(body.get("target_bet", 100) or 100)
    if _bet_kiem not in BET_RATIOS:
        raise HTTPException(
            status_code=400,
            detail=(f"Muc cuoc ${_bet_kiem:,} khong co trong game. "
                    f"Chon mot trong: {', '.join(f'${b:,}' for b in sorted(BET_RATIOS))}"
                    ).replace(",", "."))
    _mu_kiem = int(body.get("mu", 2) or 2)
    if FIXED_TABLE_RIDS.get(f"{_bet_kiem}_{_mu_kiem}") is None:
        raise HTTPException(
            status_code=400,
            detail=(f"Ban {_mu_kiem} cho khong ton tai o muc ${_bet_kiem:,}. "
                    f"So cho hop le: 2 hoac 4.").replace(",", "."))
    _ext_hub = getattr(request.app.state, "ext_hub", None)

    if body.get("kiem_truoc", True):
        _theo_ten = {str(a.get("name") or "").strip().lower(): a
                     for a in accounts if isinstance(a, dict)}
        _chon = [_theo_ten[p.strip().lower()] for p in profiles_input
                 if p.strip().lower() in _theo_ten]

        _dat, _bi_loai = await loc_profile_du_dieu_kien(
            adapter, _ext_hub, _chon, _bet_kiem)

        if _bi_loai:
            log.warning("preflight: loại %d/%d profile — %s",
                        len(_bi_loai), len(_chon),
                        "; ".join(f"{x['profile']}: {x['ly_do']}" for x in _bi_loai))

        _ten_dat = [str(a.get("name")) for a in _dat]
        if profile_a not in _ten_dat:
            _vi_sao = next((x["ly_do"] for x in _bi_loai if x["profile"] == profile_a),
                           "không đủ điều kiện")
            raise HTTPException(
                status_code=400,
                detail=(f"Account giữ tiền {profile_a} không vào bàn được: {_vi_sao}. "
                        f"Bàn ${_bet_kiem:,} cần tối thiểu "
                        f"{so_du_toi_thieu(_bet_kiem):,}.").replace(",", "."),
            )
        if len(_ten_dat) < 2:
            _ds = "; ".join(f"{x['profile']}: {x['ly_do']}" for x in _bi_loai)
            raise HTTPException(
                status_code=400,
                detail=(f"Chỉ còn {len(_ten_dat)} profile đủ điều kiện, cần ít nhất 2. "
                        f"Bị loại — {_ds}"),
            )

        # Giữ nguyên thứ tự người dùng đã tích, chỉ bỏ những cái không đạt.
        profiles_input = [p for p in profiles_input if p in _ten_dat]
        # Tên in-game vừa đọc được tươi hơn bản trong database -> dùng cho
        # bước bơm danh sách đồng đội ở preflight bên dưới.
        _moi = {str(a.get("name")): a for a in _dat}
        accounts = [_moi.get(str(a.get("name")), a) for a in accounts]

    page_a = await adapter._page(profile_a)
    if not page_a:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {profile_a}")

    # Chuẩn bị Playwright Page cho tất cả tài khoản tham gia (2 đến 5 tài khoản)
    pages = {}
    ext_scripts = load_extension_scripts()

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
                for fname, code in ext_scripts:
                    try:
                        await eval_page(p, code)
                    except Exception as e:
                        log.warning("Inject %s to %s: %s", fname, p_name, e)
        except Exception as e:
            log.warning("find-and-match: Không mở được trang cho %s: %s", p_name, e)

    if not pages:
        raise HTTPException(status_code=400, detail=f"Không có tài khoản nào trong {profiles_input} đang mở trình duyệt!")
    if profile_a not in pages:
        raise HTTPException(status_code=400, detail=f"Không mở được trình duyệt tài khoản chính {profile_a}")


    ctx = MatchContext(request, adapter, pages, profiles_input, body)

    # Bí danh cục bộ trỏ vào ctx. Nhờ đó THÂN VÒNG LẶP bên dưới giữ nguyên
    # từng ký tự so với bản trước khi tách — không có chỗ nào để lọt lỗi.
    gid = ctx.gid
    target_mu = ctx.target_mu
    bet_val = ctx.bet_val
    requested_rid = ctx.requested_rid
    auto_xa = ctx.auto_xa
    auto_start_guest_ss = ctx.auto_start_guest_ss
    auto_leave_after = ctx.auto_leave_after
    stop_epoch = ctx.stop_epoch
    run_id = ctx.run_id
    _should_stop = ctx.should_stop
    _get_screen_size = ctx.screen_size
    _is_in_tldl_lobby = ctx.in_lobby
    _ensure_in_tldl_lobby = ctx.ensure_lobby
    _set_hud_status = ctx.set_hud

    async def _check_and_click_ready_or_start(p, is_anchor=False, name="Profile"):
        return await check_and_click_ready_or_start(ctx, p, is_anchor=is_anchor, name=name)

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
        # Danh sach dong doi DA XAC MINH, lay tu database. Extension khoi tao
        # `__autotool_partners = []` va chi nhan dong doi qua khop CHINH XAC
        # `character_name`, nen khong bom xuong day thi khong ai nhan ai.
        dong_doi, thieu_ten = danh_sach_dong_doi(list(pages.keys()), accounts)
        if thieu_ten:
            log.warning(
                "find-and-match: %s chua co character_name -> KHONG duoc nhan la "
                "dong doi (danh nhu nguoi thuong). Chay Check Live de dien.",
                ", ".join(str(x) for x in thieu_ten))
            await _notify_all(
                ctx.ext_hub,
                f"Chua co ten in-game cho: {', '.join(str(x) for x in thieu_ten)}. "
                f"Chay Check Live truoc khi xa bai.",
                "warn")

        preflight_code = f"""() => {{
            // Danh tinh dong doi da xac minh (character_name tu database).
            window.__autotool_partners = {_json.dumps(dong_doi)};
            // Mở cổng kích hoạt: từ đây extension mới được phép tự động
            // (rời bàn khi gặp khách lạ, Sẵn sàng/Bắt đầu, tự đánh bài).
            // XOÁ CỜ DỪNG TRÊN MỌI TRANG. Trước đây chỉ anchor được xoá (trong
            // khối cấu hình role), trong khi _clear_hunt_state lại SET cờ này
            // trên TẤT CẢ trang khi bấm Dừng. Hậu quả: từ lần chạy thứ hai trở
            // đi, nick phụ vẫn còn cờ -> isAutoEngaged() false -> phụ KHÔNG
            // BAO GIỜ đánh bài, dù đã ghép bàn thành công.
            try {{ localStorage.removeItem('AUTOTOOL_STOPPED'); }} catch(e) {{}}
            window.__AUTOTOOL_ENGAGED = true;
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
                await eval_page(p, preflight_code)
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
            # Nói RÕ vì sao từng profile chưa vào được. Chỉ liệt kê tên thì
            # người dùng không biết phải làm gì — popup quảng cáo che màn khác
            # hẳn với đứng ở sảnh chính hay extension chưa nạp.
            ly_do = []
            for p_name in not_ready:
                ly_do.append(f"{p_name} ({await ly_do_chua_o_sanh(pages.get(p_name))})")
            err_msg = ("Chưa đưa được các profile vào sảnh chọn bàn Đếm Lá — "
                       "KHÔNG chạy gom bàn: " + "; ".join(ly_do))
            log.warning("find-and-match: %s", err_msg)
            await _notify_all(getattr(request.app.state, "ext_hub", None), f"❌ {err_msg}", "error", "❌ Lỗi sảnh")
            # Preflight ĐÃ bật cờ kích hoạt trên mọi trang -> phải tắt lại,
            # nếu không extension vẫn tự động khi người dùng chơi tay.
            await dong_luot_chay(pages, "không vào được sảnh")
            return {"ok": False, "error": err_msg, "stopped": False}

        # Anchor duy nhất là profile_a do UI/API chỉ định. Không suy đoán từ
        # tên để tránh đảo chiều: chính phải tìm/giữ bàn, phụ phải lắng nghe.
        first_name = profile_a
        first_page = pages[first_name]
        other_profiles = [name for name in pages.keys() if name != first_name]

        # Ban chi co `target_mu` cho. Anchor chiem mot, nen so nick phu NGOI
        # DUOC toi da la target_mu - 1. Truoc day vong lap co gang cho MOI nick
        # phu ngoi xuong roi doi TAT CA phai thanh cong, nen tick 3 profile o
        # ban 2 cho la khong bao gio ghep duoc — ma van bao thanh cong.
        so_phu_toi_da = max(0, int(target_mu) - 1)
        phu_se_ngoi = other_profiles[:so_phu_toi_da]
        phu_du_bi = other_profiles[so_phu_toi_da:]
        if phu_du_bi:
            log.info("find-and-match: ban %s cho -> %d nick phu ngoi cung anchor; "
                     "%s la du bi, dung cho o sanh",
                     target_mu, len(phu_se_ngoi), ", ".join(phu_du_bi))

        # Làm sạch toàn bộ biến khóa cũ và kích hoạt chế độ SĂN BÀN trên các Extension
        ext_hub = getattr(request.app.state, "ext_hub", None)
        if ext_hub:
            try:
                # CỐ ĐỊNH QUYỀN ĐIỀU PHỐI VỀ CONTROLLER: tắt auto-forward của Hub (Hub
                # forward theo ri.get('b') -> dễ nhầm bàn 100->500). Controller tự gửi
                # JOIN_ROOM chuẩn (bet_val chính xác) cho từng nick phụ.
                ext_hub.set_room_share(False)
                await ext_hub.broadcast_command("RESET_STATE", {})
                # "Bắt đầu nếu khách SS" chỉ hợp lệ khi KHÔNG có nick phụ đang
                # chờ: có phụ mà bắt đầu với người lạ là phụ không vào được bàn
                # nữa. Lớp gác Python ở dưới (`auto_start_guest_ss and not
                # other_profiles`) đã đúng, nhưng extension hành động độc lập
                # theo khung WS nên qua mặt được — phải TẮT CỜ ngay từ đây.
                # Cấu hình Anchor (Chủ bàn) chạy CHẾ ĐỘ BACKEND-DRIVEN:
                # - TẮT tự săn/self-join (__AUTOTOOL_AUTO_HUNT=false) -> không còn 2 engine
                #   join song song (nguồn gốc lỗi nhầm bàn 100->500 & join zombie sau Dừng).
                # - Vẫn bật auto-xả bài (__AUTOTOOL_AUTO_DISCARD) theo auto_xa để đánh khi tới lượt.
                try:
                    await eval_page(first_page, f"""() => {{
                        try {{ localStorage.removeItem('AUTOTOOL_STOPPED'); }} catch(e) {{}}
                        window.__AUTOTOOL_AUTO_HUNT = false;
                        window.__AUTOTOOL_ARMED = true;
                        window.__AUTOTOOL_MATCH_ROLE = 'anchor';
                        window.__is_hunt_initiator = true;
                        window.__AUTOTOOL_AUTO_DISCARD = {_json.dumps(auto_xa)};
                        window.__auto_start_guest_ss = {_json.dumps(bool(auto_start_guest_ss) and not other_profiles)};
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
                            await eval_page(sub_p, """() => {
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
            await eval_page(first_page, f"""() => {{
                window.__AUTOTOOL_MATCH_ROLE = 'anchor';
                window.__AUTOTOOL_ROLE = 'winner';
                window.__AUTOTOOL_PARTNER_PROFILES = {_json.dumps(other_profiles)};
                window.__AUTOTOOL_AUTO_DISCARD = {_json.dumps(auto_xa)};
                window.__AUTOTOOL_AUTO_HUNT = false;
            }}""")
            for sub_name in other_profiles:
                sub_page = pages[sub_name]
                await eval_page(sub_page, f"""() => {{
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
                await eval_page(p, 
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
                on_login = await eval_page(first_page, """() => {
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
                        await eval_page(p, "() => { if (typeof window.__autotool_check_logged_out === 'function') window.__autotool_check_logged_out(); }")
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
                await eval_page(first_page, "() => { window.__last_room_info = null; window.__ws_last_room_id = null; window.__room_players = []; window.__game_in_progress = false; window.__is_matched_locked = false; window.__my_cards = []; }")
                for other_p in [p for k, p in pages.items() if k != first_name]:
                    await eval_page(other_p, "() => { window.__last_room_info = null; window.__ws_last_room_id = null; window.__room_players = []; window.__game_in_progress = false; window.__is_matched_locked = false; window.__my_cards = []; }")
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
                stuck_in_old_table = await eval_page(first_page, """() => {
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
                join_res = await eval_page(first_page, 
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
                    r_info = await eval_page(first_page, """() => {
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
                            await eval_page(first_page, "() => { if (typeof window.__autotool_exec_start === 'function') window.__autotool_exec_start(); }")
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
                    in_g = await eval_page(first_page, "() => !!window.__game_in_progress")
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
                    val = await eval_page(anchor_page, "() => (window.__last_room_info && window.__last_room_info.rid) || window.__ws_last_room_id || null")
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
                room_b = await eval_page(anchor_page, "() => (window.__last_room_info && window.__last_room_info.b) || null")
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
                anchor_user_info = await eval_page(anchor_page, """() => ({
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
                    alive_check = await eval_page(anchor_page, """() => ({
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
            da_ngoi = []
            for sub_name in phu_se_ngoi:
                if _should_stop():
                    break
                sub_p = pages[sub_name]
                log.info("find-and-match: Gửi lệnh join bàn công cộng #%s cho %s nhanh chóng...", selected_rid, sub_name)
                # Đồng bộ 2 CHIỀU định danh giữa Account 1 và Account 2 (để cả 2 nhận diện chính xác 100% đồng đội, không out nhầm)
                try:
                    p_info_anchor = {"dn": anchor_dn, "u": anchor_u, "uid": anchor_uid, "profile_name": anchor_name}
                    
                    sub_user_info = {}
                    try:
                        sub_user_info = await eval_page(sub_p, """() => ({
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
                    await eval_page(sub_p, f"() => {{ if (!window.__autotool_partners) window.__autotool_partners = []; window.__autotool_partners.push({_json.dumps(p_info_anchor)}); if (typeof globalThis !== 'undefined') globalThis.__autotool_partners = window.__autotool_partners; }}")
                    
                    # 2. Nạp Account 2 vào Account 1 (ĐỂ ACCOUNT 1 NHẬN BIẾT ACCOUNT 2 LÀ ĐỒNG ĐỘI, KHÔNG COI LÀ KHÁCH LẠ)
                    await eval_page(anchor_page, f"() => {{ if (!window.__autotool_partners) window.__autotool_partners = []; window.__autotool_partners.push({_json.dumps(p_info_sub)}); if (typeof globalThis !== 'undefined') globalThis.__autotool_partners = window.__autotool_partners; }}")

                    # Extension GÁN ĐÈ danh sách khi nhận SYNC_PARTNERS, không
                    # gộp. Gửi mảnh lẻ từng nick thì xong nick B, anchor có
                    # partners=[B]; sang nick C thì thành [C] — B biến mất và bị
                    # coi là khách lạ ngay tại bàn của mình. Luôn gửi CẢ danh
                    # sách đã xác minh từ database, cộng thêm nick vừa xử lý.
                    if ext_hub:
                        ds_chung = list(dong_doi)
                        if ext_hub.is_connected(sub_name):
                            await ext_hub.send_command(sub_name, "SYNC_PARTNERS", {
                                "partners": ds_chung + [p_info_anchor, anchor_name, anchor_dn, anchor_u]})
                        if ext_hub.is_connected(anchor_name):
                            await ext_hub.send_command(anchor_name, "SYNC_PARTNERS", {
                                "partners": ds_chung + [p_info_sub, sub_name, sub_dn, sub_u]})
                except Exception as e:
                    log.warning("find-and-match: Lỗi đồng bộ định danh 2 chiều: %s", e)

                # Chốt lần cuối ngay trước khi cấp vé: Account 1 phải vẫn là
                # người duy nhất ở đúng RID đã chọn. Nếu khách lạ chen vào,
                # tuyệt đối không cho Account 2 join vào bàn đó.
                try:
                    anchor_gate = await eval_page(anchor_page, """() => ({
                        rid: Number((window.__last_room_info && window.__last_room_info.rid) || window.__ws_last_room_id || 0),
                        bet: Number((window.__last_room_info && window.__last_room_info.b) || 0),
                        players: (window.__room_players || []).length,
                        la: (window.__room_players || []).filter((p) => {
                            try {
                                if (typeof window.__is_me === 'function' && window.__is_me(p)) return false;
                                if (typeof window.__is_partner === 'function' && window.__is_partner(p)) return false;
                            } catch (e) {}
                            return true;   // thiếu helper -> coi là khách lạ (hỏng an toàn)
                        }).length,
                        in_game: !!window.__game_in_progress,
                        stranger: !!(window.__last_room_info && window.__last_room_info.has_stranger)
                    })""")
                    gate_rid = int(anchor_gate.get("rid") or 0)
                    gate_bet = int(anchor_gate.get("bet") or 0)
                    gate_players = int(anchor_gate.get("players") or 0)
                    gate_la = int(anchor_gate.get("la") or 0)
                    con_cho = int(target_mu) - gate_players
                    # Điều kiện đúng là KHÔNG CÓ KHÁCH LẠ và CÒN CHỖ, không phải
                    # "anchor một mình". Sau khi nick phụ đầu ngồi xuống, anchor
                    # thấy 2 người — điều kiện cũ `players != 1` huỷ vé của MỌI
                    # nick phụ tiếp theo, nên bàn 4 chỗ không bao giờ đủ người.
                    if (gate_rid != int(selected_rid) or gate_bet != int(bet_val)
                            or gate_la > 0 or con_cho < 1
                            or anchor_gate.get("in_game") or anchor_gate.get("stranger")):
                        log.warning("find-and-match: HỦY vé join %s — bàn không an toàn "
                                    "(rid=%s/$%s, người=%s, khách lạ=%s, còn chỗ=%s).",
                                    sub_name, gate_rid, gate_bet, gate_players, gate_la, con_cho)
                        if ext_hub and ext_hub.is_connected(sub_name):
                            await ext_hub.send_command(sub_name, "LEAVE_ROOM", {"reason": "Bàn của anchor không còn an toàn/không còn chỗ"})
                        # Đây là trạng thái của CẢ BÀN, không riêng nick này ->
                        # đi tiếp các nick khác là vô nghĩa. Và phải hạ cờ, nếu
                        # không sẽ báo "GOM BÀN THÀNH CÔNG" với người còn thiếu.
                        all_subs_matched = False
                        break
                except Exception as e:
                    log.warning("find-and-match: Không xác minh được Anchor ngay trước khi cấp vé: %s", e)
                    all_subs_matched = False
                    break

                # Cấp vé trước mọi command tới Sub. JOIN_ROOM của Hub chỉ là
                # thông báo; lệnh WS thật bên dưới chỉ chạy khi vé hợp lệ.
                try:
                    await eval_page(sub_p, f"""() => {{
                        window.__AUTOTOOL_SUB_JOIN_TICKET = {{
                            rid: {int(selected_rid)}, bet: {bet_val}, mu: {target_mu},
                            anchor: {_json.dumps(anchor_name)}, used: false,
                            expires_at: Date.now() + 8000
                        }};
                    }}""")
                except Exception:
                    log.warning("find-and-match: Không cấp được vé join cho %s", sub_name)
                    all_subs_matched = False
                    break

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
                    await eval_page(sub_p, f"""() => {{
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
                    join_res = await eval_page(sub_p, f"""() => {{
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
                        sub_user_info = await eval_page(sub_p, """() => ({
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
                        sub_pls = await eval_page(sub_p, "() => window.__room_players || []")
                    except Exception:
                        pass

                    anchor_pls = []
                    try:
                        anchor_pls = await eval_page(anchor_page, "() => window.__room_players || []")
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

                if sub_matched:
                    da_ngoi.append(sub_name)
                if not sub_matched:
                    all_subs_matched = False
                    log.warning("find-and-match: %s không vào được bàn #%s cùng %s!", sub_name, selected_rid, anchor_name)
                    if not await _is_in_tldl_lobby(sub_p):
                        await _do_leave_room(sub_p, name=sub_name, target_mu=target_mu)
                        await _ensure_in_tldl_lobby(sub_p, sub_name)
                    break

            # Thành công = ĐỦ số nick phụ mà bàn chứa được, và chỉ tính những
            # nick ĐÃ xác minh hai chiều. Trước đây cờ `all_subs_matched` vẫn
            # True khi vé bị huỷ bằng `continue`, nên hệ thống báo "ĐÃ NGỒI
            # CHUNG bàn" kèm tên những nick chưa bao giờ vào.
            if all_subs_matched and len(da_ngoi) == len(phu_se_ngoi) and da_ngoi:
                found_match = True
                log.info("find-and-match: >>> GOM BÀN THÀNH CÔNG! %s + %s đã ở chung bàn #%s <<<",
                         anchor_name, ", ".join(da_ngoi), selected_rid)
                _them = f" ({len(phu_du_bi)} nick dự bị chờ ở sảnh)" if phu_du_bi else ""
                await _notify_all(ext_hub,
                                  f"✅ {anchor_name} và {', '.join(da_ngoi)} ĐÃ NGỒI CHUNG bàn #{selected_rid} (${bet_val}){_them} → Sẵn sàng → Bắt đầu → Xả bài!",
                                  "success", "✅ Gặp nhau thành công")
                break
            else:
                log.info("find-and-match: Ghép phòng chưa thành công -> Account 1 (%s) thoát ra sảnh bàn Đếm Lá để tìm bàn mới...", anchor_name)
                await _do_leave_room(anchor_page, name=anchor_name, target_mu=target_mu)
                await _ensure_in_tldl_lobby(anchor_page, anchor_name)
                await asyncio.sleep(0.8)


        if not found_match or not selected_rid:
            await dong_luot_chay(pages, "không gom được bàn")
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
                in_game = await eval_page(anchor_page, "() => Boolean(window.__game_in_progress || (window.__my_cards && window.__my_cards.length > 0))")
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
            await dong_luot_chay(pages, "không bắt đầu được ván")
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
                in_prog = await eval_page(anchor_page, "() => Boolean(window.__game_in_progress)")
                cards_cnt = await eval_page(anchor_page, "() => (window.__my_cards || []).length")
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
                    pls = await eval_page(anchor_page, "() => window.__room_players || []")
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
                await eval_page(anchor_page, """() => {
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

        # Đóng lượt chạy CHỈ khi ván đã kết thúc thật. Nhánh hết 45 giây bên
        # trên cố ý giữ nguyên bàn để kiểm tra — ván CÓ THỂ VẪN ĐANG CHẠY, tắt
        # AUTO_DISCARD giữa ván là nick phụ ngưng đánh và bị treo lượt/phạt bài.
        if game_completed:
            await dong_luot_chay(pages, "ván đã kết thúc")

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

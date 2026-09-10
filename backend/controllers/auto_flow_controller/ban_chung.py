"""XÉ LẺ QUY TRÌNH: một account TÌM BÀN trống, account khác bấm VÀO BÀN đó.

Yêu cầu của người dùng (11/09/2026), lấy theo cách làm của công cụ Sunwin
(`control/control.py`): ở đó mỗi kết nối là một hàng ngang có nút "Tạo phòng" /
"Tìm phòng" / "Dừng"; ai tạo phòng xong thì bàn đó thành BÀN CHUNG
(`shared_room`) và những máy khác bấm "Tìm phòng" là vào thẳng bàn ấy.

Khác luồng `find-and-match-ws` cũ: ở đó phải tích sẵn account chính + account
phụ rồi chạy đồng thời, không chen ngang được. Ở đây hai bước rời nhau, bấm lúc
nào cũng được.

LỖI THẬT ĐÃ SỬA (11/09/2026): nick giữ bàn đứng im khi khách lạ ngồi vào. Bàn
2 chỗ hết ghế, nên nick thứ hai bấm "Vào bàn" thì bàn đã đầy, không vào được.
Nay có hai lớp:
  - EXTENSION rời ngay khi thấy khách (cờ `__AUTOTOOL_ROI_KHI_CO_KHACH`), vì nó
    đọc khung WS tức thì;
  - BACKEND canh nền, thấy mất bàn hoặc có khách thì DÒ LẠI và cập nhật bàn
    chung, để nút "Vào bàn" luôn trỏ vào bàn còn trống thật.

XÁC MINH BẰNG TÊN NHÂN VẬT, không đếm đầu người: bàn 2 người có thể là
"mình + đồng đội" (đúng) hoặc "mình + khách" (phải rời). `JS_DOC_BAN` tách hai
loại bằng chính `isPartner` của extension — khớp CHÍNH XÁC theo `character_name`.
"""
import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from models.config_model import load_accounts
from core.page_world import eval_page

from .constants import BET_RATIOS, FIXED_TABLE_RIDS, kiem_so_cho
from .context import load_extension_scripts, resolve_profile_name
from .join_js import JS_DOC_BAN, js_cai_dat_join
from .ket_noi import ngat_extension, noi_extension
from .kich_hoat import js_giu_ban, js_kich_hoat
from .lobby import _ensure_in_tldl_lobby_util, _is_in_tldl_lobby_util

log = logging.getLogger("auto_flow_controller")
router = APIRouter()

# Bao lâu coi như bàn chung đã cũ (người giữ có thể đã rời từ đời nào).
HAN_BAN_CHUNG = 900.0
# Canh bàn tối đa bấy nhiêu giây rồi buông, tránh task sống mãi.
HAN_CANH_BAN = 900.0


def _trang_dang_mo(request, ten):
    """Trang Chrome ĐANG MỞ; không mở mới (dùng cho vòng canh nền)."""
    manager = getattr(request.app.state, "manager", None)
    if not manager or not getattr(manager, "sessions", None):
        return None
    from services.page_pool import PagePool
    try:
        return PagePool(manager).peek(ten)
    except Exception:
        return None


def _ds_ban(request):
    """Bảng BÀN ĐANG GIỮ: {tên profile -> {rid, bet, mu, chu_cn, luc}}.

    Nhiều nick cùng bấm TÌM BÀN được, mỗi nick giữ một bàn riêng. Nick thứ ba
    bấm VÀO BÀN thì ghép vào MỘT trong các bàn đó và xác minh ngay bằng tên
    nhân vật của đúng chủ bàn ấy.
    """
    ds = getattr(request.app.state, "ban_dang_giu", None)
    if not isinstance(ds, dict):
        ds = {}
        request.app.state.ban_dang_giu = ds
    # Dọn bàn quá hạn ngay lúc đọc: chủ có thể đã rời từ đời nào.
    for ten in [t for t, b in ds.items()
                if time.time() - float(b.get("luc") or 0) > HAN_BAN_CHUNG]:
        ds.pop(ten, None)
    return ds


def _ghi_ban(request, ten, rid, bet, mu):
    _ds_ban(request)[ten] = {
        "rid": int(rid), "bet": int(bet), "mu": int(mu),
        "chu_cn": _character_name(ten), "luc": time.time(),
    }


def _xoa_ban(request, ten):
    _ds_ban(request).pop(ten, None)


def _lay_ban_cua(request, ten):
    return _ds_ban(request).get(ten)


def _character_name(ten):
    """Tên nhân vật in-game của một profile — khoá xác minh duy nhất."""
    for a in load_accounts() or []:
        if isinstance(a, dict) and str(a.get("name") or "").strip().lower() == str(ten).strip().lower():
            return str(a.get("character_name") or "").strip()
    return ""


def _ten_dong_doi(ten_minh):
    """Tên nhân vật in-game của MỌI account khác — để extension nhận ra đồng đội.

    Khoá đối chiếu là `character_name`, không phải username: hai tên chỉ khác
    một ký tự (`nicktestxabai1` vs `nicktestxxabai1`) nên nhầm là khớp sai người.
    """
    ra = []
    for a in load_accounts() or []:
        if not isinstance(a, dict):
            continue
        if str(a.get("name") or "").strip().lower() == str(ten_minh).strip().lower():
            continue
        cn = str(a.get("character_name") or "").strip()
        if cn:
            ra.append(cn)
    return ra


def _kiem_tham_so(bet, mu):
    bet = int(bet or 100)
    if bet not in BET_RATIOS:
        raise HTTPException(status_code=400,
                            detail=f"Mức cược ${bet:,} không có trong game.".replace(",", "."))
    try:
        mu = kiem_so_cho(mu or 2)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    rid = FIXED_TABLE_RIDS.get(f"{bet}_{mu}")
    if not rid:
        raise HTTPException(status_code=400,
                            detail=f"Không có bàn {mu} chỗ ở mức ${bet:,}.".replace(",", "."))
    return bet, mu, int(rid)


async def _chuan_bi(request, ten, bet, mu, auto_xa):
    """Đưa profile về đúng tư thế dò bàn — dùng lại nguyên luồng của gom bàn.

    Chưa mở Chrome thì MỞ (không bắt người dùng tự mở), nạp lại bộ script
    extension, dẹp popup và điều hướng vào sảnh Tiến Lên Đếm Lá, rồi mới mở
    cổng kích hoạt và cài hàm join. Không nạp script thì `__ws_get_simms` và
    `__autotool_is_inside_table` không tồn tại, hàm join trả `no_socket`.
    """
    from .deps import _build_adapter

    adapter = _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})
    try:
        trang = await adapter._page(ten)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không mở được Chrome cho {ten}: {e}")
    if trang is None:
        raise HTTPException(
            status_code=400,
            detail=f"Không mở được Chrome cho {ten}. Kiểm tra profile có trong danh sách không.")

    try:
        await adapter.sniffer.inject_playwright(trang)
        await adapter.sniffer.inject(trang)
    except Exception:
        pass
    for fname, code in load_extension_scripts():
        try:
            await eval_page(trang, code)
        except Exception as e:
            log.warning("TÌM BÀN: nạp %s cho %s lỗi: %s", fname, ten, e)

    await noi_extension(request, ten)

    # Dẹp popup + vào sảnh bàn Đếm Lá (đường chính bằng node, dự phòng OpenCV).
    if not await _is_in_tldl_lobby_util(trang):
        log.info("TÌM BÀN: %s chưa ở sảnh Đếm Lá -> điều hướng vào sảnh...", ten)
        vao = False
        for _ in range(3):
            try:
                vao = await _ensure_in_tldl_lobby_util(trang, name=ten, target_mu=mu)
            except Exception as e:
                log.warning("TÌM BÀN: điều hướng %s lỗi: %s", ten, e)
                vao = False
            if vao:
                break
            await asyncio.sleep(1.0)
        if not vao:
            raise HTTPException(
                status_code=409,
                detail=(f"{ten} chưa vào được sảnh Tiến Lên Đếm Lá "
                        f"(có thể đang ở màn đăng nhập). Kiểm tra Chrome rồi bấm lại."))
        log.info("TÌM BÀN: ✅ %s đã ở sảnh Tiến Lên Đếm Lá.", ten)

    await eval_page(trang, js_cai_dat_join())
    # Cổng kích hoạt MỞ + vai anchor: gặp bàn có người ngoài thì extension tự
    # rời, đúng thứ vòng dò cần.
    await eval_page(trang, js_kich_hoat("anchor", auto_xa, _ten_dong_doi(ten), bet, mu))
    return trang


async def _doc_ban(trang):
    try:
        tt = await eval_page(trang, JS_DOC_BAN)
    except Exception:
        return None
    return tt if isinstance(tt, dict) else None


async def _do_va_giu(request, trang, ten, bet, mu, rid, auto_xa, so_lan):
    """Dò tới khi ngồi được bàn TRỐNG rồi giữ bàn + ghi vào bảng bàn đang giữ.

    Trả `(ok, rid_that, so_lan_da_do, ly_do)`.
    """
    ly_do = "chưa dò xong"
    for lan in range(1, so_lan + 1):
        try:
            kq = await eval_page(
                trang, f"() => window.__autotool_leave_then_join({rid}, {bet}, {mu})") or {}
        except Exception as e:
            return False, None, lan, f"lỗi gửi lệnh vào bàn: {e}"
        if not kq.get("ok"):
            ly_do = str(kq.get("reason") or "join_that_bai")
            await asyncio.sleep(1.2)
            continue

        tt = None
        for _ in range(10):
            await asyncio.sleep(0.25)
            tt = await _doc_ban(trang)
            if tt and tt.get("co_thong_tin"):
                break
        if not tt or not tt.get("co_thong_tin"):
            ly_do = "không đọc được trạng thái bàn"
            continue

        # BÀN TRỐNG = một mình VÀ không có ai lạ. Xác minh theo tên nhân vật
        # (JS_DOC_BAN tách đồng đội / khách bằng isPartner), không đếm đầu người.
        if int(tt.get("so_khach") or 0) > 0:
            ly_do = "bàn có khách: " + (", ".join(tt.get("ten_khach") or []) or "?")
            log.info("TÌM BÀN: [%s] lần %d — %s, dò tiếp.", ten, lan, ly_do)
            await asyncio.sleep(1.0)
            continue
        if int(tt.get("so_nguoi") or 0) > 1:
            ly_do = "bàn đã có người ngồi sẵn"
            log.info("TÌM BÀN: [%s] lần %d — %s, dò tiếp.", ten, lan, ly_do)
            await asyncio.sleep(1.0)
            continue

        rid_that = int(tt.get("rid") or rid)
        # roi_khi_co_khach=True: khách ngồi vào là extension RỜI ngay, vì bàn
        # đầy thì đồng đội không vào được nữa.
        await eval_page(trang, js_giu_ban(auto_xa, bet, mu,
                                          dong_doi=_ten_dong_doi(ten),
                                          roi_khi_co_khach=True))
        _ghi_ban(request, ten, rid_that, bet, mu)
        log.info("TÌM BÀN: >>> %s ĐÃ GIỮ BÀN TRỐNG #%s ($%s) sau %d lần dò. <<<",
                 ten, rid_that, bet, lan)
        return True, rid_that, lan, ""

    return False, None, so_lan, ly_do


async def _canh_giu_ban(request, ten, bet, mu, rid, auto_xa):
    """Canh nền bàn đang giữ: khách vào (hoặc rơi khỏi bàn) thì DÒ LẠI.

    Dừng canh khi: đồng đội đã ngồi cùng (xong việc), người dùng bấm Dừng, bàn
    của nick này bị xoá, Chrome đóng, hoặc quá `HAN_CANH_BAN`.
    """
    moc = int(getattr(request.app.state, "gom_ban_stop_epoch", 0))
    het = time.time() + HAN_CANH_BAN
    while time.time() < het:
        await asyncio.sleep(1.2)
        if int(getattr(request.app.state, "gom_ban_stop_epoch", 0)) != moc:
            log.info("CANH BÀN: %s — người dùng đã bấm Dừng, thôi canh.", ten)
            return
        ban = _lay_ban_cua(request, ten)
        if not ban:
            log.info("CANH BÀN: %s — bàn đã bị xoá/hết hạn, thôi canh.", ten)
            return
        trang = _trang_dang_mo(request, ten)
        if trang is None:
            log.info("CANH BÀN: %s — Chrome đã đóng, thôi canh.", ten)
            return
        tt = await _doc_ban(trang)
        if tt is None or tt.get("dang_van"):
            continue
        if int(tt.get("so_dong_doi") or 0) > 0:
            log.info("CANH BÀN: ✅ %s — đồng đội %s đã vào bàn #%s, thôi canh.",
                     ten, ", ".join(tt.get("ten_dong_doi") or []) or "?", ban.get("rid"))
            return

        co_khach = int(tt.get("so_khach") or 0) > 0
        roi_ban = not tt.get("co_thong_tin") or int(tt.get("so_nguoi") or 0) == 0
        if not co_khach and not roi_ban:
            continue

        vi_sao = ("khách vào bàn: " + (", ".join(tt.get("ten_khach") or []) or "?")) \
            if co_khach else "đã rơi khỏi bàn"
        log.warning("CANH BÀN: %s — %s -> dò bàn khác.", ten, vi_sao)
        _xoa_ban(request, ten)
        ok, rid_moi, lan, ly_do = await _do_va_giu(
            request, trang, ten, bet, mu, rid, auto_xa, so_lan=40)
        if not ok:
            log.warning("CANH BÀN: %s dò lại không được (%s), thôi canh.", ten, ly_do)
            return
        log.info("CANH BÀN: %s đã chuyển sang giữ bàn #%s.", ten, rid_moi)


def _bat_canh(request, ten, bet, mu, rid, auto_xa):
    """Mỗi nick giữ bàn có MỘT vòng canh riêng — chạy song song được."""
    ds = getattr(request.app.state, "canh_ban_tasks", None)
    if not isinstance(ds, dict):
        ds = {}
        request.app.state.canh_ban_tasks = ds
    cu = ds.get(ten)
    if cu and not cu.done():
        cu.cancel()
    ds[ten] = asyncio.create_task(_canh_giu_ban(request, ten, bet, mu, rid, auto_xa))


def _dung_canh(request, ten=None):
    ds = getattr(request.app.state, "canh_ban_tasks", None)
    if not isinstance(ds, dict):
        return
    for t in ([ten] if ten else list(ds.keys())):
        task = ds.pop(t, None)
        if task and not task.done():
            task.cancel()


@router.post("/api/autoplay/tim-ban")
async def tim_ban(body: dict, request: Request):
    """MỘT account dò cho tới khi ngồi được vào một bàn TRỐNG, rồi giữ bàn.

    Gọi được ĐỒNG THỜI cho nhiều nick: mỗi nick giữ một bàn riêng, mỗi nick có
    một vòng canh riêng. Nick khác bấm VÀO BÀN sẽ ghép vào một trong các bàn đó.

    Body: profile_name, bet (mặc định 100), mu (mặc định 2),
          auto_xa (mặc định True), so_lan (mặc định 40 vòng).
    """
    body = body or {}
    ten = resolve_profile_name(body.get("profile_name"), load_accounts())
    if not ten:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào.")
    bet, mu, rid = _kiem_tham_so(body.get("bet"), body.get("mu"))
    auto_xa = bool(body.get("auto_xa", True))
    so_lan = max(1, min(int(body.get("so_lan") or 40), 200))

    trang = await _chuan_bi(request, ten, bet, mu, auto_xa)
    log.info("TÌM BÀN: %s bắt đầu dò bàn trống $%s (%s chỗ, rid=%s).", ten, bet, mu, rid)

    ok, rid_that, lan, ly_do = await _do_va_giu(
        request, trang, ten, bet, mu, rid, auto_xa, so_lan)
    if not ok:
        log.warning("TÌM BÀN: %s dò %d lần chưa gặp bàn trống (%s).", ten, lan, ly_do)
        return {"ok": False, "profile": ten,
                "error": f"Dò {lan} lần chưa gặp bàn trống ({ly_do}).", "so_lan_do": lan}

    _bat_canh(request, ten, bet, mu, rid, auto_xa)

    hub = getattr(request.app.state, "ext_hub", None)
    if hub:
        try:
            await hub.send_command(ten, "TOAST", {
                "title": "🎯 Đã giữ bàn",
                "text": f"🎯 {ten} đang giữ bàn #{rid_that} (${bet:,}). Bấm VÀO BÀN ở nick khác."
                        .replace(",", "."),
                "type": "success", "source_profile": "server", "duration": 3000,
            })
        except Exception:
            pass
    return {"ok": True, "profile": ten, "rid": rid_that, "bet": bet, "mu": mu,
            "so_lan_do": lan, "so_ban_dang_giu": len(_ds_ban(request))}


async def _chon_ban_de_vao(request, ten_vao, chu_muon=None):
    """Chọn một bàn đang giữ để ghép vào. Trả `(chu, ban, ly_do_neu_khong)`.

    Ưu tiên bàn người dùng chỉ định; không chỉ định thì lấy bàn GIỮ LÂU NHẤT mà
    kiểm tại chỗ thấy còn ghế và không có khách. Kiểm TRƯỚC khi join: vào rồi
    mới biết bàn đầy là mất một nhịp join và một lần rời bàn vô ích.
    """
    ds = _ds_ban(request)
    if not ds:
        return None, None, "Chưa có nick nào đang giữ bàn. Bấm TÌM BÀN trước."

    ung = [(t, b) for t, b in ds.items() if t.strip().lower() != ten_vao.strip().lower()]
    if chu_muon:
        ung = [(t, b) for t, b in ung if t.strip().lower() == chu_muon.strip().lower()]
        if not ung:
            return None, None, f"{chu_muon} không nằm trong danh sách nick đang giữ bàn."
    if not ung:
        return None, None, f"{ten_vao} chính là nick đang giữ bàn."

    ung.sort(key=lambda x: float(x[1].get("luc") or 0))
    vuong = []
    for chu, ban in ung:
        trang_chu = _trang_dang_mo(request, chu)
        if trang_chu is None:
            vuong.append(f"{chu}: Chrome đã đóng")
            continue
        tt = await _doc_ban(trang_chu)
        if not tt or not tt.get("co_thong_tin") or int(tt.get("so_nguoi") or 0) == 0:
            vuong.append(f"{chu}: không còn trong bàn")
            continue
        if int(tt.get("so_khach") or 0) > 0:
            vuong.append(f"{chu}: bàn có khách ({', '.join(tt.get('ten_khach') or []) or '?'})")
            continue
        if int(tt.get("so_nguoi") or 0) >= int(ban.get("mu") or 2):
            vuong.append(f"{chu}: bàn đã đủ {ban.get('mu')} người")
            continue
        return chu, ban, ""
    return None, None, "Không bàn nào còn ghế — " + "; ".join(vuong)


@router.post("/api/autoplay/vao-ban")
async def vao_ban(body: dict, request: Request):
    """MỘT account ghép vào MỘT trong các bàn đang được giữ.

    Body: profile_name, chu (tuỳ chọn — chỉ đích danh nick giữ bàn),
          auto_xa (mặc định True).

    Kiểm TRƯỚC khi vào (bàn còn ghế, không có khách) và XÁC MINH SAU khi vào
    (đúng nick giữ bàn có mặt, theo tên nhân vật in-game).
    """
    body = body or {}
    accounts = load_accounts()
    ten = resolve_profile_name(body.get("profile_name"), accounts)
    if not ten:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào.")
    chu_muon = resolve_profile_name(body.get("chu"), accounts) if body.get("chu") else None

    chu, ban, vi_sao = await _chon_ban_de_vao(request, ten, chu_muon)
    if not chu:
        raise HTTPException(status_code=409, detail=vi_sao)

    bet, mu, rid = int(ban["bet"]), int(ban["mu"]), int(ban["rid"])
    chu_cn = str(ban.get("chu_cn") or "") or _character_name(chu)
    auto_xa = bool(body.get("auto_xa", True))

    trang = await _chuan_bi(request, ten, bet, mu, auto_xa)
    try:
        kq = await eval_page(
            trang, f"() => window.__autotool_leave_then_join({rid}, {bet}, {mu})") or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi gửi lệnh vào bàn: {e}")
    if not kq.get("ok"):
        return {"ok": False, "profile": ten, "rid": rid,
                "error": f"Không gửi được lệnh vào bàn ({kq.get('reason')})."}

    tt = None
    for _ in range(12):
        await asyncio.sleep(0.25)
        tt = await _doc_ban(trang)
        if tt and tt.get("co_thong_tin") and int(tt.get("so_nguoi") or 0) >= 2:
            break

    # XÁC MINH BẰNG TÊN NHÂN VẬT: server tự xếp chỗ ("Chống Vây") nên gửi đúng
    # rid vẫn có thể rơi vào bàn con khác. Đúng bàn = thấy tên nhân vật của nick
    # giữ bàn ngồi cùng.
    ten_trong_ban = [str(x) for x in ((tt or {}).get("ten_dong_doi") or [])] \
        + [str(x) for x in ((tt or {}).get("ten_khach") or [])]
    dung_chu = bool(chu_cn) and any(x.strip().lower() == chu_cn.strip().lower()
                                    for x in ten_trong_ban)
    so_nguoi = int((tt or {}).get("so_nguoi") or 0)
    so_khach = int((tt or {}).get("so_khach") or 0)

    if not dung_chu:
        log.warning("VÀO BÀN: %s vào bàn #%s nhưng KHÔNG thấy %s (%s) — thấy: %s",
                    ten, rid, chu, chu_cn or "chưa có tên in-game",
                    ", ".join(ten_trong_ban) or "không ai")
        return {
            "ok": False, "profile": ten, "rid": rid, "so_nguoi": so_nguoi,
            "chu_ban": chu, "trong_ban": ten_trong_ban,
            "error": (f"Vào bàn #{rid} nhưng không thấy {chu}"
                      + (f" ({chu_cn})" if chu_cn
                         else " — nick này chưa có tên in-game, chạy Check Live")
                      + ". Server có thể đã xếp sang bàn con khác; bấm TÌM BÀN lại."),
        }

    await eval_page(trang, js_giu_ban(auto_xa, bet, mu, dong_doi=_ten_dong_doi(ten)))
    # Ghép xong thì bàn này không còn là chỗ trống để mời nữa.
    _xoa_ban(request, chu)
    _dung_canh(request, chu)
    log.info("VÀO BÀN: ✅ %s đã vào bàn #%s ($%s) cùng %s (%s) — %d người, %d khách. "
             "Còn %d bàn đang giữ.",
             ten, rid, bet, chu, chu_cn, so_nguoi, so_khach, len(_ds_ban(request)))
    return {"ok": True, "profile": ten, "rid": rid, "bet": bet, "mu": mu,
            "so_nguoi": so_nguoi, "co_khach_la": so_khach > 0,
            "chu_ban": chu, "chu_ban_cn": chu_cn,
            "so_ban_dang_giu": len(_ds_ban(request))}


@router.post("/api/autoplay/kiem-ban")
async def kiem_ban(body: dict, request: Request):
    """Bàn mà profile này đang ngồi: mấy người, ai là đồng đội, ai là khách.

    Người dùng hỏi rõ "có cơ chế kiểm tra cho tôi có khách lạ không" — đây là
    nó, đọc thẳng từ trang nên luôn là hiện trạng, không phải cache.
    """
    body = body or {}
    ten = resolve_profile_name(body.get("profile_name"), load_accounts())
    if not ten:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào.")
    trang = _trang_dang_mo(request, ten)
    if trang is None:
        raise HTTPException(status_code=400, detail=f"{ten} chưa mở Chrome.")
    tt = await _doc_ban(trang)
    if tt is None:
        raise HTTPException(status_code=500, detail=f"Không đọc được trạng thái bàn của {ten}.")
    return {"ok": True, "profile": ten, **tt}


@router.get("/api/autoplay/ban-chung")
async def xem_ban_chung(request: Request):
    """Danh sách MỌI bàn đang được giữ (nhiều nick giữ song song được)."""
    ds = _ds_ban(request)
    ban = [{"chu": t, "chu_cn": b.get("chu_cn") or "", "rid": b["rid"],
            "bet": b["bet"], "mu": b["mu"],
            "tuoi_giay": round(time.time() - float(b["luc"]), 1)}
           for t, b in sorted(ds.items(), key=lambda x: float(x[1].get("luc") or 0))]
    return {"co": bool(ban), "so_ban": len(ban), "ban": ban}


@router.post("/api/autoplay/ban-chung/xoa")
async def xoa_ban_chung(body: dict | None = None, request: Request = None):
    """Xoá một bàn (truyền profile_name) hoặc tất cả, và dừng vòng canh."""
    body = body or {}
    ten = resolve_profile_name(body.get("profile_name"), load_accounts()) \
        if body.get("profile_name") else None
    if ten:
        _xoa_ban(request, ten)
        _dung_canh(request, ten)
        log.info("BÀN CHUNG: đã xoá bàn của %s.", ten)
    else:
        request.app.state.ban_dang_giu = {}
        _dung_canh(request)
        log.info("BÀN CHUNG: đã xoá TẤT CẢ bàn đang giữ.")
    return {"ok": True, "con_lai": len(_ds_ban(request))}


@router.post("/api/autoplay/ngat-sau-van")
async def ngat_sau_van(body: dict, request: Request):
    """Ngắt kết nối extension cho các nick chỉ định — dùng sau khi xả xong.

    Tách thành endpoint riêng thay vì tự động: người dùng có thể còn muốn chạy
    thêm ván nữa, tự quyết lúc nào thì buông tay là đúng hơn.
    """
    body = body or {}
    accounts = load_accounts()
    ten = [resolve_profile_name(t, accounts)
           for t in (body.get("profile_names") or []) if str(t or "").strip()]
    if not ten:
        ten = list(_ds_ban(request).keys())
    if not ten:
        raise HTTPException(status_code=400, detail="Không biết ngắt cho profile nào.")
    xong = [t for t in ten if await ngat_extension(request, t)]
    return {"ok": True, "profiles": xong}

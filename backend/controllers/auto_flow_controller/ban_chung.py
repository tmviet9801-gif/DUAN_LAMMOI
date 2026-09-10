"""XÉ LẺ QUY TRÌNH: một account TÌM BÀN trống, account khác bấm VÀO BÀN đó.

Yêu cầu của người dùng (11/09/2026), lấy theo cách làm của công cụ Sunwin
(`control/control.py`): ở đó mỗi kết nối là một hàng ngang có nút "Tạo phòng" /
"Tìm phòng" / "Dừng"; ai tạo phòng xong thì bàn đó thành BÀN CHUNG
(`shared_room`) và những máy khác bấm "Tìm phòng" là vào thẳng bàn ấy.

Khác luồng `find-and-match-ws` cũ: ở đó phải tích sẵn account chính + account
phụ rồi chạy đồng thời, không chen ngang được. Ở đây hai bước rời nhau, bấm lúc
nào cũng được, và số account vào bàn là tuỳ ý (1, 2 hay 3 nick).

SAU KHI VÀO ĐỦ, KHÔNG CÓ GÌ THÊM Ở PYTHON: extension tự bắt tay theo luật
"chỉ xả với đồng đội" (Sẵn sàng / Bắt đầu / đánh bài) — cùng đúng cơ chế mà nút
Tự đánh dùng. Bàn có người ngoài thì extension im hoàn toàn.

Xong ván, nếu người dùng bật `ngat_sau_van` thì app NGẮT kết nối extension cho
các nick trong bàn, để từ đó không lệnh nào của tool chạm vào Chrome nữa.
"""
import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from models.config_model import load_accounts
from core.page_world import eval_page

from .constants import BET_RATIOS, FIXED_TABLE_RIDS, kiem_so_cho
from .context import resolve_profile_name
from .join_js import JS_DOC_BAN, js_cai_dat_join
from .ket_noi import ngat_extension, noi_extension
from .kich_hoat import js_giu_ban, js_kich_hoat

log = logging.getLogger("auto_flow_controller")
router = APIRouter()

# Bao lâu coi như bàn chung đã cũ (người giữ có thể đã rời từ đời nào).
HAN_BAN_CHUNG = 900.0


def _trang(request, ten):
    manager = getattr(request.app.state, "manager", None)
    if not manager or not getattr(manager, "sessions", None):
        return None
    from services.page_pool import PagePool
    try:
        return PagePool(manager).peek(ten)
    except Exception:
        return None


def _lay_ban_chung(request):
    bc = getattr(request.app.state, "ban_chung", None)
    if not isinstance(bc, dict) or not bc.get("rid"):
        return None
    if time.time() - float(bc.get("luc") or 0) > HAN_BAN_CHUNG:
        return None
    return bc


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
    """Mở cổng kết nối, cài hàm join, đặt trang vào chế độ dò bàn."""
    trang = _trang(request, ten)
    if trang is None:
        raise HTTPException(status_code=400,
                            detail=f"{ten} chưa mở Chrome. Mở Chrome rồi bấm lại.")
    await noi_extension(request, ten)
    await eval_page(trang, js_cai_dat_join())
    # Cổng kích hoạt MỞ + vai anchor: gặp bàn có người ngoài thì extension tự
    # rời, đúng thứ vòng dò cần.
    await eval_page(trang, js_kich_hoat("anchor", auto_xa, _ten_dong_doi(ten), bet, mu))
    return trang


@router.post("/api/autoplay/tim-ban")
async def tim_ban(body: dict, request: Request):
    """MỘT account dò cho tới khi ngồi được vào một bàn TRỐNG, rồi giữ bàn.

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

    ly_do_cuoi = "chưa dò xong"
    for lan in range(1, so_lan + 1):
        try:
            kq = await eval_page(
                trang,
                f"() => window.__autotool_leave_then_join({rid}, {bet}, {mu})") or {}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi gửi lệnh vào bàn: {e}")
        if not kq.get("ok"):
            ly_do_cuoi = str(kq.get("reason") or "join_that_bai")
            await asyncio.sleep(1.2)
            continue

        # Chờ khung cmd 202 tả lại bàn vừa ngồi.
        tt = None
        for _ in range(10):
            await asyncio.sleep(0.25)
            try:
                tt = await eval_page(trang, JS_DOC_BAN)
            except Exception:
                tt = None
            if isinstance(tt, dict) and tt.get("co_thong_tin"):
                break
        if not isinstance(tt, dict) or not tt.get("co_thong_tin"):
            ly_do_cuoi = "không đọc được trạng thái bàn"
            continue

        trong = int(tt.get("so_nguoi") or 0) <= 1 and not tt.get("co_khach_la")
        if not trong:
            ly_do_cuoi = "bàn có người" if tt.get("co_khach_la") else "bàn đã đủ người"
            log.info("TÌM BÀN: [%s] lần %d — %s, dò tiếp.", ten, lan, ly_do_cuoi)
            await asyncio.sleep(1.0)
            continue

        # Ngồi được bàn trống -> giữ bàn và ghi làm BÀN CHUNG.
        rid_that = int(tt.get("rid") or rid)
        await eval_page(trang, js_giu_ban(auto_xa, bet, mu))
        request.app.state.ban_chung = {
            "rid": rid_that, "bet": bet, "mu": mu, "chu": ten, "luc": time.time(),
        }
        log.info("TÌM BÀN: >>> %s ĐÃ GIỮ BÀN TRỐNG #%s ($%s) sau %d lần dò. <<<",
                 ten, rid_that, bet, lan)
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
                "so_lan_do": lan}

    log.warning("TÌM BÀN: %s dò %d lần chưa gặp bàn trống (%s).", ten, so_lan, ly_do_cuoi)
    return {"ok": False, "profile": ten, "error": f"Dò {so_lan} lần chưa gặp bàn trống ({ly_do_cuoi}).",
            "so_lan_do": so_lan}


@router.post("/api/autoplay/vao-ban")
async def vao_ban(body: dict, request: Request):
    """MỘT account vào thẳng BÀN CHUNG mà nick khác đang giữ.

    Body: profile_name, auto_xa (mặc định True). Mức cược / rid lấy từ bàn chung.
    """
    body = body or {}
    ten = resolve_profile_name(body.get("profile_name"), load_accounts())
    if not ten:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào.")
    bc = _lay_ban_chung(request)
    if not bc:
        raise HTTPException(status_code=409,
                            detail="Chưa có bàn chung. Bấm TÌM BÀN ở một nick trước.")
    if str(bc.get("chu") or "").strip().lower() == ten.strip().lower():
        raise HTTPException(status_code=400, detail=f"{ten} chính là nick đang giữ bàn.")

    bet, mu, rid = int(bc["bet"]), int(bc["mu"]), int(bc["rid"])
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

    # Chờ ngồi xuống rồi chuyển sang chế độ xả với đồng đội.
    tt = None
    for _ in range(12):
        await asyncio.sleep(0.25)
        try:
            tt = await eval_page(trang, JS_DOC_BAN)
        except Exception:
            tt = None
        if isinstance(tt, dict) and tt.get("co_thong_tin") and int(tt.get("so_nguoi") or 0) >= 2:
            break
    await eval_page(trang, js_giu_ban(auto_xa, bet, mu))

    so_nguoi = int((tt or {}).get("so_nguoi") or 0)
    co_khach = bool((tt or {}).get("co_khach_la"))
    log.info("VÀO BÀN: %s đã vào bàn #%s ($%s) — %d người, khách lạ=%s.",
             ten, rid, bet, so_nguoi, co_khach)
    return {"ok": True, "profile": ten, "rid": rid, "bet": bet, "mu": mu,
            "so_nguoi": so_nguoi, "co_khach_la": co_khach,
            "chu_ban": bc.get("chu")}


@router.get("/api/autoplay/ban-chung")
async def xem_ban_chung(request: Request):
    bc = _lay_ban_chung(request)
    if not bc:
        return {"co": False}
    return {"co": True, "rid": bc["rid"], "bet": bc["bet"], "mu": bc["mu"],
            "chu": bc["chu"], "tuoi_giay": round(time.time() - float(bc["luc"]), 1)}


@router.post("/api/autoplay/ban-chung/xoa")
async def xoa_ban_chung(request: Request):
    request.app.state.ban_chung = None
    log.info("BÀN CHUNG: đã xoá theo lệnh người dùng.")
    return {"ok": True}


@router.post("/api/autoplay/ngat-sau-van")
async def ngat_sau_van(body: dict, request: Request):
    """Ngắt kết nối extension cho các nick đang ở bàn chung — dùng sau khi xả.

    Tách thành endpoint riêng thay vì tự động: người dùng có thể còn muốn chạy
    thêm ván nữa, tự quyết lúc nào thì buông tay là đúng hơn.
    """
    body = body or {}
    accounts = load_accounts()
    ten = [resolve_profile_name(t, accounts)
           for t in (body.get("profile_names") or []) if str(t or "").strip()]
    if not ten:
        bc = _lay_ban_chung(request)
        if bc:
            ten = [bc["chu"]]
    if not ten:
        raise HTTPException(status_code=400, detail="Không biết ngắt cho profile nào.")
    xong = [t for t in ten if await ngat_extension(request, t)]
    return {"ok": True, "profiles": xong}

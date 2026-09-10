"""Nút TỰ ĐÁNH: bật bộ xả trên MỘT profile mà không chạy gom bàn.

Yêu cầu (10/09/2026): "khi tôi không chạy quy trình này mà vào 1 phòng thủ
công với 1 người chơi khác sẽ thực hiện quy trình xả bài giống như đang làm".

Đây chính là chế độ GIỮ BÀN (kich_hoat.js_giu_ban) mà nick chính đã chạy thật
sau ván gom bàn — cùng cổng kích hoạt, cùng bộ xả, cùng các lớp gác trong
extension — chỉ khác cách vào: không có bàn mục tiêu, không có đồng đội. Hai
điểm khác được đặt ở `js_tu_danh`, không đụng luật chọn nước:
  - mức cược mục tiêu = 0: extension không tự out vì "sai mức cược" — người
    dùng chọn bàn nào là quyền của họ;
  - mình có thể là KHÁCH trong bàn người khác: extension đọc cờ chủ bàn `C`
    của khung 202 để biết phải gửi Sẵn sàng (khách) hay Bắt đầu (chủ).

Tắt = `dong_luot_chay` trên đúng trang đó: đóng cổng, KHÔNG rời bàn, KHÔNG
đặt cờ Dừng — người dùng tắt tự đánh để tự chơi tiếp, không phải để out.
Nút "⏹ Dừng" chung vẫn tắt được (cùng cổng), nhưng Dừng thì rời bàn.

Trạng thái BẬT/TẮT trả cho giao diện đọc TỪ TRANG (JS_DOC_TU_DANH), không phải
từ danh sách đã bấm: trang tải lại là extension khởi tạo lại
`__AUTOTOOL_ENGAGED = false`, chế độ im lặng tắt trong khi nút vẫn báo BẬT.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

from models.config_model import load_accounts
from core.page_world import eval_page

from .context import resolve_profile_name
from .kich_hoat import JS_DOC_TU_DANH, js_tu_danh
from .lobby import dong_luot_chay

log = logging.getLogger("auto_flow_controller")
router = APIRouter()


def _tap_tu_danh(request):
    tap = getattr(request.app.state, "tu_danh_profiles", None)
    if tap is None:
        tap = set()
        request.app.state.tu_danh_profiles = tap
    return tap


def _trang_cua(request, ten):
    """Trang Chrome ĐANG MỞ của profile; không mở mới.

    Người dùng phải đang ở trong game rồi mới bật Tự đánh — mở Chrome hộ họ
    ở đây là làm một việc không ai yêu cầu trên tài khoản thật.
    """
    manager = getattr(request.app.state, "manager", None)
    if not manager or not getattr(manager, "sessions", None):
        return None
    from services.page_pool import PagePool
    try:
        return PagePool(manager).peek(ten)
    except Exception:
        return None


def _dang_gom_ban(request, ten):
    """Profile đang thuộc một lượt gom bàn còn chạy (matching.py ghi danh vào
    `gom_ban_profiles` lúc bắt đầu và gỡ ở `finally`)."""
    dang_chay = getattr(request.app.state, "gom_ban_profiles", None) or set()
    return ten in dang_chay


def _da_bat(tt, auto_xa):
    return (isinstance(tt, dict) and bool(tt.get("tu_danh")) and bool(tt.get("engaged"))
            and bool(tt.get("auto_xa")) == bool(auto_xa))


@router.post("/api/autoplay/tu-danh/bat")
async def tu_danh_bat(body: dict, request: Request):
    """Bật Tự đánh cho MỘT profile đang mở Chrome.

    Body: profile_name (bắt buộc), auto_xa (mặc định True),
          auto_start_guest_ss (mặc định True — ô "Bắt đầu nếu khách SS": tắt
          thì tool không tự Sẵn sàng/Bắt đầu, chỉ tự đánh khi ván đã chạy).
    """
    body = body or {}
    ten = resolve_profile_name(body.get("profile_name"), load_accounts())
    if not ten:
        raise HTTPException(status_code=400,
                            detail="Chưa chọn profile nào. Tích 1 profile trên bảng rồi bấm lại.")
    if _dang_gom_ban(request, ten):
        raise HTTPException(status_code=409,
                            detail=f"{ten} đang trong lượt Gom bàn — bấm Dừng trước, hoặc chờ lượt xong.")
    trang = _trang_cua(request, ten)
    if trang is None:
        raise HTTPException(status_code=400,
                            detail=f"{ten} chưa mở Chrome. Mở Chrome, vào bàn rồi bấm Tự đánh.")

    auto_xa = bool(body.get("auto_xa", True))
    auto_start = bool(body.get("auto_start_guest_ss", True))

    # ĐẶT rồi ĐỌC LẠI, tối đa hai lần — nguyên tắc của kich_hoat.py: không tin
    # lần đặt trước. Đọc lại vẫn sai thì báo lỗi rõ, không ghi danh.
    tt = None
    hanh_dong = None
    for _ in range(2):
        try:
            # js_tu_danh còn KIỂM NGAY bàn đang ngồi (người dùng có thể bấm lúc
            # đã ngồi trong bàn người khác) và trả hành động đã chọn.
            hanh_dong = await eval_page(trang, js_tu_danh(auto_xa, auto_start))
            tt = await eval_page(trang, JS_DOC_TU_DANH)
        except Exception as e:
            raise HTTPException(status_code=500,
                                detail=f"Không đặt được chế độ Tự đánh trên trang {ten}: {e}")
        if _da_bat(tt, auto_xa):
            break
    if not _da_bat(tt, auto_xa):
        raise HTTPException(
            status_code=500,
            detail=(f"Đặt xong nhưng đọc lại trang {ten} vẫn chưa bật "
                    f"(extension chưa nạp? trang đang tải lại?): {tt}"))

    _tap_tu_danh(request).add(ten)
    trong_ban = bool(tt.get("trong_ban"))
    so_nguoi = int(tt.get("so_nguoi") or 0)
    log.info("TỰ ĐÁNH: bật cho %s (auto_xa=%s, tự SS/Bắt đầu=%s, đang trong bàn=%s, %s người, "
             "kiểm ngay -> %s).", ten, auto_xa, auto_start, trong_ban, so_nguoi, hanh_dong)

    hub = getattr(request.app.state, "ext_hub", None)
    if hub:
        try:
            await hub.send_command(ten, "TOAST", {
                "title": "🤖 Tự đánh",
                "text": ("🤖 TỰ ĐÁNH BẬT: là khách thì tự Sẵn sàng, là chủ bàn thì khách "
                         "Sẵn sàng là tự Bắt đầu; xả xong ở lại bàn."),
                "type": "active", "source_profile": "server", "duration": 3000,
            })
        except Exception:
            pass
    return {"ok": True, "profile": ten, "auto_xa": auto_xa,
            "auto_start_guest_ss": auto_start, "trong_ban": trong_ban, "so_nguoi": so_nguoi,
            "hanh_dong_ngay": hanh_dong if isinstance(hanh_dong, str) else None}


@router.post("/api/autoplay/tu-danh/tat")
async def tu_danh_tat(body: dict, request: Request):
    """Tắt Tự đánh: đóng cổng trên đúng trang đó, KHÔNG rời bàn, KHÔNG đặt cờ Dừng."""
    body = body or {}
    ten = resolve_profile_name(body.get("profile_name"), load_accounts())
    if not ten:
        raise HTTPException(status_code=400, detail="Thiếu profile_name.")
    trang = _trang_cua(request, ten)
    if trang is not None:
        await dong_luot_chay({ten: trang}, "người dùng tắt Tự đánh")
    _tap_tu_danh(request).discard(ten)
    log.info("TỰ ĐÁNH: tắt cho %s (vẫn ngồi nguyên bàn, không đặt cờ Dừng).", ten)
    return {"ok": True, "profile": ten, "van_trong_ban": trang is not None}


@router.get("/api/autoplay/tu-danh/status")
async def tu_danh_status(request: Request):
    """Trạng thái THẬT đọc từ trang. Trang nào đã rớt chế độ (tải lại, đã Dừng,
    Chrome đóng) thì gỡ khỏi danh sách và trả trong `da_roi` để giao diện báo."""
    tap = _tap_tu_danh(request)
    con, roi = [], []
    for ten in sorted(tap):
        trang = _trang_cua(request, ten)
        tt = None
        if trang is not None:
            try:
                tt = await eval_page(trang, JS_DOC_TU_DANH)
            except Exception:
                tt = None
        if isinstance(tt, dict) and tt.get("tu_danh") and tt.get("engaged"):
            con.append({"profile": ten,
                        "trong_ban": bool(tt.get("trong_ban")),
                        "so_nguoi": int(tt.get("so_nguoi") or 0),
                        "auto_xa": bool(tt.get("auto_xa"))})
        else:
            roi.append(ten)
    for ten in roi:
        tap.discard(ten)
        log.warning("TỰ ĐÁNH: %s đã rớt chế độ (trang tải lại / đã Dừng / Chrome đóng) -> gỡ khỏi danh sách.", ten)
    return {"profiles": [x["profile"] for x in con], "chi_tiet": con, "da_roi": roi}

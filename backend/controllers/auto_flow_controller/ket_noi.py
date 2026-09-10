"""Cổng KẾT NỐI giữa app và extension — nút Kết nối / Ngắt trên giao diện.

Yêu cầu của người dùng (11/09/2026): "khi bấm Dừng thì các tài khoản sẽ dừng
hết tất cả auto và thao tác như người dùng; có thể hiểu đóng ws lại và tắt
connect với extension lại", và "thêm 1 nút connect với extension trên giao
diện, khi bấm sẽ connect ws với app và bấm đóng sẽ ngắt kết nối để Chrome bình
thường".

HAI ĐƯỜNG DÂY, ĐỪNG NHẦM:
  - WebSocket của GAME (Simms) — tuyệt đối KHÔNG đụng. Đóng nó là người dùng
    văng khỏi bàn, mất cược.
  - WebSocket giữa EXTENSION và app (`/ws/bridge`) — đây là thứ được ngắt. Ngắt
    rồi thì app không gửi được lệnh nào xuống Chrome nữa.

VÌ SAO PHẢI GỌI QUA PLAYWRIGHT: sau khi ngắt, không còn WS để app gọi extension.
Đường duy nhất còn lại là Playwright bơm `window.postMessage` vào trang; content
script nghe được và bảo background nối lại. Nên cả hai chiều đều đi lối này cho
nhất quán.
"""
import json
import logging

from fastapi import APIRouter, HTTPException, Request

from models.config_model import load_accounts
from core.page_world import eval_page

from .context import resolve_profile_name

log = logging.getLogger("auto_flow_controller")
router = APIRouter()


def _trang(request, ten):
    """Trang Chrome ĐANG MỞ của profile; không mở mới."""
    manager = getattr(request.app.state, "manager", None)
    if not manager or not getattr(manager, "sessions", None):
        return None
    from services.page_pool import PagePool
    try:
        return PagePool(manager).peek(ten)
    except Exception:
        return None


async def _ban(request, ten, bat):
    """Bơm lệnh nối/ngắt vào trang. Trả True nếu bơm được."""
    trang = _trang(request, ten)
    if trang is None:
        return False
    loai = "AUTOTOOL_HUB_CONNECT" if bat else "AUTOTOOL_HUB_DISCONNECT"
    try:
        await eval_page(trang, f"""() => {{
            window.postMessage({{ type: {json.dumps(loai)}, profile_name: {json.dumps(ten)} }}, "*");
        }}""")
        return True
    except Exception as e:
        log.warning("kết nối extension: không bơm được lệnh cho %s: %s", ten, e)
        return False


async def noi_extension(request, ten):
    """Nối lại cổng cho MỘT profile. Dùng từ các luồng tự động trước khi chạy."""
    ok = await _ban(request, ten, True)
    if ok:
        log.info("kết nối extension: đã yêu cầu %s NỐI LẠI với app.", ten)
    return ok


async def ngat_extension(request, ten):
    """Ngắt cổng cho MỘT profile — Chrome chạy như người dùng tự thao tác."""
    ok = await _ban(request, ten, False)
    if ok:
        log.info("kết nối extension: đã yêu cầu %s NGẮT khỏi app.", ten)
    return ok


def _danh_sach(body, accounts):
    ten = []
    for x in (body.get("profile_names") or []):
        x = str(x or "").strip()
        if x:
            ten.append(x)
    mot = str(body.get("profile_name") or "").strip()
    if mot:
        ten.append(mot)
    return [resolve_profile_name(t, accounts) for t in ten]


def _tat_ca_dang_mo(request):
    manager = getattr(request.app.state, "manager", None)
    ra = []
    for s in list(getattr(manager, "sessions", {}).values()) if manager else []:
        ten = (s.account or {}).get("name")
        if ten:
            ra.append(ten)
    return ra


@router.post("/api/extension/ngat")
async def extension_ngat(body: dict, request: Request):
    """Ngắt kết nối extension. Không truyền tên -> ngắt mọi profile đang mở."""
    body = body or {}
    ten = _danh_sach(body, load_accounts()) or _tat_ca_dang_mo(request)
    if not ten:
        raise HTTPException(status_code=400, detail="Không có profile nào đang mở Chrome.")
    xong = [t for t in ten if await ngat_extension(request, t)]
    return {"ok": True, "profiles": xong, "khong_bom_duoc": [t for t in ten if t not in xong]}


@router.post("/api/extension/noi")
async def extension_noi(body: dict, request: Request):
    """Nối lại kết nối extension. Không truyền tên -> nối mọi profile đang mở."""
    body = body or {}
    ten = _danh_sach(body, load_accounts()) or _tat_ca_dang_mo(request)
    if not ten:
        raise HTTPException(status_code=400, detail="Không có profile nào đang mở Chrome.")
    xong = [t for t in ten if await noi_extension(request, t)]
    return {"ok": True, "profiles": xong, "khong_bom_duoc": [t for t in ten if t not in xong]}


@router.get("/api/extension/trang-thai")
async def extension_trang_thai(request: Request):
    """Profile nào đang mở Chrome, profile nào còn nối WS với app.

    `dang_noi` đọc từ Hub (danh sách socket sống), không phải từ lần bấm trước:
    trang tải lại hay Chrome đóng là trạng thái đổi mà không ai báo.
    """
    hub = getattr(request.app.state, "ext_hub", None)
    ra = []
    for ten in _tat_ca_dang_mo(request):
        noi = False
        if hub:
            try:
                noi = bool(hub.is_connected(ten))
            except Exception:
                noi = False
        ra.append({"profile": ten, "dang_noi": noi})
    return {"profiles": ra, "tong": len(ra), "dang_noi": sum(1 for x in ra if x["dang_noi"])}

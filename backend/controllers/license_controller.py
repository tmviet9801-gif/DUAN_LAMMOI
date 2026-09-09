"""Controller: license — kích hoạt / trạng thái / hủy / sinh (owner)."""
import logging

from fastapi import APIRouter, HTTPException

import license as lic

log = logging.getLogger("license_controller")
router = APIRouter()


@router.get("/api/license/status")
async def license_status():
    st = lic.status()
    return st


@router.post("/api/license/activate")
async def license_activate(body: dict):
    key = (body.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Thiếu license key")
    result = lic.activate(key)
    if not result["valid"]:
        reason = {
            "invalid_key": "Key không hợp lệ",
            "wrong_machine": "Key không dành cho máy này",
            "expired": "Key đã hết hạn",
        }.get(result.get("reason"), "Không kích hoạt được")
        raise HTTPException(status_code=400, detail=reason)

    # Chữ ký hợp lệ chưa chắc key còn hiệu lực: hỏi máy chủ ngay để bắt
    # trường hợp key đã bị thu hồi mà chữ ký vẫn đúng tới ngày hết hạn.
    if lic.server_enabled():
        try:
            await lic.check_online(key)
        except Exception:
            log.exception("kiểm tra online khi kích hoạt thất bại")
        st = lic.status()
        if not st.get("valid"):
            lic.deactivate()
            raise HTTPException(
                status_code=400,
                detail=st.get("message") or "Key không còn hiệu lực",
            )
        return st

    return result


@router.post("/api/license/recheck")
async def license_recheck():
    """Hỏi lại máy chủ ngay (nút 'Kiểm tra lại' trong app)."""
    if not lic.server_enabled():
        return {"ok": False, "error": "disabled", **lic.status()}
    result = await lic.check_online()
    return {"ok": result.get("ok", False), "error": result.get("error"), **lic.status()}


@router.post("/api/license/deactivate")
async def license_deactivate():
    return lic.deactivate()


# ĐÃ BỎ: endpoint POST /api/license/make (sinh license ngay trong app).
#
# Việc cấp license chuyển sang dự án quản trị riêng. App chỉ còn NHẬP và KIỂM
# license: đúng mã máy, còn hạn, và mở được bao nhiêu profile.
#
# Không chỉ là dọn giao diện: chừng nào app còn tự ký được key thì ai unpack
# được exe cũng tự cấp key vô hạn cho mình — đúng lỗ hổng mà bản Ed25519 sinh
# ra để bịt. `lic.make_key` vẫn còn trong backend/license.py vì bộ kiểm thử
# dùng nó để dựng key thử; nhưng không còn đường nào từ mạng gọi tới nó.


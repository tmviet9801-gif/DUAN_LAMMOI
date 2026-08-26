"""Controller: license — kích hoạt / trạng thái / hủy."""
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
    return result


@router.post("/api/license/deactivate")
async def license_deactivate():
    return lic.deactivate()

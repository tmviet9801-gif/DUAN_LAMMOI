"""Controller: license — kích hoạt / trạng thái / hủy / sinh (owner)."""
import logging

from fastapi import APIRouter, HTTPException

import license as lic
from platform_config import OWNER_TOKEN

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


@router.post("/api/license/make")
async def license_make(body: dict):
    """Sinh license key cho khách (cần owner_token)."""
    token = (body.get("owner_token") or "").strip()
    if not token or token != OWNER_TOKEN:
        raise HTTPException(status_code=403, detail="Sai token — chỉ owner mới sinh được key")
    machine_id = (body.get("machine_id") or "").strip()
    if not machine_id:
        raise HTTPException(status_code=400, detail="Thiếu machine_id của máy khách")
    days = int(body.get("days", 30))
    max_tabs = int(body.get("max_tabs", 10))
    features = (body.get("features") or "game").strip()
    if days < 1 or days > 3650:
        raise HTTPException(status_code=400, detail="Số ngày không hợp lệ (1-3650)")
    if max_tabs < 1 or max_tabs > 50:
        raise HTTPException(status_code=400, detail="Số tab không hợp lệ (1-50)")
    key = lic.make_key(machine_id, days, max_tabs, features)
    log.info("owner generated license for %s (%d days, %d tabs)", machine_id, days, max_tabs)
    return {
        "key": key,
        "machine_id": machine_id,
        "days": days,
        "max_tabs": max_tabs,
        "expires_at": lic.parse_key(key)["expiry"] if lic.parse_key(key) else 0,
    }
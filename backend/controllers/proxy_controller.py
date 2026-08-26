"""Controller: quản lý proxy (lưu, áp dụng cho profile)."""
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import config_model
from models.config_model import load_accounts, save_accounts
from models.proxy_model import parse_proxy

log = logging.getLogger("proxy_controller")
router = APIRouter()


def _proxies_file():
    return config_model.DATA_DIR / "proxies.json"


def _load_proxies() -> list:
    try:
        data = json.loads(_proxies_file().read_text(encoding="utf-8"))
        return [p for p in data.get("proxies", []) if p]
    except Exception:
        return []


def _save_proxies(proxies: list):
    _proxies_file().write_text(
        json.dumps({"proxies": proxies}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _clean(proxies) -> list:
    seen = set()
    out = []
    for p in proxies or []:
        p = (p or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


@router.get("/api/proxies")
async def get_proxies():
    return {"proxies": _load_proxies()}


@router.post("/api/proxies")
async def save_proxies(body: dict):
    proxies = _clean(body.get("proxies", []))
    _save_proxies(proxies)
    log.info("saved %d proxies", len(proxies))
    return {"ok": True, "count": len(proxies)}


class ApplyIn(BaseModel):
    proxies: list[str] = []


@router.post("/api/proxies/apply")
async def apply_proxies(body: ApplyIn):
    """Áp proxy (số lượng có hạn) cho các profile chưa có proxy, theo thứ tự."""
    proxies = _clean(body.proxies)
    if not proxies:
        raise HTTPException(status_code=400, detail="Không có proxy để áp")
    accounts = load_accounts()
    free = [a for a in accounts if not a.get("proxy")]
    applied = 0
    for i, acc in enumerate(free):
        if i >= len(proxies):
            break
        acc["proxy"] = proxies[i]
        applied += 1
    save_accounts(accounts)
    log.info("applied %d proxies to %d profiles", applied, len(free))
    return {"applied": applied, "free_profiles": len(free)}


@router.post("/api/proxies/validate")
async def validate_proxies(body: ApplyIn):
    """Validate format từng proxy (không check mạng). Trả list hợp lệ."""
    valid = []
    invalid = []
    for p in _clean(body.proxies):
        if parse_proxy(p):
            valid.append(p)
        else:
            invalid.append(p)
    return {"valid": valid, "invalid": invalid}

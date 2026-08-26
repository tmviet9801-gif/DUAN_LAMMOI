"""Controller: mở/đóng/xếp lưới cửa sổ trình duyệt."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from models.config_model import load_accounts
from services.account_service import ensure_account_fingerprints

log = logging.getLogger("browser_controller")
router = APIRouter()


class OpenIn(BaseModel):
    count: Optional[int] = None
    account_ids: Optional[list[str]] = None


class CloseIn(BaseModel):
    session_ids: Optional[list[str]] = None


def _available_slots(manager) -> tuple[int, int]:
    """Trả (max_tabs, slots còn lại). max_tabs từ license (0 = chưa kích hoạt)."""
    import license as lic

    max_tabs = lic.max_tabs()
    current = len(manager.sessions)
    return max_tabs, max(0, max_tabs - current)


@router.post("/api/browser/open")
async def open_browser(body: OpenIn, request: Request):
    manager = request.app.state.manager
    max_tabs, slots = _available_slots(manager)
    if max_tabs <= 0:
        raise HTTPException(status_code=403, detail="License chưa kích hoạt hoặc hết hạn")
    if slots <= 0:
        raise HTTPException(status_code=429, detail=f"Đã đạt giới hạn {max_tabs} tab")

    if body.account_ids is not None:
        if len(body.account_ids) > slots:
            raise HTTPException(
                status_code=429,
                detail=f"Vượt giới hạn: còn {slots}/{max_tabs} tab trống",
            )
    else:
        count = body.count or 0
        body.count = min(count, slots)

    accounts = ensure_account_fingerprints(load_accounts())
    ids = await manager.open_sessions(
        count=body.count, account_ids=body.account_ids, accounts=accounts
    )
    return {"session_ids": ids}


@router.post("/api/browser/close")
async def close_browser(body: CloseIn, request: Request):
    manager = request.app.state.manager
    if body.session_ids:
        for sid in body.session_ids:
            await manager.close_session(sid)
    else:
        await manager.close_all()
    return {"ok": True}


@router.post("/api/browser/layout")
async def apply_layout(request: Request):
    manager = request.app.state.manager
    n = await manager.apply_layout()
    return {"count": n}


@router.get("/api/sessions")
async def get_sessions(request: Request):
    return request.app.state.manager.states()

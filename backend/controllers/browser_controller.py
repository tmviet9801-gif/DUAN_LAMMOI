"""Controller: mở/đóng/xếp lưới cửa sổ trình duyệt."""
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from models.config_model import load_accounts

log = logging.getLogger("browser_controller")
router = APIRouter()


class OpenIn(BaseModel):
    count: Optional[int] = None
    account_ids: Optional[list[str]] = None


class CloseIn(BaseModel):
    session_ids: Optional[list[str]] = None


class EvalIn(BaseModel):
    session_id: Optional[str] = None
    account_id: Optional[str] = None
    profile_name: Optional[str] = None
    name: Optional[str] = None
    js: str


class ClickIn(BaseModel):
    session_id: Optional[str] = None
    account_id: Optional[str] = None
    profile_name: Optional[str] = None
    name: Optional[str] = None
    x: int
    y: int


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

    accounts = load_accounts()
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


@router.post("/api/browser/screenshot")
async def browser_screenshot(body: dict, request: Request):
    """Chụp màn hình page của 1 session để xem trạng thái (debug/drive browser)."""
    import base64
    from models.config_model import DATA_DIR

    account_id = (body.get("account_id") or "").strip()
    session_id = (body.get("session_id") or "").strip()
    name = (body.get("name") or body.get("profile_name") or "").strip()
    manager = request.app.state.manager
    session = None
    for s in manager.sessions.values():
        if session_id and s.session_id == session_id:
            session = s
            break
        if account_id and s.account and s.account.get("id") == account_id:
            session = s
            break
        if name and s.account and s.account.get("name") == name:
            session = s
            break
    if not session or not session.page:
        raise HTTPException(status_code=400, detail="Không tìm thấy session/page")
    try:
        png = await session.page.screenshot(type="png")
        fp = DATA_DIR / "game_sim_debug" / f"shot_{account_id[:8]}_{int(time.time())}.png"
        fp.write_bytes(png)
        return {"ok": True, "file": str(fp), "size": len(png)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/browser/eval")
async def browser_eval(body: EvalIn, request: Request):
    """Evaluate JS trên page của 1 session (debug / test / lưu session thủ công)."""
    manager = request.app.state.manager
    session = None
    pname = (body.profile_name or body.name or "").strip().lower()
    for s in manager.sessions.values():
        if body.session_id and s.session_id == body.session_id:
            session = s
            break
        if body.account_id and s.account and s.account.get("id") == body.account_id:
            session = s
            break
        if pname and s.account:
            s_name = (s.account.get("name") or "").lower()
            if s_name == pname or pname in s_name or s_name in pname:
                session = s
                break
    if not session or not session.page:
        raise HTTPException(status_code=400, detail="Không tìm thấy session/page")
    try:
        frames_res = []
        for i, frame in enumerate(session.page.frames):
            try:
                fr_res = await frame.evaluate(body.js)
                frames_res.append({"frame_idx": i, "url": frame.url, "result": fr_res})
            except Exception as e:
                frames_res.append({"frame_idx": i, "url": frame.url, "error": str(e)})

        workers_res = []
        for j, w in enumerate(session.page.workers or []):
            try:
                w_res = await w.evaluate(body.js)
                workers_res.append({"worker_idx": j, "url": w.url, "result": w_res})
            except Exception as e:
                workers_res.append({"worker_idx": j, "url": w.url, "error": str(e)})

        return {"result": frames_res, "workers": workers_res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/browser/click")
async def browser_click(body: ClickIn, request: Request):
    """Click tọa độ x, y trên page của 1 session bằng Playwright native mouse."""
    manager = request.app.state.manager
    session = None
    pname = (body.profile_name or body.name or "").strip().lower()
    for s in manager.sessions.values():
        if body.session_id and s.session_id == body.session_id:
            session = s
            break
        if body.account_id and s.account and s.account.get("id") == body.account_id:
            session = s
            break
        if pname and s.account:
            s_name = (s.account.get("name") or "").lower()
            if s_name == pname or pname in s_name or s_name in pname:
                session = s
                break
    if not session or not session.page:
        raise HTTPException(status_code=400, detail="Không tìm thấy session/page")
    try:
        await session.page.mouse.click(body.x, body.y)
        return {"ok": True, "x": body.x, "y": body.y}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/browser/show-window")
async def show_window(request: Request):
    """Dùng CDP Browser.setWindowBounds để maximize/restore Chrome window.

    Hoạt động xuyên desktop context (kể cả sandbox exebox của IDE) vì đi
    qua DevTools Protocol websocket thay vì Win32 API (không bị UIPI block).
    """
    manager = request.app.state.manager
    results = []
    for session in manager.sessions.values():
        if not session.page:
            continue
        res = {"session": session.session_id, "ok": False, "detail": ""}
        try:
            # bring_to_front qua Playwright (kích hoạt tab)
            await session.page.bring_to_front()

            # CDP Browser-level: lấy window ID rồi maximize
            # session.browser_ctx = BrowserContext (PersistentContext)
            cdp = await session.browser_ctx.new_cdp_session(session.page)
            target_info = await cdp.send("Target.getTargetInfo", {})
            target_id = target_info["targetInfo"]["targetId"]
            await cdp.detach()

            # Browser-level CDP session (dùng page.context.browser nếu có)
            try:
                browser_obj = session.browser or session.browser_ctx.browser
                browser_cdp = await browser_obj.new_browser_cdp_session()
            except Exception:
                # Fallback: dùng context-level CDP
                browser_cdp = await session.browser_ctx.new_cdp_session(session.page)

            win_data = await browser_cdp.send(
                "Browser.getWindowForTarget", {"targetId": target_id}
            )
            window_id = win_data["windowId"]

            # Maximize window → visible trên màn hình thật
            await browser_cdp.send(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": {"windowState": "maximized"}},
            )
            try:
                await browser_cdp.detach()
            except Exception:
                pass
            res["ok"] = True
            res["detail"] = f"windowId={window_id} maximized"
            log.info("show-window CDP OK: session=%s windowId=%s", session.session_id, window_id)
        except Exception as e:
            res["detail"] = str(e)
            log.warning("show-window CDP failed: session=%s err=%s", session.session_id, e)
            try:
                await session.page.bring_to_front()
                res["detail"] += " | bring_to_front fallback OK"
            except Exception:
                pass
        results.append(res)
    return {"ok": any(r["ok"] for r in results), "results": results}


@router.get("/api/browser/targets")
async def get_browser_targets(request: Request):
    manager = request.app.state.manager
    data = {}
    for sid, session in manager.sessions.items():
        if not session.page:
            continue
        try:
            cdp = await session.browser_ctx.new_cdp_session(session.page)
            targets = await cdp.send("Target.getTargets", {})
            await cdp.detach()
            sws = [str(sw) for sw in getattr(session.browser_ctx, "service_workers", [])]
            data[sid] = {"targets": targets.get("targetInfos", []), "service_workers": sws}
        except Exception as e:
            data[sid] = {"error": str(e)}
    return data


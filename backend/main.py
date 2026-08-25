import asyncio
import logging
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from browser_manager import BrowserManager
from config import (
    APP_NAME,
    APP_VERSION,
    DATA_DIR,
    DEFAULT_CONFIG,
    PROFILES_DIR,
    load_accounts,
    load_config,
    make_profile_dir,
    save_accounts,
    save_config,
)
from fingerprint import random_chrome_ua, random_desktop_os

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")

hub = None
manager = None


class Hub:
    def __init__(self):
        self.connections = set()

    def connect(self, ws):
        self.connections.add(ws)

    def disconnect(self, ws):
        self.connections.discard(ws)

    async def broadcast(self, event):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def on_manager_event(event):
    try:
        loop = asyncio.get_running_loop()
        if loop.is_closed():
            return
        loop.create_task(hub.broadcast(event))
    except RuntimeError:
        return


app = FastAPI(title="Tab Manager")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    global hub, manager
    hub = Hub()
    manager = BrowserManager(load_config(), on_event=on_manager_event)


class AccountIn(BaseModel):
    name: str
    url: str = "about:blank"
    user_agent: str = ""
    proxy: str = ""
    save_session: bool = True


class OpenIn(BaseModel):
    count: Optional[int] = None
    account_ids: Optional[list[str]] = None


class CloseIn(BaseModel):
    session_ids: Optional[list[str]] = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    return load_config()


@app.get("/api/info")
async def get_info():
    return {
        "profiles_dir": str(PROFILES_DIR),
        "data_dir": str(DATA_DIR),
    }


@app.get("/api/version")
async def get_version():
    return {"version": APP_VERSION, "app": APP_NAME}


@app.get("/api/browser-status")
async def get_browser_status():
    try:
        from camoufox.pkgman import installed_verstr
        ver = installed_verstr()
        return {"installed": bool(ver), "version": ver}
    except Exception:
        return {"installed": False, "version": None}


@app.post("/api/install-browser")
async def install_browser():
    import asyncio

    def _fetch():
        from camoufox.pkgman import CamoufoxFetcher
        CamoufoxFetcher().install()

    await asyncio.get_event_loop().run_in_executor(None, _fetch)
    return {"ok": True}


@app.post("/api/config")
async def set_config(cfg: dict):
    current = load_config()
    if "grid" in cfg:
        current["grid"] = {**current["grid"], **cfg["grid"]}
    if "window" in cfg:
        current["window"] = {**current["window"], **cfg["window"]}
    if "anti_detect" in cfg:
        current["anti_detect"] = {**current["anti_detect"], **cfg["anti_detect"]}
    if "open_direction" in cfg:
        current["open_direction"] = cfg["open_direction"]
    if "default_count" in cfg:
        current["default_count"] = int(cfg["default_count"])
    if "auto_layout" in cfg:
        current["auto_layout"] = bool(cfg["auto_layout"])
    save_config(current)
    manager.config = current
    if current.get("auto_layout", True):
        await manager.apply_layout()
    return current


@app.get("/api/antidetect")
async def get_antidetect_options():
    return {
        "os": ["random", "windows", "macos", "linux"],
        "locale": ["random", "en-US", "vi-VN", "zh-CN", "ja-JP", "ko-KR", "th-TH", "id-ID", "en-GB", "de-DE", "fr-FR"],
    }


@app.get("/api/accounts")
async def get_accounts():
    accounts = _ensure_account_fingerprints(load_accounts())
    for i, a in enumerate(accounts):
        a["index"] = i + 1
    return accounts


def _ensure_account_fingerprints(accounts):
    changed = False
    for a in accounts:
        if a.get("save_session") and not a.get("profile_ua") and not a.get("user_agent"):
            os_name = random_desktop_os()
            a["profile_os"] = os_name
            a["profile_ua"] = random_chrome_ua(os_name)
            changed = True
    if changed:
        save_accounts(accounts)
    return accounts


@app.post("/api/accounts")
async def add_account(a: AccountIn):
    accounts = load_accounts()
    account_id = str(uuid.uuid4())
    record = {"id": account_id, **a.model_dump()}
    if record.get("save_session"):
        record["profile_dir"] = make_profile_dir(record["name"], account_id)
        if not record.get("user_agent"):
            os_name = random_desktop_os()
            record["profile_os"] = os_name
            record["profile_ua"] = random_chrome_ua(os_name)
    else:
        record["profile_dir"] = ""
    accounts.append(record)
    save_accounts(accounts)
    record["index"] = len(accounts)
    return record


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str):
    for sid in [
        s.session_id
        for s in manager.sessions.values()
        if s.account and s.account["id"] == account_id
    ]:
        await manager.close_session(sid)
    accounts = load_accounts()
    accounts = [a for a in accounts if a["id"] != account_id]
    save_accounts(accounts)
    return {"ok": True}


@app.post("/api/browser/open")
async def open_browser(body: OpenIn):
    accounts = _ensure_account_fingerprints(load_accounts())
    ids = await manager.open_sessions(
        count=body.count, account_ids=body.account_ids, accounts=accounts
    )
    return {"session_ids": ids}


@app.post("/api/browser/close")
async def close_browser(body: CloseIn):
    if body.session_ids:
        for sid in body.session_ids:
            await manager.close_session(sid)
    else:
        await manager.close_all()
    return {"ok": True}


@app.post("/api/browser/layout")
async def apply_layout():
    n = await manager.apply_layout()
    return {"count": n}


@app.get("/api/sessions")
async def get_sessions():
    return manager.states()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.connect(ws)
    await ws.send_json({"type": "hello", "sessions": manager.states()})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
"""Controller: health, info, version, browser status, profiles-dir."""
import asyncio
import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from models.config_model import (
    APP_NAME,
    APP_VERSION,
    DATA_DIR,
    get_profiles_dir,
    load_config,
    save_config,
)
from models.proxy_model import parse_proxy

log = logging.getLogger("info_controller")

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/info")
async def get_info():
    return {
        "profiles_dir": str(get_profiles_dir()),
        "data_dir": str(DATA_DIR),
    }


@router.post("/api/set-profiles-dir")
async def set_profiles_dir(body: dict):
    raw = (body.get("dir") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Thiếu đường dẫn")
    p = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không thể tạo thư mục: {e}")
    current = load_config()
    current["profiles_dir"] = str(p)
    save_config(current)
    log.info("profiles_dir -> %s", p)
    return {"profiles_dir": str(p)}


@router.get("/api/version")
async def get_version():
    return {"version": APP_VERSION, "app": APP_NAME}


@router.get("/api/platform")
async def get_platform():
    from platform_config import info as platform_info

    return platform_info()


@router.get("/api/browser-status")
async def get_browser_status():
    try:
        from patchright.async_api import async_playwright

        async with async_playwright() as p:
            path = p.chromium.executable_path
            installed = bool(path and Path(path).exists())
        return {"installed": installed, "version": None}
    except Exception:
        return {"installed": False, "version": None}


@router.post("/api/install-browser")
async def install_browser():
    from services.browser_service import install_chromium

    await asyncio.get_event_loop().run_in_executor(None, install_chromium, None)
    return {"ok": True}


def _proxy_to_requests_url(proxy_config: dict) -> str:
    """Chuyển proxy dict (kiểu Playwright) sang URL proxy cho `requests`.

    Ví dụ: {"server": "http://1.2.3.4:80", "username": "u", "password": "p"}
      -> "http://u:p@1.2.3.4:80"
    """
    server = proxy_config["server"]
    if "username" in proxy_config:
        user = proxy_config["username"]
        pwd = proxy_config.get("password", "")
        scheme, _, rest = server.partition("://")
        return f"{scheme}://{user}:{pwd}@{rest}"
    return server


@router.post("/api/check-proxy")
async def check_proxy(body: dict):
    """Kiểm tra proxy: thử kết nối ra internet qua proxy."""
    raw = (body.get("proxy") or "").strip()
    if not raw:
        return {"ok": False, "error": "Chuỗi proxy rỗng"}
    proxy_config = parse_proxy(raw)
    if not proxy_config:
        return {"ok": False, "error": "Định dạng proxy không hợp lệ (host:port hoặc host:port:user:pass)"}

    import requests

    proxy_url = _proxy_to_requests_url(proxy_config)
    proxies = {"http": proxy_url, "https": proxy_url}
    start = time.monotonic()
    try:
        resp = requests.get(
            "https://api.ipify.org",
            proxies=proxies,
            timeout=10,
            headers={"User-Agent": "curl/8.0"},
        )
        resp.raise_for_status()
        ip = resp.text.strip()
        latency_ms = int((time.monotonic() - start) * 1000)
        log.info("proxy check OK: %s (%sms)", ip, latency_ms)
        return {"ok": True, "ip": ip, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        msg = str(e)[:200] or e.__class__.__name__
        log.warning("proxy check FAIL: %s", msg)
        return {"ok": False, "error": msg, "latency_ms": latency_ms}

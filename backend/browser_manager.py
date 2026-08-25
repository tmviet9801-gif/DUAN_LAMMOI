import asyncio
import ctypes
import json
import logging
import time
from ctypes import wintypes

import psutil
from camoufox import AsyncCamoufox
from camoufox.async_api import AsyncNewContext

from window_layout import compute_grid, get_work_area
from fingerprint import random_chrome_ua, random_desktop_os

log = logging.getLogger("browser_manager")

user32 = ctypes.windll.user32
SWP_NOZORDER = 0x0004


def _find_hwnd_by_pid(pid):
    hwnds = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        pid_value = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_value))
        if pid_value.value == pid and user32.IsWindowVisible(hwnd):
            hwnds.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return hwnds[0] if hwnds else None


def _camoufox_pids():
    pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info["name"] or "").lower()
        if "camoufox" in name or name in ("firefox.exe", "firefox"):
            pids.add(proc.info["pid"])
    return pids


class TabSession:
    def __init__(self, session_id, account, browser_ctx, browser, page, pid, hwnd, ua="", fp_os=""):
        self.session_id = session_id
        self.account = account
        self.browser_ctx = browser_ctx
        self.browser = browser
        self.page = page
        self.pid = pid
        self.hwnd = hwnd
        self.state = "opening"
        self.error = None
        self.ua = ua
        self.fp_os = fp_os
        self.url = account["url"] if account and account.get("url") else "about:blank"

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "account": self.account,
            "state": self.state,
            "error": self.error,
            "url": self.url,
            "pid": self.pid,
            "ua": self.ua,
            "fp_os": self.fp_os,
        }


def _install_browser_with_progress(on_progress=None):
    import os
    import shutil
    import tempfile
    from pathlib import Path

    import orjson
    import requests

    from camoufox.pkgman import CamoufoxFetcher, unzip
    from camoufox.multiversion import (
        BROWSERS_DIR,
        COMPAT_FLAG,
        get_repo_name,
        set_active,
        version_folder_name,
    )

    fetcher = CamoufoxFetcher()
    fetcher.fetch_latest()
    if fetcher._selected_version and fetcher._selected_version.sha256:
        sha8 = fetcher._selected_version.sha8
    else:
        sha8 = getattr(fetcher, "installed_sha8", "")
    repo_name = get_repo_name(fetcher.github_repo)
    version_folder = version_folder_name(fetcher.version, fetcher.build, sha8)
    install_path = BROWSERS_DIR / repo_name / version_folder

    if install_path.exists() and (install_path / "version.json").exists():
        set_active(f"browsers/{repo_name}/{version_folder}")
        return

    if install_path.exists():
        shutil.rmtree(install_path)
    install_path.mkdir(parents=True, exist_ok=True)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name

        resp = requests.get(fetcher.url, stream=True, timeout=60)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        with open(tmp_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total and on_progress:
                    on_progress(int(done * 100 / total))

        unzip(tmp_path, str(install_path))
        if fetcher._selected_version:
            metadata = fetcher._selected_version.to_metadata()
        else:
            metadata = {
                "version": fetcher.version,
                "build": fetcher.build,
                "prerelease": fetcher.is_prerelease,
                "sha256": getattr(fetcher, "installed_sha256", None),
                "created_at": getattr(fetcher, "installed_created_at", None),
            }
        with open(install_path / "version.json", "wb") as fh:
            fh.write(orjson.dumps(metadata))
        set_active(f"browsers/{repo_name}/{version_folder}")
        COMPAT_FLAG.touch()
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class BrowserManager:
    def __init__(self, config, on_event=None):
        self.config = config
        self.sessions = {}
        self.on_event = on_event or (lambda event: None)

    def _emit(self, kind, **data):
        try:
            self.on_event({"type": kind, **data, "sessions": self.states()})
        except Exception:
            pass

    def states(self):
        return [s.to_dict() for s in self.sessions.values()]

    async def ensure_browser(self):
        try:
            from camoufox.pkgman import installed_verstr
            installed_verstr()
            return True
        except Exception:
            pass
        loop = asyncio.get_running_loop()
        self._emit("browser_installing", percent=0)
        try:
            def _install():
                _install_browser_with_progress(
                    lambda p: loop.call_soon_threadsafe(self._emit, "browser_installing", percent=p)
                )
            await loop.run_in_executor(None, _install)
        except Exception as e:
            log.exception("install browser failed")
            self._emit("browser_install_error", error=str(e))
            return False
        self._emit("browser_installed")
        return True

    async def open_sessions(self, count=None, account_ids=None, accounts=None):
        if not await self.ensure_browser():
            return []
        accounts = accounts or []
        for i, a in enumerate(accounts, 1):
            a["index"] = i
        if account_ids:
            by_id = {a["id"]: a for a in accounts}
            pool = [by_id[i] for i in account_ids if i in by_id]
        else:
            pool = list(accounts)
        open_account_ids = {
            s.account["id"] for s in self.sessions.values() if s.account
        }
        pool = [a for a in pool if a["id"] not in open_account_ids]
        if count is None:
            count = len(pool)
        count = max(0, int(count))
        stamp = int(time.time() * 1000)
        for i in range(count):
            account = pool[i] if i < len(pool) else None
            await self._open_one(f"tab_{stamp}_{i}", account)
        if self.config.get("auto_layout", True):
            await self.apply_layout()
        return [s.session_id for s in self.sessions.values()]

    @staticmethod
    async def _read_ua(page):
        try:
            return await page.evaluate("navigator.userAgent") or ""
        except Exception:
            return ""

    async def _open_one(self, session_id, account):
        ad = self.config.get("anti_detect", {})
        fp_os = ad.get("os", "random")
        locale = ad.get("locale", "random")
        profile_dir = account.get("profile_dir") if account and account.get("save_session") else None
        if account:
            ua = account.get("user_agent") or account.get("profile_ua") or None
            real_os = account.get("profile_os") or fp_os
            idx = account.get("index")
            tab_title = f"#{idx} {account['name']}" if idx else account["name"]
        else:
            os_name = random_desktop_os()
            ua = random_chrome_ua(os_name)
            real_os = os_name
            tab_title = "Tab trống"
        before = _camoufox_pids()
        browser_ctx = None
        try:
            launch_kwargs = {}
            if profile_dir:
                launch_kwargs["persistent_context"] = True
                launch_kwargs["user_data_dir"] = profile_dir
                if ua:
                    launch_kwargs["user_agent"] = ua
                if locale and locale != "random":
                    launch_kwargs["locale"] = locale
            browser_ctx = AsyncCamoufox(headless=False, **launch_kwargs)
            browser = await browser_ctx.__aenter__()
            if profile_dir:
                pages = browser.pages
                page = pages[0] if pages else await browser.new_page()
                for extra in pages[1:]:
                    try:
                        await extra.close()
                    except Exception:
                        pass
                ua_actual = await self._read_ua(page)
            else:
                context_kwargs = {}
                if ua:
                    context_kwargs["user_agent"] = ua
                if fp_os and fp_os != "random":
                    context_kwargs["os"] = fp_os
                if locale and locale != "random":
                    context_kwargs["locale"] = locale
                context = await AsyncNewContext(browser, **context_kwargs)
                page = await context.new_page()
                ua_actual = await self._read_ua(page)
            try:
                await page.evaluate(f"document.title = {json.dumps(tab_title)}")
            except Exception:
                pass
            url = account["url"] if account and account.get("url") else "about:blank"
            if url and url != "about:blank":
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await page.evaluate(f"document.title = {json.dumps(tab_title)}")
                except Exception as e:
                    log.warning("goto %s failed: %s", url, e)
            pid, hwnd = await self._wait_new_window(before)
            if pid is None:
                raise RuntimeError("không tìm thấy cửa sổ trình duyệt")
            session = TabSession(
                session_id, account, browser_ctx, browser, page, pid, hwnd,
                ua=ua_actual, fp_os=real_os,
            )
            self.sessions[session_id] = session
            session.state = "ready"
            self._emit("opened", session_id=session_id)
        except Exception as e:
            if browser_ctx is not None:
                try:
                    await browser_ctx.__aexit__(None, None, None)
                except Exception:
                    pass
            log.exception("open %s failed", session_id)
            session = TabSession(
                session_id, account, None, None, None, None, None,
                ua=ua if ua else "", fp_os=real_os,
            )
            session.state = "error"
            session.error = str(e)
            self.sessions[session_id] = session
            self._emit("opened", session_id=session_id)

    async def _wait_new_window(self, before, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for pid in _camoufox_pids() - before:
                hwnd = _find_hwnd_by_pid(pid)
                if hwnd:
                    return pid, hwnd
            await asyncio.sleep(0.5)
        return None, None

    def _set_window(self, session, rect):
        hwnd = session.hwnd or (session.pid and _find_hwnd_by_pid(session.pid))
        if not hwnd:
            return False
        x, y, w, h = rect
        user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), SWP_NOZORDER)
        session.hwnd = hwnd
        return True

    async def apply_layout(self):
        sessions = list(self.sessions.values())
        if not sessions:
            return 0
        grid = self.config.get("grid", {})
        win = self.config.get("window", {})
        direction = self.config.get("open_direction", "row")
        rects = compute_grid(
            len(sessions),
            grid.get("cols", 5),
            grid.get("gap", 8),
            grid.get("margin", 4),
            get_work_area(),
            window_size=(win.get("width", 0), win.get("height", 0)),
            direction=direction,
        )
        moved = 0
        for session, rect in zip(sessions, rects):
            if self._set_window(session, rect):
                moved += 1
        self._emit("layout", count=moved)
        return moved

    async def close_session(self, session_id):
        session = self.sessions.pop(session_id, None)
        if not session:
            return False
        if session.browser_ctx is not None:
            try:
                await session.browser_ctx.__aexit__(None, None, None)
            except Exception as e:
                log.warning("close %s error: %s", session_id, e)
        self._emit("closed", session_id=session_id)
        return True

    async def close_all(self):
        ids = list(self.sessions)
        for sid in ids:
            await self.close_session(sid)
        return len(ids)

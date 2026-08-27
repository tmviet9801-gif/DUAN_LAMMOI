import asyncio
import ctypes
import json
import logging
import os
import time
from ctypes import wintypes
from pathlib import Path

import psutil
from camoufox import AsyncCamoufox
from camoufox.async_api import AsyncNewContext

from models.config_model import DATA_DIR
from models.fingerprint_model import random_chrome_ua, random_desktop_os
from models.proxy_model import parse_proxy
from models.window_layout_model import compute_grid, get_work_area
from game_sim.token_store import TokenStore

log = logging.getLogger("browser_service")

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


def _pid_alive(pid):
    """Trả True nếu pid còn tồn tại và vẫn là process camoufox/firefox."""
    try:
        p = psutil.Process(pid)
        name = (p.name() or "").lower()
        return "camoufox" in name or name in ("firefox.exe", "firefox")
    except Exception:
        return False


def _clear_profile_lock(profile_dir):
    """Firefox/Camoufox để lại parent.lock khi bị kill đột ngột. Nếu không xóa,
    lần mở lại profile sẽ từ chối mở (hiện dialog 'profile in use') hoặc mở cửa
    sổ tạm/trống. Xóa lock cũ trước khi launch persistent_context."""
    if not profile_dir:
        return
    for name in ("parent.lock", "lock", ".parentlock"):
        try:
            p = Path(profile_dir) / name
            if p.exists() or p.is_symlink():
                p.unlink()
        except Exception:
            pass


def reap_orphan_camoufox(my_pid=None):
    """Kill các process camoufox KHÔNG phải hậu duệ (descendant) của backend hiện tại.

    Khi backend/Electron restart mà không đóng trình duyệt cũ (dev reload, kill
    cứng), các camoufox cũ sống sót thành 'mồ côi' — vẫn hiện trên màn hình nhưng
    app không track, và có thể là cửa sổ trống. Chỉ giữ lại process là con/cháu của
    process backend đang chạy; mọi process camoufox khác đều bị thu hồi.
    """
    me = my_pid or os.getpid()

    def is_descendant(proc, ancestor):
        seen = set()
        cur = proc
        while cur is not None and cur.pid not in seen:
            if cur.pid == ancestor:
                return True
            seen.add(cur.pid)
            try:
                cur = cur.parent()
            except Exception:
                break
        return False

    killed = 0
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info["name"] or "").lower()
        if "camoufox" not in name and name not in ("firefox.exe", "firefox"):
            continue
        try:
            p = psutil.Process(proc.info["pid"])
        except Exception:
            continue
        if is_descendant(p, me):
            continue  # trình duyệt do backend hiện tại quản lý -> giữ
        try:
            for child in p.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            p.kill()
            killed += 1
        except Exception as e:
            log.warning("reap camoufox %s failed: %s", proc.info["pid"], e)
    if killed:
        log.info("reaped %d orphan camoufox process trees", killed)
    return killed


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
            for chunk in resp.iter_content(chunk_size=256 * 1024):
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
        self.token_store = TokenStore(DATA_DIR / "game_sim_token.json")

    def _emit(self, kind, **data):
        try:
            self.on_event({"type": kind, **data, "sessions": self.states()})
        except Exception:
            pass

    def states(self):
        return [s.to_dict() for s in self.sessions.values()]

    def prune_dead_sessions(self):
        """Gỡ các session mà trình duyệt đã tắt/crash (pid không còn là camoufox).

        Mặc định backend không biết khi user đóng cửa sổ thủ công hoặc trình duyệt
        crash → session cứ hiển thị 'ready' mãi. Hàm này đồng bộ lại trạng thái thực
        tế và emit 'closed' để UI cập nhật.
        """
        dead = []
        for sid, s in list(self.sessions.items()):
            if s.browser_ctx is None or s.pid is None:
                continue
            if not _pid_alive(s.pid):
                dead.append(sid)
        for sid in dead:
            session = self.sessions.pop(sid, None)
            if session:
                log.info("pruned dead session %s (pid %s gone)", sid, session.pid)
                try:
                    self._emit("closed", session_id=sid)
                except Exception:
                    pass
        return len(dead)

    async def save_open_sessions_storage(self):
        """Đọc localStorage/sessionStorage của mọi session đang mở và lưu vào account.

        Game HITCLUB lưu token login trong localStorage nhưng session (hitsession_id)
        bị expire theo thời gian. Gọi định kỳ (watchdog) để luôn giữ session MỚI NHẤT
        của user — mở lại profile sẽ auto-login mà không cần bấm 'Lưu login' tay.
        """
        from models.config_model import load_accounts, save_accounts

        accounts = load_accounts()
        by_id = {a["id"]: a for a in accounts}
        saved_any = False
        for session in self.sessions.values():
            if session.page is None or session.account is None or session.state != "ready":
                continue
            acc_id = session.account.get("id")
            if acc_id not in by_id:
                continue
            try:
                ls = await session.page.evaluate("JSON.stringify(window.localStorage)")
                ss = await session.page.evaluate("JSON.stringify(window.sessionStorage)")
            except Exception:
                continue
            data = {}
            if ls:
                ld = json.loads(ls)
                if ld:
                    data["local"] = ld
            if ss:
                sd = json.loads(ss)
                if sd:
                    data["session"] = sd
            # ---- capture token MỚI nhất vào token store ----
            tok = TokenStore.extract_from_storage(data.get("local", {})) or TokenStore.extract_from_storage(data.get("session", {}))
            if tok:
                if self.token_store.save(session.account.get("name") or acc_id, tok,
                                         extra={"username": session.account.get("username")}):
                    log.info("auto-saved NEW token for %s", session.account.get("name"))
            if not data:
                continue
            cur = by_id[acc_id].get("web_storage") or {}
            if cur == data:
                continue
            by_id[acc_id]["web_storage"] = data
            session.account["web_storage"] = data
            saved_any = True
            log.info("auto-saved web storage for %s (local=%d, session=%d)",
                     session.account.get("name"), len(data.get("local", {})), len(data.get("session", {})))
        if saved_any:
            try:
                save_accounts(accounts)
            except Exception as e:
                log.warning("save accounts in auto-save failed: %s", e)
        return saved_any

    async def ensure_browser(self):
        try:
            from camoufox.pkgman import installed_verstr
            installed_verstr()
            return True
        except Exception:
            pass
        try:
            from camoufox.multiversion import BROWSERS_DIR, set_active
            ver_paths = sorted(BROWSERS_DIR.rglob("version.json"))
            if ver_paths:
                rel = str(ver_paths[0].parent.relative_to(BROWSERS_DIR))
                set_active(f"browsers/{rel}")
                return True
        except Exception:
            pass
        try:
            from models.bundled_model import get_bundled_browser_dir, install_bundled_browser
            bundled = get_bundled_browser_dir()
            if bundled:
                self._emit("browser_installing", percent=0, source="bundled")
                ok = await asyncio.get_running_loop().run_in_executor(
                    None, install_bundled_browser, bundled
                )
                if ok:
                    self._emit("browser_installed", source="bundled")
                    return True
        except Exception as e:
            log.warning("install bundled browser failed: %s", e)
        loop = asyncio.get_running_loop()
        self._emit("browser_installing", percent=0, source="download")
        try:
            def _install():
                _install_browser_with_progress(
                    lambda p: loop.call_soon_threadsafe(
                        lambda: self._emit("browser_installing", percent=int(p))
                    )
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
        self.prune_dead_sessions()
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
        proxy_dict = parse_proxy(account.get("proxy") or "") if account else None
        try:
            launch_kwargs = {}
            if self.config.get("mute_all_sites"):
                launch_kwargs["firefox_user_prefs"] = {"media.default_muted": True}
            if profile_dir:
                _clear_profile_lock(profile_dir)
                launch_kwargs["persistent_context"] = True
                launch_kwargs["user_data_dir"] = profile_dir
                if ua:
                    launch_kwargs["user_agent"] = ua
                if locale and locale != "random":
                    launch_kwargs["locale"] = locale
            if proxy_dict:
                launch_kwargs["proxy"] = proxy_dict
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
                if proxy_dict:
                    context_kwargs["proxy"] = proxy_dict
                context = await AsyncNewContext(browser, **context_kwargs)
                page = await context.new_page()
                ua_actual = await self._read_ua(page)
            try:
                await page.evaluate(f"document.title = {json.dumps(tab_title)}")
            except Exception:
                pass
            if account and account.get("web_storage"):
                try:
                    ws = account["web_storage"]
                    local = dict(ws.get("local", {}))
                    session = dict(ws.get("session", {}))
                    # Ưu tiên token MỚI NHẤT từ token store (game trả token mới mỗi
                    # lần login, token cũ có thể expire -> profile không login được).
                    fresh = self.token_store.get(account.get("name") or account.get("id"))
                    if fresh:
                        local["token"] = fresh
                        local["user_token"] = fresh
                        log.info("restore FRESH token for %s (override stale web_storage)",
                                 account.get("name"))
                    local = json.dumps(local)
                    session = json.dumps(session)
                    # Force isAutoLogin = true để game tự login khi mở
                    await page.add_init_script(f"""
                        (() => {{
                            const local = {local};
                            const session = {session};
                            local.isAutoLogin = 'true';
                            Object.entries(local).forEach(([k, v]) => {{
                                try {{ localStorage.setItem(k, v); }} catch(e) {{}}
                            }});
                            Object.entries(session).forEach(([k, v]) => {{
                                try {{ sessionStorage.setItem(k, v); }} catch(e) {{}}
                            }});
                        }})();
                    """)
                except Exception:
                    pass
            url = account["url"] if account and account.get("url") else "about:blank"
            if url and url != "about:blank":
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    # Game Cocos/WASM đọc localStorage từ lần boot thứ 2 trở đi.
                    # Nếu có web_storage đã lưu (token login), reload để game
                    # đọc token và auto-login, thay vì user phải F5 thủ công.
                    if account and account.get("web_storage"):
                        try:
                            await page.reload(wait_until="domcontentloaded", timeout=60000)
                        except Exception:
                            pass
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
        self.prune_dead_sessions()
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
        # Lưu localStorage + sessionStorage (token login game) vào account record
        # TRƯỚC khi đóng. Firefox/Playwright KHÔNG flush localStorage xuống đĩa
        # khi đóng persistent context (file ls/data.sqlite vẫn rỗng) nên login
        # bị mất. Ta tự đọc toàn bộ storage rồi inject lại khi mở (_open_one).
        if session.page and session.account and session.state == "ready":
            try:
                ls = await session.page.evaluate("JSON.stringify(window.localStorage)")
                ss = await session.page.evaluate("JSON.stringify(window.sessionStorage)")
                saved = {}
                if ls:
                    ld = json.loads(ls)
                    if ld:
                        saved["local"] = ld
                if ss:
                    sd = json.loads(ss)
                    if sd:
                        saved["session"] = sd
                if saved:
                    session.account["web_storage"] = saved
                    from models.config_model import load_accounts, save_accounts

                    accounts = load_accounts()
                    for a in accounts:
                        if a["id"] == session.account["id"]:
                            a["web_storage"] = saved
                            break
                    save_accounts(accounts)
                    log.info(
                        "saved web storage for %s (local=%d, session=%d)",
                        session.account.get("name"),
                        len(saved.get("local", {})),
                        len(saved.get("session", {})),
                    )
                # ---- capture token MỚI nhất vào token store trước khi xóa ----
                tok = TokenStore.extract_from_storage(saved.get("local", {})) or TokenStore.extract_from_storage(saved.get("session", {}))
                if tok:
                    self.token_store.save(session.account.get("name") or session.account.get("id"), tok,
                                           extra={"username": session.account.get("username")})
                # ---- XÓA token session khỏi browser live ----
                # Game HITCLUB trả token MỚI mỗi lần login; token cũ (đã lưu trên)
                # sẽ expire. Xóa token live để app/editor khác mở profile này
                # KHÔNG mang theo session cũ hết hạn (gây "không login được").
                # Token mới nhất đã nằm an toàn trong token store + web_storage.
                try:
                    await session.page.evaluate(
                        "try{localStorage.removeItem('token');}catch(e){}"
                        "try{localStorage.removeItem('user_token');}catch(e){}"
                    )
                except Exception:
                    pass
            except Exception as e:
                log.debug("save web storage %s fail: %s", session_id, e)
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

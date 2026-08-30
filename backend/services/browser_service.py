import asyncio
import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

import psutil

from models.config_model import DATA_DIR
from models.proxy_model import parse_proxy
from models.window_layout_model import compute_grid, get_work_area
from game_sim.token_store import TokenStore

log = logging.getLogger("browser_service")

user32 = ctypes.windll.user32
SWP_NOZORDER    = 0x0004
SWP_SHOWWINDOW  = 0x0040  # buộc hiện window (kể cả khi đang minimized)
SW_RESTORE      = 9       # restore từ minimized
SW_SHOW         = 5       # hiện window ở trạng thái hiện tại

# Tên process của Chromium (engine của Patchright) trên Windows/Linux/macOS.
CHROME_PROCESS_NAMES = ("chrome.exe", "chrome", "chromium.exe", "chromium")


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


def _chrome_pids():
    pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info["name"] or "").lower()
        if name in CHROME_PROCESS_NAMES:
            pids.add(proc.info["pid"])
    return pids


def _pid_alive(pid):
    """Trả True nếu pid còn tồn tại và vẫn là process chromium/chrome."""
    try:
        p = psutil.Process(pid)
        name = (p.name() or "").lower()
        return name in CHROME_PROCESS_NAMES
    except Exception:
        return False


def _clear_profile_lock(profile_dir):
    """Chromium để lại SingletonLock/SingletonCookie/SingletonSocket khi bị kill
    đột ngột. Nếu không xóa, lần mở lại profile có thể bị từ chối ("profile in
    use"). Xóa lock cũ trước khi launch persistent context."""
    if not profile_dir:
        return
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        try:
            p = Path(profile_dir) / name
            if p.exists() or p.is_symlink():
                p.unlink()
        except Exception:
            pass


def reap_orphan_chrome(my_pid=None):
    """Kill các process Chromium mồ côi DO APP QUẢN LÝ (không phải hậu duệ backend).

    CHỈ thu hồi process Chrome mà executable nằm dưới thư mục browser của
    Playwright/Patchright (ms-playwright/.../chrome-win64) hoặc profile do app tạo
    (user-data-dir chứa đường dẫn profiles của app). KHÔNG đụng vào Chrome cá nhân
    của user hay Chromium nhúng của ứng dụng khác.
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

    def is_app_chrome(p):
        """Chrome thuộc app: exe nằm dưới ms-playwright/browser bundle, HOẶC
        user-data-dir thuộc thư mục profiles của app."""
        try:
            exe = (p.exe() or "").lower().replace("/", "\\")
            if "ms-playwright" in exe or "chrome-win" in exe or "chromium" in exe:
                return True
        except Exception:
            pass
        try:
            for arg in p.cmdline():
                if arg.startswith("--user-data-dir="):
                    udd = arg.split("=", 1)[1].lower().replace("/", "\\")
                    if "\\profiles\\" in udd or "autotool" in udd or "tabmanager" in udd:
                        return True
        except Exception:
            pass
        return False

    killed = 0
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info["name"] or "").lower()
        if name not in CHROME_PROCESS_NAMES:
            continue
        try:
            p = psutil.Process(proc.info["pid"])
        except Exception:
            continue
        if is_descendant(p, me):
            continue  # trình duyệt do backend hiện tại quản lý -> giữ
        if not is_app_chrome(p):
            continue  # Chrome cá nhân / ứng dụng khác -> KHÔNG đụng
        try:
            for child in p.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            p.kill()
            killed += 1
        except Exception as e:
            log.warning("reap chrome %s failed: %s", proc.info["pid"], e)
    if killed:
        log.info("reaped %d orphan app-chrome process trees", killed)
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
        self.temp_dir = None

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


def install_chromium(on_progress=None):
    """Tải Chromium cho Patchright (`patchright install chromium`)."""
    def emit(p):
        try:
            if on_progress:
                on_progress(int(p))
        except Exception:
            pass

    emit(3)
    cmd = [sys.executable, "-m", "patchright", "install", "chromium"]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
    except Exception:
        # fallback: console script patchright(.exe) nằm cạnh python.exe
        script = Path(sys.executable).parent / ("patchright.exe" if os.name == "nt" else "patchright")
        cmd2 = [str(script), "install", "chromium"] if script.exists() else ["patchright", "install", "chromium"]
        subprocess.run(cmd2, check=True, capture_output=True, timeout=900)
    emit(100)


def _title_enforce_script(title: str) -> str:
    """Script giữ tên profile trên tiêu đề cửa sổ/tab.

    Game (Cocos/WASM) thường ghi đè `document.title` sau khi tải → tên profile
    biến mất. Script này ép `document.title` = tên profile qua init script
    (chạy trước mọi script page, tồn tại qua reload) + MutationObserver +
    setInterval dự phòng.
    """
    t = json.dumps(title)
    return f"""
    (() => {{
        const TITLE = {t};
        const apply = () => {{
            try {{
                if (document.title !== TITLE) {{
                    document.title = TITLE;
                    const el = document.querySelector('title');
                    if (el && el.textContent !== TITLE) el.textContent = TITLE;
                }}
            }} catch (e) {{}}
        }};
        apply();
        document.addEventListener('DOMContentLoaded', apply);
        window.addEventListener('load', apply);
        try {{
            new MutationObserver(apply).observe(document.documentElement, {{
                subtree: true, childList: true, characterData: true,
                attributes: true, attributeFilter: ['title'],
            }});
        }} catch (e) {{}}
        setInterval(apply, 1000);
    }})();
    """


class BrowserManager:
    def __init__(self, config, on_event=None):
        self.config = config
        self.sessions = {}
        self.on_event = on_event or (lambda event: None)
        self.token_store = TokenStore(DATA_DIR / "game_sim_token.json")
        self._pw = None
        self._last_mute_state = None
        self._mute_pid_snapshot = None

    def _emit(self, kind, **data):
        try:
            self.on_event({"type": kind, **data, "sessions": self.states()})
        except Exception:
            pass

    def states(self):
        return [s.to_dict() for s in self.sessions.values()]

    async def _ensure_playwright(self):
        if self._pw is None:
            from patchright.async_api import async_playwright

            self._pw = await async_playwright().start()
        return self._pw

    async def _reset_playwright(self):
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    async def _chromium_available(self):
        try:
            pw = await self._ensure_playwright()
            path = pw.chromium.executable_path
            if path and Path(path).exists():
                return True
        except Exception:
            pass
        return False

    def prune_dead_sessions(self):
        """Gỡ các session mà trình duyệt đã tắt/crash (pid không còn là chrome).

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
        if await self._chromium_available():
            return True
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
                    await self._reset_playwright()
                    return True
        except Exception as e:
            log.warning("install bundled browser failed: %s", e)
        loop = asyncio.get_running_loop()
        self._emit("browser_installing", percent=0, source="download")
        try:
            def _install():
                install_chromium(
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
        await self._reset_playwright()
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
        locale = ad.get("locale", "random")
        profile_dir = account.get("profile_dir") if account and account.get("save_session") else None
        if account:
            idx = account.get("index")
            tab_title = f"#{idx} {account['name']}" if idx else account["name"]
        else:
            tab_title = "Tab trống"
        before = _chrome_pids()
        context = None
        temp_dir = None
        proxy_dict = parse_proxy(account.get("proxy") or "") if account else None
        try:
            pw = await self._ensure_playwright()
            args = []
            if self.config.get("mute_all_sites"):
                args.append("--mute-audio")
            # Nhúng Chrome extension WS bridge vào profile: content script (main world,
            # document_start) patch window.WebSocket của game -> Python có thể gửi lệnh
            # join/đánh bài qua page.evaluate("window.__ws_send(...)") mà không cần
            # intercept (không làm game treo "Đang kết nối").
            try:
                from models.bundled_model import get_extension_dir

                ext_dir = get_extension_dir()
                if ext_dir:
                    args.append("--disable-extensions-except=" + str(ext_dir))
                    args.append("--load-extension=" + str(ext_dir))
            except Exception:
                pass
            user_data_dir = profile_dir
            if not user_data_dir:
                temp_dir = tempfile.mkdtemp(prefix="autotool_tab_")
                user_data_dir = temp_dir
            else:
                _clear_profile_lock(profile_dir)
            # Buộc Chrome luôn mở ra màn hình ở vị trí visible.
            # --start-maximized: maximize ngay khi mở (thay vì bị ẩn sau taskbar).
            # --window-position=100,100: đặt vị trí khởi đầu trên màn hình.
            # --window-size=1280,800: kích thước mặc định nếu chưa có config.
            # --disable-session-crashed-bubble: bỏ popup "Chrome không tắt đúng cách".
            args += [
                "--start-maximized",
                "--window-position=100,100",
                "--disable-session-crashed-bubble",
                "--disable-infobars",
                "--no-first-run",
                "--disable-restore-session-state",
            ]
            launch_kwargs = {
                "user_data_dir": user_data_dir,
                "headless": False,
                "no_viewport": True,
                "args": args,
            }
            if locale and locale != "random":
                launch_kwargs["locale"] = locale
            if proxy_dict:
                launch_kwargs["proxy"] = proxy_dict
            context = await pw.chromium.launch_persistent_context(**launch_kwargs)
            browser = context.browser
            pages = context.pages
            page = pages[0] if pages else await context.new_page()
            for extra in pages[1:]:
                try:
                    await extra.close()
                except Exception:
                    pass
            ua_actual = await self._read_ua(page)
            # Giữ tên profile trên tiêu đề cửa sổ/tab (game hay ghi đè title).
            try:
                await page.add_init_script(_title_enforce_script(tab_title))
            except Exception:
                pass
            try:
                await page.evaluate(f"document.title = {json.dumps(tab_title)}")
            except Exception:
                pass
            if account and account.get("web_storage"):
                try:
                    ws = account["web_storage"]
                    local = dict(ws.get("local", {}))
                    session = dict(ws.get("session", {}))
                    # Token MỚI NHẤT từ token store: chỉ dùng làm FALLBACK khi profile
                    # (Chromium persist native) chưa có token nào. KHÔNG ghi đè token
                    # tươi đang nằm trong localStorage tự nhiên của profile.
                    fresh = self.token_store.get(account.get("name") or account.get("id")) or ""
                    local = json.dumps(local)
                    session = json.dumps(session)
                    fresh = json.dumps(fresh)
                    await page.add_init_script(f"""
                        (() => {{
                            const local = {local};
                            const session = {session};
                            const freshToken = {fresh};
                            try {{ localStorage.setItem('isAutoLogin', 'true'); }} catch(e) {{}}
                            const hasToken = localStorage.getItem('token') || localStorage.getItem('user_token');
                            Object.entries(local).forEach(([k, v]) => {{
                                try {{ if (localStorage.getItem(k) === null) localStorage.setItem(k, v); }} catch(e) {{}}
                            }});
                            if (!hasToken && freshToken) {{
                                try {{ localStorage.setItem('token', freshToken); }} catch(e) {{}}
                                try {{ localStorage.setItem('user_token', freshToken); }} catch(e) {{}}
                            }}
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
                except Exception as e:
                    log.warning("goto %s failed: %s", url, e)
            pid, hwnd = await self._wait_new_window(before)
            if pid is None:
                # Fallback: lấy PID từ process của context (Patchright/Playwright
                # luôn biết PID ngay cả khi UIPI ngăn EnumWindows).
                try:
                    proc = context.browser._browser_type._playwright._impl_obj._loop
                    pid = None
                except Exception:
                    pass
                # Thử lấy từ chrome_pids mới nhất
                new_pids = _chrome_pids() - before
                if new_pids:
                    pid = next(iter(new_pids))
                    log.warning(
                        "_wait_new_window timeout nhưng tìm thấy chrome PID %s — "
                        "có thể do UIPI (Admin). Tiếp tục với pid=%s hwnd=None.",
                        pid, pid,
                    )
                else:
                    raise RuntimeError("không tìm thấy cửa sổ trình duyệt")
            session = TabSession(
                session_id, account, context, browser, page, pid, hwnd,
                ua=ua_actual, fp_os="",
            )
            session.temp_dir = temp_dir
            self.sessions[session_id] = session
            session.state = "ready"
            if self.config.get("mute_all_sites"):
                try:
                    await self.sync_mute()
                except Exception:
                    pass
            self._emit("opened", session_id=session_id)
        except Exception as e:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            log.exception("open %s failed", session_id)
            session = TabSession(
                session_id, account, None, None, None, None, None,
                ua="", fp_os="",
            )
            session.state = "error"
            session.error = str(e)
            self.sessions[session_id] = session
            self._emit("opened", session_id=session_id)

    async def _wait_new_window(self, before, timeout=25):
        """Tìm PID + HWND của cửa sổ Chromium mới vừa mở.

        Khi backend chạy với elevated privileges (Admin), UIPI ngăn
        EnumWindows/IsWindowVisible thấy cửa sổ của Chromium (chạy ở user
        level). Trong trường hợp đó hàm vẫn trả về pid tìm được (không có
        hwnd) để session vẫn được tạo — bring_to_front sẽ dùng Playwright
        API thay vì Win32.
        """
        deadline = time.monotonic() + timeout
        new_pid = None
        while time.monotonic() < deadline:
            new_pids = _chrome_pids() - before
            for pid in new_pids:
                hwnd = _find_hwnd_by_pid(pid)
                if hwnd:
                    return pid, hwnd
                new_pid = pid  # ghi nhớ pid kể cả khi không tìm được hwnd
            await asyncio.sleep(0.5)
        # Fallback: trả pid (không có hwnd) — cửa sổ vẫn chạy,
        # bring_to_front sẽ dùng page.bring_to_front() thay vì Win32.
        if new_pid:
            log.warning(
                "_wait_new_window: tìm thấy PID %s nhưng không lấy được HWND "
                "(có thể do UIPI khi chạy Admin). Dùng Playwright bring_to_front.",
                new_pid,
            )
            return new_pid, None
        return None, None

    def _set_window(self, session, rect):
        hwnd = session.hwnd or (session.pid and _find_hwnd_by_pid(session.pid))
        if not hwnd:
            return False
        x, y, w, h = rect
        # Restore trước (khỏi động minimized ở taskbar) rồi di chuyển ra đúng vị trí.
        # Đây là nguyên nhân chính khiến Chrome thấy trong taskbar nhưng
        # không hiện trên màn hình: SetWindowPos với SWP_NOZORDER đơn thuần
        # không show window nếu nó đang ở trạng thái minimized/hidden.
        user32.ShowWindow(hwnd, SW_RESTORE)   # restore từ minimize
        user32.ShowWindow(hwnd, SW_SHOW)      # đảm bảo visible
        user32.SetWindowPos(
            hwnd, 0,
            int(x), int(y), int(w), int(h),
            SWP_NOZORDER | SWP_SHOWWINDOW,    # vừa move vừa show
        )
        user32.SetForegroundWindow(hwnd)      # đưa lên trước mọn
        session.hwnd = hwnd
        return True

    async def _bring_page_to_front(self, session):
        """Dùng Playwright page.bring_to_front() để đưa cửa sổ Chromium ra
        trước màn hình — hoạt động kể cả khi backend chạy với Admin privileges
        (UIPI ngăn Win32 API nhưng không ngăn Playwright CDP)."""
        if session.page is None:
            return
        try:
            await session.page.bring_to_front()
        except Exception as e:
            log.debug("bring_to_front failed for %s: %s", session.session_id, e)

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
            # Luôn gọi bring_to_front qua Playwright CDP — hoạt động kể cả
            # khi Win32 SetWindowPos bị UIPI block (backend chạy Admin).
            await self._bring_page_to_front(session)
        self._emit("layout", count=moved)
        return moved

    def _session_tree_pids(self, session) -> set:
        """Toàn bộ pid của 1 session: browser main + mọi process con (renderer/gpu)."""
        pids = set()
        if not session.pid:
            return pids
        pids.add(session.pid)
        try:
            proc = psutil.Process(session.pid)
            for child in proc.children(recursive=True):
                pids.add(child.pid)
        except Exception:
            pass
        return pids

    async def mute_all(self, muted: bool) -> int:
        """Mute/unmute âm thanh ngay lập tức cho mọi session đang mở (Windows Core Audio)."""
        from services.audio_control import set_processes_mute

        pids = set()
        for s in self.sessions.values():
            pids |= self._session_tree_pids(s)
        if not pids:
            return 0
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, set_processes_mute, pids, muted)

    async def sync_mute(self) -> int:
        """Đồng bộ trạng thái mute theo cấu hình (gọi định kỳ + khi mở session).

        Audio session của Chrome chỉ xuất hiện khi tab bắt đầu phát âm thanh,
        nên khi mute ON cần re-apply định kỳ để bắt session phát sau khi mở.
        Khi mute OFF chỉ unmute 1 lần (khi user vừa tắt), không gọi lặp lại.
        """
        if not self.sessions:
            self._mute_pid_snapshot = frozenset()
            return 0
        muted = bool(self.config.get("mute_all_sites"))
        if not muted and self._last_mute_state is not True:
            return 0
        # Chỉ re-apply khi tập pid session thay đổi (mở/đóng tab) — tránh quét
        # toàn bộ audio session hệ thống mỗi 5s khi không có gì mới.
        pid_snapshot = frozenset(self._session_tree_pids(s) for s in self.sessions.values())
        current = frozenset().union(*pid_snapshot) if pid_snapshot else frozenset()
        if muted and current == getattr(self, "_mute_pid_snapshot", None):
            return 0
        self._mute_pid_snapshot = current
        self._last_mute_state = muted
        try:
            return await self.mute_all(muted)
        except Exception as e:
            log.debug("sync_mute fail: %s", e)
            return 0

    async def close_session(self, session_id):
        session = self.sessions.pop(session_id, None)
        if not session:
            return False
        # Lưu localStorage + sessionStorage (token login game) vào account record
        # TRƯỚC khi đóng. Chủ động đọc toàn bộ storage rồi inject lại khi mở
        # (_open_one) để login không bị mất (đặc biệt khi đóng trình duyệt đột ngột).
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
                # ---- capture token MỚI nhất vào token store ----
                tok = TokenStore.extract_from_storage(saved.get("local", {})) or TokenStore.extract_from_storage(saved.get("session", {}))
                if tok:
                    self.token_store.save(session.account.get("name") or session.account.get("id"), tok,
                                           extra={"username": session.account.get("username")})
            except Exception as e:
                log.debug("save web storage %s fail: %s", session_id, e)
        if session.browser_ctx is not None:
            try:
                await session.browser_ctx.close()
            except Exception as e:
                log.warning("close %s error: %s", session_id, e)
        # Dọn container module của sniffer (tránh rò rỉ bộ nhớ khi đóng/mở nhiều session)
        if session.page is not None:
            try:
                from game_sim.ws_sniffer import cleanup_page

                cleanup_page(session.page)
            except Exception:
                pass
        if getattr(session, "temp_dir", None):
            shutil.rmtree(session.temp_dir, ignore_errors=True)
        self._emit("closed", session_id=session_id)
        return True

    async def close_all(self):
        ids = list(self.sessions)
        for sid in ids:
            await self.close_session(sid)
        await self._reset_playwright()
        return len(ids)

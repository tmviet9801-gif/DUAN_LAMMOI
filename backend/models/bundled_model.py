"""Model tìm và copy bundled browser (Chromium) từ resources vào Playwright cache."""
import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger("bundled")


def get_bundled_browser_dir() -> Path | None:
    """Tra bundled browser trong PyInstaller bundle / electron extraResources.

    Thứ tự tìm:
    1. Env TABMANAGER_BUNDLED_BROWSER
    2. PyInstaller _MEIPASS/browser
    3. Cùng thư mục với exe (portable): ./browser hoặc ../browser
    """
    env = os.environ.get("TABMANAGER_BUNDLED_BROWSER")
    if env:
        p = Path(env)
        if p.exists():
            return p

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / "browser"
        if p.exists():
            return p

    exe_dir = Path(sys.executable).resolve().parent
    for cand in (exe_dir / "browser", exe_dir.parent / "browser"):
        if cand.exists():
            return cand

    return None


def get_extension_dir() -> Path | None:
    """Tìm thư mục Chrome extension WS bridge, copy sang path AN TOÀN nếu cần.

    Chromium `--load-extension` bỏ qua path chứa dấu cách/ký tự non-ASCII
    (vd "DỰ ÁN KHÁCH") — nên nếu source có dấu cách sẽ copy sang
    %LOCALAPPDATA%/autotool-extension rồi trả về path an toàn đó.

    Thứ tự tìm source:
    1. Env TABMANAGER_EXTENSION
    2. PyInstaller _MEIPASS/extension
    3. Dev: <backend>/extension (cạnh models/)
    """
    src = None
    env = os.environ.get("TABMANAGER_EXTENSION")
    if env:
        p = Path(env)
        if (p / "manifest.json").exists():
            src = p

    if src is None:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "extension"
            if (p / "manifest.json").exists():
                src = p

    if src is None:
        dev = Path(__file__).resolve().parent.parent / "extension"
        if (dev / "manifest.json").exists():
            src = dev

    if src is None:
        return None

    # Nếu source path có dấu cách hoặc non-ASCII -> copy sang nơi an toàn
    raw = str(src)
    if " " in raw or any(ord(c) > 127 for c in raw):
        local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        safe = Path(local) / "autotool-extension"
        try:
            safe.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    target = safe / f.name
                    if not target.exists() or target.stat().st_mtime < f.stat().st_mtime or target.stat().st_size != f.stat().st_size:
                        shutil.copy2(f, target)
            log.info("synced extension files -> %s", safe)
            return safe
        except Exception as e:
            log.warning("copy extension fail: %s", e)
            return src
    return src


def _playwright_browsers_dir() -> Path:
    """Thư mục cache browser của Playwright/Patchright."""
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if base:
        return Path(base)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def install_bundled_browser(bundled_dir: Path) -> bool:
    """Copy thư mục bundled `chromium-*/*` sang Playwright browsers dir.

    Trả về True nếu copy thành công ít nhất 1 bản hợp lệ.
    """
    if not bundled_dir.exists():
        return False

    target = _playwright_browsers_dir()
    target.mkdir(parents=True, exist_ok=True)

    copied = False
    for src in bundled_dir.iterdir():
        if not src.is_dir():
            continue
        dst = target / src.name
        if dst.exists():
            log.info("bundled browser %s đã có sẵn, bỏ qua copy", dst)
            continue
        log.info("copy bundled browser %s -> %s", src, dst)
        shutil.copytree(src, dst)
        copied = True

    return copied

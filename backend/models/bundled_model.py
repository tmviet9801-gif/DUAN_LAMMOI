"""Model tìm và copy bundled browser từ resources vào INSTALL_DIR."""
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


def install_bundled_browser(bundled_dir: Path) -> bool:
    """Copy thư mục bundled browsers/<repo>/<version>-<build>/* sang INSTALL_DIR.

    Trả về True nếu copy thành công và có ít nhất 1 bản hợp lệ.
    """
    from camoufox.multiversion import (
        BROWSERS_DIR,
        COMPAT_FLAG,
        INSTALL_DIR,
        set_active,
    )

    if not bundled_dir.exists():
        return False

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    BROWSERS_DIR.mkdir(parents=True, exist_ok=True)

    src_repos = [d for d in bundled_dir.iterdir() if d.is_dir()]
    if not src_repos:
        log.warning("bundled browser dir rỗng: %s", bundled_dir)
        return False

    active_set = False
    for src_repo in src_repos:
        dst_repo = BROWSERS_DIR / src_repo.name
        dst_repo.mkdir(parents=True, exist_ok=True)
        for src_version in src_repo.iterdir():
            if not src_version.is_dir():
                continue
            dst_version = dst_repo / src_version.name
            if dst_version.exists() and (dst_version / "version.json").exists():
                log.info("bundled browser %s đã có sẵn, bỏ qua copy", dst_version)
            else:
                if dst_version.exists():
                    shutil.rmtree(dst_version)
                log.info("copy bundled browser %s -> %s", src_version, dst_version)
                shutil.copytree(src_version, dst_version)

            rel = dst_version.relative_to(INSTALL_DIR).as_posix()
            if not active_set:
                try:
                    set_active(rel)
                    active_set = True
                except Exception:
                    pass

    if active_set:
        try:
            COMPAT_FLAG.touch()
        except Exception:
            pass

    return active_set
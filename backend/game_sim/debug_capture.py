"""DebugCapture — chụp ảnh màn hình + dump HTML khi lỗi."""
import logging
from pathlib import Path

from core.time_utils import utcnow_iso

log = logging.getLogger("game_sim.debug")


class DebugCapture:
    def __init__(self, save_dir):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, label: str, ext: str) -> Path:
        ts = utcnow_iso().replace(":", "-").split("+")[0]
        return self.save_dir / f"{label}_{ts}.{ext}"

    async def screenshot(self, page, label: str) -> str:
        if page is None:
            return ""
        path = self._path(label, "png")
        try:
            await page.screenshot(path=str(path), full_page=True)
            log.info("screenshot saved: %s", path)
            return str(path)
        except Exception as e:
            log.warning("screenshot fail: %s", e)
            return ""

    async def dump_html(self, page, label: str) -> str:
        if page is None:
            return ""
        path = self._path(label, "html")
        try:
            html = await page.content()
            path.write_text(html, encoding="utf-8")
            log.info("html dump saved: %s", path)
            return str(path)
        except Exception as e:
            log.warning("html dump fail: %s", e)
            return ""
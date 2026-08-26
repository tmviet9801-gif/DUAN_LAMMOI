"""Platform config — mỗi cổng game là 1 bản riêng.

Bản HITCLUB và bản B52 dùng chung mã nguồn nhưng khác platform_config.
Khi build bản B52, chỉ cần đổi preset này (id/app_name/url/adapter) —
dữ liệu (accounts/proxies/license) tách riêng theo platform id.
"""
import logging
import sys
from pathlib import Path

log = logging.getLogger("platform")

# ---- preset mặc định (đổi thành "B52" khi build bản B52) ----
PLATFORM_ID = "HITCLUB"
PLATFORM_NAME = "AutoTool HITCLUB"
PLATFORM_GAME_URL = "https://play.hitclub.voting/?a=hitclub"
PLATFORM_ADAPTER = "hitclub"
PLATFORM_MAX_TABS = 10
PLATFORM_OWNER_EMAIL = ""  # hiển thị trong phần trợ giúp license


def data_dir() -> Path:
    """Thư mục dữ liệu — tách riêng theo platform để 2 bản không dùng chung."""
    if getattr(sys, "frozen", False):
        import os

        base = Path(os.environ.get("APPDATA", str(Path.home()))) / f"AutoTool_{PLATFORM_ID}"
    else:
        base = Path(__file__).resolve().parent  # backend/
    d = base / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def info() -> dict:
    return {
        "platform": PLATFORM_ID,
        "name": PLATFORM_NAME,
        "game_url": PLATFORM_GAME_URL,
        "adapter": PLATFORM_ADAPTER,
        "max_tabs": PLATFORM_MAX_TABS,
        "owner_email": PLATFORM_OWNER_EMAIL,
    }

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
PLATFORM_GAME_URL = "https://v.hitclub.latino/?a=hitclub"
PLATFORM_ADAPTER = "hitclub"
PLATFORM_MAX_TABS = 10
PLATFORM_OWNER_EMAIL = ""  # hiển thị trong phần trợ giúp license

# URL mặc định cho profile khi tạo mới (trỏ vào game)
DEFAULT_PROFILE_URL = PLATFORM_GAME_URL

# Token chủ sở hữu — dùng để mở khóa panel sinh license trong app.
# CHỈ owner biết; đổi trước khi build. Nếu để trống, panel sinh license tắt.
OWNER_TOKEN = "AutoToolOwner@2026"


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

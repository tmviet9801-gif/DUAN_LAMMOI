"""Platform config — mỗi cổng game là 1 bản riêng.

Bản HITCLUB và bản B52 dùng chung mã nguồn nhưng khác platform_config.
Khi build bản B52, chỉ cần đổi preset này (id/app_name/url/adapter) —
dữ liệu (accounts/proxies/license) tách riêng theo platform id.
"""
import logging
import re
import sys
from pathlib import Path

log = logging.getLogger("platform")

# ---- preset mặc định (đổi thành "B52" khi build bản B52) ----
PLATFORM_ID = "HITCLUB"
PLATFORM_NAME = "AutoTool HITCLUB"
PLATFORM_GAME_URL = "https://v.hitclub.latino/?a=hitclub"
PLATFORM_ADAPTER = "hitclub"

# Cổng game đổi tên miền liên tục (v.hitclub.latino -> .bike -> .chat -> .email…).
# Không khớp cứng theo tên miền đầy đủ: chỉ cần URL có chứa từ khoá này là coi
# như đang ở trang game. Bản B52 chỉ cần đổi "hitclub" thành "b52".
PLATFORM_URL_KEYWORD = "hitclub"
GAME_URL_RE = re.compile(re.escape(PLATFORM_URL_KEYWORD), re.IGNORECASE)


def is_game_url(url) -> bool:
    """URL này có phải trang của cổng game không (bất kể tên miền/TLD)?

    Dùng thay cho mọi so khớp cứng `v.hitclub.<tld>`, để site đổi tên miền là
    tool vẫn nhận ra và KHÔNG điều hướng lại (điều hướng lại = mất đăng nhập,
    vì game này không giữ phiên qua reload).
    """
    if not url:
        return False
    return bool(GAME_URL_RE.search(str(url)))
PLATFORM_MAX_TABS = 10
PLATFORM_OWNER_EMAIL = ""  # hiển thị trong phần trợ giúp license

# URL mặc định cho profile khi tạo mới (trỏ vào game)
DEFAULT_PROFILE_URL = PLATFORM_GAME_URL

# Token chủ sở hữu — dùng để mở khóa panel sinh license trong app.
# CHỈ owner biết; đổi trước khi build. Nếu để trống, panel sinh license tắt.
OWNER_TOKEN = "AutoToolOwner@2026"

# ---- Máy chủ license (portal quản trị) ----
# Key là HMAC tự chứa hạn dùng nên app kiểm tra được offline; nhưng thu hồi
# license CHỈ có hiệu lực nếu app hỏi lại máy chủ. Điền URL portal vào đây để bật.
# Để TRỐNG = tắt hoàn toàn, app chạy y như trước (thuần offline).
LICENSE_SERVER_URL = ""

# Máy chủ không gọi được (mất mạng, sập server) thì app vẫn chạy bằng kết quả
# kiểm tra lần trước, trong tối đa từng này ngày. Quá hạn đó mới khoá.
LICENSE_OFFLINE_GRACE_DAYS = 7

# Khoảng cách giữa hai lần tự kiểm tra nền (giây).
LICENSE_CHECK_INTERVAL = 6 * 3600


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

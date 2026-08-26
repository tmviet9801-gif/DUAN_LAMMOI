"""Các hàm tiện ích dùng chung (chuỗi, đường dẫn)."""
import os
import re
import unicodedata
from pathlib import Path


def slugify(name) -> str:
    """Chuẩn hóa tên thành slug an toàn cho tên thư mục (vd profile)."""
    s = unicodedata.normalize("NFKD", str(name))
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s[:48] or "profile"


def expand_user_path(raw) -> Path:
    """Mở rộng %ENV% và ~ trong đường dẫn, trả Path tuyệt đối."""
    return Path(os.path.expandvars(os.path.expanduser(str(raw)))).resolve()

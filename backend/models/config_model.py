"""Model cấu hình + dữ liệu (config, accounts, thư mục dữ liệu).

Chịu trách nhiệm: lưu/đọc config.json, accounts.json, xác định thư mục
data/profiles. Không chứa logic nghiệp vụ trình duyệt.
"""
import json
import os
import sys
import uuid
from pathlib import Path

from core.time_utils import utcnow_iso
from core.utils import slugify
from platform_config import DEFAULT_PROFILE_URL, PLATFORM_ID, PLATFORM_NAME

APP_NAME = PLATFORM_NAME
APP_VERSION = "1.2.0"


def get_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Tách dữ liệu theo cổng game: AutoTool_HITCLUB, AutoTool_B52...
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / f"AutoTool_{PLATFORM_ID}"
    else:
        base = Path(__file__).resolve().parent.parent  # backend/
    return base / "data"


DATA_DIR = get_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "grid": {
        "cols": 5,
        "gap": 8,
        "margin": 4,
    },
    "window": {
        "width": 0,
        "height": 0,
    },
    "open_direction": "row",
    "anti_detect": {
        "locale": "random",
    },
    "default_count": 10,
    "auto_layout": True,
    "mute_all_sites": False,
    "profiles_dir": "",
    "default_url": DEFAULT_PROFILE_URL,
}


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict:
    cfg = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    for key in ("grid", "window", "anti_detect"):
        merged[key] = {**DEFAULT_CONFIG[key], **(cfg.get(key) or {})}
    return merged


def save_config(config: dict):
    save_json(CONFIG_FILE, config)


def get_profiles_dir() -> Path:
    """Thư mục lưu profile (cookies, đăng nhập). Có thể cấu hình trong config.json."""
    cfg = load_config()
    raw = (cfg.get("profiles_dir") or "").strip()
    if raw:
        try:
            p = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass
    default = DATA_DIR / "profiles"
    default.mkdir(parents=True, exist_ok=True)
    return default


def make_profile_dir(name: str, account_id: str) -> str:
    short = account_id[:8] if account_id else uuid.uuid4().hex[:8]
    return str(get_profiles_dir() / f"{slugify(name)}-{short}")


def load_accounts() -> list:
    return load_json(ACCOUNTS_FILE, [])


def save_accounts(accounts: list):
    save_json(ACCOUNTS_FILE, accounts)


def new_account_record(account: dict, existing: list | None = None) -> dict:
    """Tạo record account mới (id, profile_dir).

    Luôn bật lưu session riêng (save_session=True) cho mọi profile.
    `existing`: giữ tham số để tương thích chữ ký cũ (không còn dùng).
    """
    account_id = str(uuid.uuid4())
    record = {"id": account_id, "created_at": utcnow_iso(), **account}
    record["save_session"] = True
    record["profile_dir"] = make_profile_dir(record.get("name") or "profile", account_id)
    return record


def ensure_accounts_save_session(accounts: list) -> tuple[list, int]:
    """Bật lưu session cho mọi account (migration cho account cũ).

    - save_session -> True
    - tạo profile_dir nếu còn thiếu
    Trả về (accounts, số lượng đã sửa).
    """
    changed = 0
    for a in accounts:
        if not a.get("save_session"):
            a["save_session"] = True
            changed += 1
        if not a.get("profile_dir"):
            a["profile_dir"] = make_profile_dir(a.get("name") or "profile", a.get("id"))
            changed += 1
    return accounts, changed


PROFILES_DIR = get_profiles_dir()  # noqa: E402 — giữ cho tương thích import cũ

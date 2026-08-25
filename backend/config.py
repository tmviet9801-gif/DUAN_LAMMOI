import json
import os
import re
import sys
import unicodedata
import uuid
from pathlib import Path

APP_NAME = "AutoTool"
APP_VERSION = "1.0.2"


def get_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    else:
        base = Path(__file__).resolve().parent
    return base / "data"


DATA_DIR = get_data_dir()
PROFILES_DIR = DATA_DIR / "profiles"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR.mkdir(exist_ok=True)

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
        "os": "random",
        "locale": "random",
    },
    "default_count": 10,
    "auto_layout": True,
}


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_accounts():
    return load_json(ACCOUNTS_FILE, [])


def save_accounts(accounts):
    save_json(ACCOUNTS_FILE, accounts)


def _slugify(name):
    s = unicodedata.normalize("NFKD", str(name))
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s[:48] or "profile"


def make_profile_dir(name, account_id):
    short = account_id[:8] if account_id else uuid.uuid4().hex[:8]
    return str(PROFILES_DIR / f"{_slugify(name)}-{short}")


def load_config():
    cfg = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    for key in ("grid", "window", "anti_detect"):
        merged[key] = {**DEFAULT_CONFIG[key], **(cfg.get(key) or {})}
    return merged


def save_config(config):
    save_json(CONFIG_FILE, config)

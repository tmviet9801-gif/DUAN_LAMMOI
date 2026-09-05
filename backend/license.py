"""License — quản lý cho thuê tool.

- Key dạng AUTO-<sig>-<base64(payload)>.
- payload = machine_id|expiry_ts|max_tabs|features, ký HMAC-SHA256.
- Bind máy (MachineGuid), có hạn, giới hạn số tab.
- Owner dùng tools/make_license.py để sinh key cho từng máy khách.
"""
import base64
import hashlib
import hmac
import json
import logging
import platform
import time
from pathlib import Path

from platform_config import data_dir

log = logging.getLogger("license")

# SECRET đổi khi phát hành riêng (owner giữ). Đừng commit secret thật.
SECRET = b"AutoToolLicenseSecret_ChangeMe_2026"

LICENSE_FILE = data_dir() / "license.json"


def get_machine_id() -> str:
    """Lấy MachineGuid (bind 1 máy)."""
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return value.strip().lower()
    except Exception:
        return platform.node() or "unknown-machine"


def _sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:16]


def make_key(machine_id: str, days: int, max_tabs: int, features: str = "game") -> str:
    """Sinh license key cho 1 máy (dùng bởi owner)."""
    expiry = int(time.time()) + days * 86400
    payload = f"{machine_id}|{expiry}|{max_tabs}|{features}"
    sig = _sign(payload)
    b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"AUTO-{sig}-{b64}"


def parse_key(key: str) -> dict | None:
    try:
        rest = key.strip().split("-", 1)[1]  # bỏ "AUTO-"
        sig = rest[:16]                       # sig luôn 16 ký tự hex
        b64 = rest[17:]                       # bỏ dấu "-" ngăn cách
        payload = base64.urlsafe_b64decode(b64.encode()).decode()
        machine_id, expiry, max_tabs, features = payload.split("|")
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        return {
            "machine_id": machine_id,
            "expiry": int(expiry),
            "max_tabs": int(max_tabs),
            "features": features,
        }
    except Exception:
        return None


def validate_key(key: str, machine_id: str | None = None) -> dict:
    data = parse_key(key)
    if not data:
        return {"valid": False, "reason": "invalid_key"}
    mid = machine_id or get_machine_id()
    if data["machine_id"] != mid:
        return {"valid": False, "reason": "wrong_machine"}
    if data["expiry"] < time.time():
        return {"valid": False, "reason": "expired"}
    return {"valid": True, **data}


# ---- lưu trạng thái kích hoạt ----
def load_license() -> dict | None:
    try:
        if LICENSE_FILE.exists():
            return json.loads(LICENSE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def save_license(data: dict):
    LICENSE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def activate(key: str) -> dict:
    result = validate_key(key)
    if not result["valid"]:
        return result
    save_license({"key": key.strip(), "activated_at": int(time.time())})
    log.info("license activated (max_tabs=%s, expiry=%s)", result["max_tabs"], result["expiry"])
    return {"valid": True, **result}


def deactivate():
    if LICENSE_FILE.exists():
        LICENSE_FILE.unlink()
    return {"ok": True}


def status() -> dict:
    machine_id = get_machine_id()
    lic = load_license()
    if not lic:
        return {"activated": False, "valid": False, "machine_id": machine_id, "reason": "not_activated", "key": ""}
    result = validate_key(lic["key"], machine_id)
    return {
        "activated": True,
        "valid": result["valid"],
        "reason": result.get("reason"),
        "machine_id": machine_id,
        "expires_at": result.get("expiry"),
        "max_tabs": result.get("max_tabs", PLATFORM_DEFAULT_MAX_TABS),
        "features": result.get("features", "game"),
        "key": lic.get("key", ""),
    }


def max_tabs() -> int:
    st = status()
    if st.get("valid"):
        return int(st.get("max_tabs", 10))
    return 0


PLATFORM_DEFAULT_MAX_TABS = 10

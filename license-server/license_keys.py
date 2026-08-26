"""Sinh/parse license key — giống hệt backend/license.py để key tương thích.

SECRET phải khớp với backend/license.py (đọc từ config.LICENSE_SECRET).
"""
import base64
import hashlib
import hmac

from config import LICENSE_SECRET


def _sign(payload: str) -> str:
    return hmac.new(LICENSE_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:16]


def make_key(machine_id: str, expiry_ts: int, max_tabs: int, features: str = "game") -> str:
    payload = f"{machine_id}|{int(expiry_ts)}|{int(max_tabs)}|{features}"
    sig = _sign(payload)
    b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"AUTO-{sig}-{b64}"


def parse_key(key: str) -> dict | None:
    try:
        rest = key.strip().split("-", 1)[1]
        sig = rest[:16]
        b64 = rest[17:]
        payload = base64.urlsafe_b64decode(b64.encode()).decode()
        machine_id, expiry, max_tabs, features = payload.split("|")
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        return {"machine_id": machine_id, "expiry": int(expiry), "max_tabs": int(max_tabs), "features": features}
    except Exception:
        return None
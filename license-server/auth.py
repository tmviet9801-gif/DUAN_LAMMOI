"""Admin session — HMAC-signed token, không cần thêm thư viện."""
import base64
import hashlib
import hmac
import time

from config import ADMIN_PASSWORD, SESSION_TTL


def _secret() -> bytes:
    return (ADMIN_PASSWORD + ":licadmin").encode()


def create_session() -> str:
    exp = int(time.time()) + SESSION_TTL
    payload = f"adm:{exp}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def verify_session(token: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(":", 1)
        exp = int(payload.split(":")[1])
        if exp < time.time():
            return False
        return hmac.compare_digest(
            hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32],
            sig,
        )
    except Exception:
        return False
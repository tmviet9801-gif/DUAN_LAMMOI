"""License — quản lý cho thuê tool.

- Key dạng AUTO-<sig>-<base64(payload)>.
- payload = machine_id|expiry_ts|max_tabs|features, ký HMAC-SHA256.
- Bind máy (MachineGuid), có hạn, giới hạn số tab.
- Owner sinh key bằng dự án quản trị riêng; app KHÔNG tự sinh được key.

Kiểm tra online (tuỳ chọn, bật bằng LICENSE_SERVER_URL):
    Chữ ký HMAC tự chứa hạn dùng nên key vẫn xác thực được khi không có mạng —
    nhưng cũng vì thế, THU HỒI license không có tác dụng nếu app không hỏi lại
    máy chủ. Nên app hỏi portal định kỳ và ghi kết quả vào license.json.

    status() KHÔNG bao giờ gọi mạng: nó chỉ đọc kết quả đã lưu. Việc gọi mạng
    do task nền trong main.py đảm nhiệm. Lý do: status() là hàm đồng bộ, được
    gọi từ route async ở đường đi nóng (mở tab, mở trình duyệt) — gọi HTTP ở đó
    sẽ chặn event loop và treo cả app khi mạng chậm.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import platform
import time
from pathlib import Path

from platform_config import (
    ALLOW_LEGACY_HMAC,
    LICENSE_CHECK_INTERVAL,
    LICENSE_OFFLINE_GRACE_DAYS,
    LICENSE_PUBLIC_KEY,
    LICENSE_SERVER_URL,
    data_dir,
)

log = logging.getLogger("license")

# SECRET của scheme HMAC đời cũ (v1). Đối xứng: khoá này vừa ký vừa kiểm tra.
#
# KHÔNG hardcode nó ở đây nữa. Mã hoá hay giấu chuỗi trong file exe đều vô ích:
# app phải giải mã được để dùng, nên khoá giải mã cũng nằm trong exe — kẻ dịch
# ngược chỉ tốn thêm một bước. Cách duy nhất chắc chắn là KHÔNG có bí mật nào
# trong bản gửi khách.
#
# Giá trị đọc từ biến môi trường, chỉ đặt trên máy dev khi cần test key v1.
# Bản build cho khách không có biến này -> SECRET rỗng -> key v1 tự động vô hiệu.
SECRET = os.environ.get("AUTOTOOL_LEGACY_SECRET", "").encode()

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
    if not SECRET:
        raise RuntimeError(
            "Khong co AUTOTOOL_LEGACY_SECRET — ban nay khong ky/kiem tra duoc key HMAC doi cu"
        )
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:16]


def make_key(machine_id: str, days: int, max_tabs: int, features: str = "game") -> str:
    """Sinh license key HMAC đời cũ.

    CHỈ còn dùng cho test và cho panel owner khi ALLOW_LEGACY_HMAC=True.
    Bản thương mại phải cấp key từ portal (Ed25519) — app không giữ khoá ký.
    """
    expiry = int(time.time()) + days * 86400
    payload = f"{machine_id}|{expiry}|{max_tabs}|{features}"
    sig = _sign(payload)
    b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"AUTO-{sig}-{b64}"


def _b64url_decode(text: str) -> bytes:
    """base64url không padding -> bytes (tự bù dấu '=')."""
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _split_payload(payload: str) -> dict | None:
    parts = payload.split("|")
    if len(parts) != 4:
        return None
    machine_id, expiry, max_tabs, features = parts
    try:
        return {
            "machine_id": machine_id,
            "expiry": int(expiry),
            "max_tabs": int(max_tabs),
            "features": features,
        }
    except ValueError:
        return None


def _parse_key_v1(key: str) -> dict | None:
    """AUTO-<sig16>-<base64url(payload)> — HMAC-SHA256, khoá đối xứng."""
    if not ALLOW_LEGACY_HMAC or not SECRET:
        return None
    try:
        rest = key.strip().split("-", 1)[1]  # bỏ "AUTO-"
        sig = rest[:16]                       # sig luôn 16 ký tự hex
        b64 = rest[17:]                       # bỏ dấu "-" ngăn cách
        payload = base64.urlsafe_b64decode(b64.encode()).decode()
        data = _split_payload(payload)
        if not data:
            return None
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        return {**data, "algo": "hmac"}
    except Exception:
        return None


def _parse_key_v2(key: str) -> dict | None:
    """AUTO2.<base64url(payload)>.<base64url(chữ ký 64 byte)> — Ed25519."""
    if not LICENSE_PUBLIC_KEY:
        return None
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        log.error("thiếu thư viện 'cryptography' — không kiểm tra được key Ed25519")
        return None

    try:
        parts = key.strip().split(".")
        if len(parts) != 3 or parts[0] != "AUTO2":
            return None
        _, payload_b64, sig_b64 = parts

        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(LICENSE_PUBLIC_KEY))
        # Chữ ký ký trên CHUỖI base64url của payload, không phải payload thô.
        public_key.verify(_b64url_decode(sig_b64), payload_b64.encode())

        data = _split_payload(_b64url_decode(payload_b64).decode())
        return {**data, "algo": "ed25519"} if data else None
    except InvalidSignature:
        return None
    except Exception:
        return None


def parse_key(key: str) -> dict | None:
    """Đọc key, nhận cả hai định dạng, tự nhận dạng theo tiền tố."""
    text = (key or "").strip()
    if not text:
        return None
    if text.startswith("AUTO2."):
        return _parse_key_v2(text)
    if text.startswith("AUTO-"):
        return _parse_key_v1(text)
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


# ---- kiểm tra với máy chủ license ----

# Máy chủ trả các lý do này = key hết hiệu lực, khoá ngay không cần ân hạn.
_FATAL_VERDICTS = ("revoked", "suspended", "key_not_issued", "expired", "wrong_machine")

_VERDICT_MESSAGE = {
    "revoked": "License đã bị thu hồi",
    "suspended": "License đang bị tạm treo",
    "key_not_issued": "Key này không có trong hệ thống",
    "expired": "License đã hết hạn",
    "wrong_machine": "Key không dành cho máy này",
    "offline_too_long": "Không liên lạc được máy chủ license quá lâu",
}


def server_enabled() -> bool:
    """Có bật kiểm tra online không? Không bật thì app chạy thuần offline như cũ."""
    return bool(str(LICENSE_SERVER_URL).strip())


def verdict_message(reason: str) -> str:
    return _VERDICT_MESSAGE.get(reason, "")


def _grace_seconds() -> int:
    return max(0, int(LICENSE_OFFLINE_GRACE_DAYS)) * 86400


async def check_online(key: str | None = None, machine_id: str | None = None) -> dict:
    """Hỏi máy chủ xem key còn hiệu lực không, rồi ghi kết quả vào license.json.

    Mất mạng thì KHÔNG đụng tới kết quả cũ — ân hạn vẫn đếm từ lần thành công
    gần nhất, nên rớt mạng tạm thời không làm khách mất quyền dùng.
    """
    if not server_enabled():
        return {"ok": False, "error": "disabled"}

    lic = load_license()
    key = key or (lic or {}).get("key") or ""
    if not key:
        return {"ok": False, "error": "not_activated"}

    machine_id = machine_id or get_machine_id()
    url = str(LICENSE_SERVER_URL).rstrip("/") + "/api/public/verify"

    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json={"key": key, "machine_id": machine_id})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        # Không có mạng / server sập: giữ nguyên kết quả cũ, chỉ ghi lại lần thử.
        log.warning("license: không hỏi được máy chủ (%s)", exc)
        return {"ok": False, "error": "unreachable"}

    verdict = "valid" if data.get("valid") else (data.get("reason") or "invalid")
    _save_server_check(verdict)
    if verdict != "valid":
        log.warning("license: máy chủ từ chối key (%s)", verdict)
    return {"ok": True, "verdict": verdict, "data": data}


def _save_server_check(verdict: str):
    lic = load_license()
    if not lic:
        return
    lic["server_check"] = {"at": int(time.time()), "verdict": verdict}
    try:
        save_license(lic)
    except Exception:
        log.exception("license: không ghi được kết quả kiểm tra")


def _apply_server_check(lic: dict, result: dict) -> dict:
    """Đối chiếu kết quả kiểm tra online đã lưu với kết quả xác thực offline.

    Trả về dict bổ sung cho status(): có thể lật valid thành False.
    """
    check = lic.get("server_check") or {}
    verdict = check.get("verdict")
    checked_at = int(check.get("at") or 0)
    now = int(time.time())

    extra = {
        "server_verdict": verdict or None,
        "server_checked_at": checked_at or None,
    }

    # Máy chủ đã nói key chết -> khoá ngay, không ân hạn.
    if verdict in _FATAL_VERDICTS:
        extra.update({"valid": False, "reason": verdict})
        return extra

    # Chưa từng kiểm tra được lần nào: đếm ân hạn từ lúc kích hoạt.
    last_ok = checked_at if verdict == "valid" else int(lic.get("activated_at") or 0)
    grace = _grace_seconds()
    if grace and last_ok and now - last_ok > grace:
        extra.update({"valid": False, "reason": "offline_too_long"})
        return extra

    if grace and last_ok:
        extra["grace_days_left"] = max(0, (last_ok + grace - now) // 86400)
    return extra


def status() -> dict:
    """Trạng thái license. Hàm đồng bộ, CHỈ đọc file — không bao giờ gọi mạng."""
    machine_id = get_machine_id()
    lic = load_license()
    if not lic:
        return {"activated": False, "valid": False, "machine_id": machine_id, "reason": "not_activated", "key": ""}

    result = validate_key(lic["key"], machine_id)
    out = {
        "activated": True,
        "valid": result["valid"],
        "reason": result.get("reason"),
        "machine_id": machine_id,
        "expires_at": result.get("expiry"),
        "max_tabs": result.get("max_tabs", PLATFORM_DEFAULT_MAX_TABS),
        "features": result.get("features", "game"),
        "key": lic.get("key", ""),
        "key_algo": result.get("algo") or ("ed25519" if lic["key"].startswith("AUTO2.") else "hmac"),
        "server_enabled": server_enabled(),
    }

    # Chữ ký offline hợp lệ chưa đủ: còn phải chưa bị máy chủ thu hồi.
    if out["valid"] and server_enabled():
        out.update(_apply_server_check(lic, result))

    if not out["valid"]:
        out["message"] = verdict_message(out.get("reason") or "")
    return out


def max_tabs() -> int:
    st = status()
    if st.get("valid"):
        return int(st.get("max_tabs", 10))
    return 0


PLATFORM_DEFAULT_MAX_TABS = 10

# Khoảng cách giữa hai lần tự kiểm tra nền (main.py dùng).
CHECK_INTERVAL = LICENSE_CHECK_INTERVAL

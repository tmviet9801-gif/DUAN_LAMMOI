"""Service: nghiệp vụ tài khoản (fingerprint tự động khi thiếu)."""
import logging

from models.config_model import load_accounts, save_accounts
from models.fingerprint_model import diverse_os, random_chrome_ua

log = logging.getLogger("account_service")


def ensure_account_fingerprints(accounts: list) -> list:
    """Gán profile_os + profile_ua cho account có save_session nhưng chưa có UA."""
    changed = False
    for a in accounts:
        if a.get("save_session") and not a.get("profile_ua") and not a.get("user_agent"):
            os_name = diverse_os(a.get("profile_os") for a in accounts)
            a["profile_os"] = os_name
            a["profile_ua"] = random_chrome_ua(os_name)
            changed = True
    if changed:
        save_accounts(accounts)
        log.info("updated fingerprints for %d accounts", changed)
    return accounts


def bulk_names(prefix: str, count: int) -> list[str]:
    """Sinh tên hàng loạt theo số thứ tự zero-padded.

    count=1  -> ["A"]
    count=10 -> ["A01", "A02", ..., "A10"]  (tránh lỗi sort A1, A10, A11...)
    count=100 -> ["A001", ...]
    """
    count = max(1, int(count))
    width = max(2, len(str(count)))
    prefix = (prefix or "").strip()
    if count == 1:
        return [prefix]
    return [f"{prefix}{str(i).zfill(width)}" for i in range(1, count + 1)]

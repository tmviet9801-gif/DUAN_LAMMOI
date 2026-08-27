"""Token store — lưu token login HITCLUB (localStorage) cho mỗi profile.

Game HITCLUB trả token MỚI mỗi lần login (vd login.aspx -> token "1-xxx"),
nên token cũ bị expire -> profile "vẫn không login được" nếu ta restore
token cũ. Ta chủ động lưu token mỗi khi có login MỚI (token thay đổi) vào
file này, và khi mở lại profile sẽ ưu tiên dùng token mới nhất thay vì
token cũ trong web_storage.

Cấu trúc file (DATA_DIR/game_sim_token.json):
  { "<account_name>": {"token": "1-xxx", "username": "...", "saved_at": "..."} }
"""
import json
import logging
import re
from pathlib import Path

from core.time_utils import utcnow_iso

log = logging.getLogger("game_sim.token_store")

_TOKEN_RE = re.compile(r"1-[0-9a-f]{32}", re.I)


class TokenStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self):
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except Exception:
            pass
        return {}

    def _persist(self):
        try:
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.warning("token persist fail: %s", e)

    @staticmethod
    def _normalize(tok):
        if not tok:
            return None
        m = _TOKEN_RE.search(str(tok))
        if m:
            return m.group(0)
        return str(tok).strip() if str(tok).startswith("1-") else None

    def save(self, account_name, token, extra=None) -> bool:
        """Lưu token nếu là token MỚI (khác với đã lưu). Trả True nếu có thay đổi."""
        if not account_name or not token:
            return False
        token = self._normalize(token)
        if not token:
            return False
        prev = self._data.get(account_name, {}).get("token")
        if prev == token:
            return False
        rec = {"token": token, "saved_at": utcnow_iso()}
        if extra:
            rec.update(extra)
        self._data[account_name] = rec
        self._persist()
        log.info("token store: saved NEW token for %s (prev=%s)", account_name, bool(prev))
        return True

    def get(self, account_name):
        return self._data.get(account_name, {}).get("token")

    def get_record(self, account_name):
        return self._data.get(account_name)

    def clear(self, account_name=None):
        if account_name:
            self._data.pop(account_name, None)
        else:
            self._data.clear()
        self._persist()

    @staticmethod
    def extract_from_storage(storage: dict) -> str | None:
        """Từ dict localStorage/sessionStorage, tìm value chứa token '1-<32hex>'."""
        if not isinstance(storage, dict):
            return None
        # ưu tiên key 'token' / 'user_token'
        for key in ("token", "user_token", "accessToken"):
            v = storage.get(key)
            if v:
                tok = TokenStore._normalize(v)
                if tok:
                    return tok
        for v in storage.values():
            if isinstance(v, str):
                tok = TokenStore._normalize(v)
                if tok:
                    return tok
        return None

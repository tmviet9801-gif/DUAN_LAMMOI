"""Token store — lưu token login HITCLUB (localStorage) cho mỗi profile.

Game HITCLUB trả token MỚI mỗi lần login (vd login.aspx -> token "1-xxx"),
nên token cũ bị expire -> profile "vẫn không login được" nếu ta restore
token cũ. Ta chủ động lưu token mỗi khi có login MỚI (token thay đổi) vào
file này, và khi mở lại profile sẽ ưu tiên dùng token mới nhất thay vì
token cũ trong web_storage.

Cấu trúc file (DATA_DIR/game_sim_token.json):
  { "<account_id>": {"token": "1-xxx", "account_id": "...", "account_name": "...",
                     "username": "...", "saved_at": "..."} }

KHOÁ CHÍNH TẮC LÀ `account["id"]` (uuid4), không phải tên profile. Người dùng
đổi tên account được (`PATCH /api/accounts/{id}`), và bản trước không di trú
khoá theo -> token bị bỏ rơi dưới khoá cũ, lần lưu sau đẻ khoá mới. Kho từng
tích tụ 9 khoá cho 5 account theo đúng cách đó.

Ba bất biến, rút ra từ vòng phản bác:

1. GHI LÀ ĐỌC-SỬA-GHI DƯỚI KHOÁ, KHÔNG PHẢI GHI ĐÈ.
   Có ÍT NHẤT 4 nơi tự dựng `TokenStore` riêng (check_live, hitclub adapter,
   browser_service, routes_basic). Bản trước nạp file một lần trong `__init__`
   rồi `_persist()` ghi cả dict — nên bản ghi sau XOÁ MẤT thay đổi của bản
   trước (lost update). Nay mỗi lần ghi đều đọc lại đĩa trong lock rồi mới
   trộn, và ghi bằng file tạm + replace để không bao giờ để lại file cụt.

2. LOCK PHẢI REENTRANT.
   Các phương thức công khai gọi lẫn nhau (`save` -> `save_for_account`).
   `threading.Lock` thường sẽ tự khoá chính mình; và vì các đường gọi này nằm
   trên event loop của backend, deadlock làm đứng hình cả tiến trình chứ
   không chỉ một request.

3. ĐƯỜNG ĐỌC KHÔNG BAO GIỜ XOÁ.
   Ý tưởng "đọc xong tự lành, chép sang khoá id rồi xoá khoá cũ" nghe hợp lý
   nhưng nguy hiểm: một account MỚI tạo bằng Thêm hàng loạt có thể trùng tên
   với khoá cũ của account KHÁC (`bulk_names` sinh đúng "Account01"...), và
   đường đọc chỉ nhìn thấy MỘT account nên không thể biết khoá đó còn khớp ai
   nữa. Nó sẽ trao token người cũ cho người mới rồi xoá mất đường lùi. Chỉ
   `migrate()` được xoá, vì chỉ nó nhìn thấy TOÀN BỘ danh sách account để áp
   luật nhập nhằng, và chỉ nó tạo bản sao lưu trước.
"""
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from core.time_utils import utcnow_iso

log = logging.getLogger("game_sim.token_store")

_TOKEN_RE = re.compile(r"1-[0-9a-f]{32}", re.I)

# Một RLock cho mỗi đường dẫn file: các TokenStore khác nhau trỏ cùng một file
# phải loại trừ nhau. RLock (không phải Lock) vì phương thức công khai gọi nhau.
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    khoa = str(Path(path).resolve()).lower()
    with _LOCKS_GUARD:
        if khoa not in _LOCKS:
            _LOCKS[khoa] = threading.RLock()
        return _LOCKS[khoa]


def chuan(s) -> str:
    """Chuẩn hoá một định danh để đối chiếu khoá: bỏ dấu cách, thường hoá."""
    return str(s or "").strip().replace(" ", "").lower()


class TokenStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.path)
        # Đọc dưới khoá: trên Windows, `os.replace` của luồng khác sẽ báo
        # "Access is denied" nếu file đích đang được mở đọc.
        with self._lock:
            self._data = self._doc_dia()

    # ---------- đĩa ----------

    def _doc_dia(self) -> dict:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8") or "{}")
                if isinstance(d, dict):
                    return d
        except Exception as e:
            log.warning("token store: đọc %s lỗi: %s", self.path, e)
        return {}

    def _ghi_dia(self, data: dict) -> bool:
        """Ghi nguyên tử: file tạm rồi replace. Không để lại file cụt khi tắt máy."""
        # Tên file tạm KÈM id luồng: hai luồng cùng ghi mà dùng chung một file
        # tạm thì `os.replace` của luồng này xoá mất file tạm của luồng kia.
        tam = self.path.with_suffix(f"{self.path.suffix}.{threading.get_ident()}.tmp")
        try:
            tam.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            # Windows từ chối replace khi file đích đang bị mở (trình quét
            # virus, indexer, hoặc một tiến trình khác của chính app). Đây là
            # sự cố THOÁNG QUA — bỏ cuộc ngay là mất token.
            loi = None
            for lan in range(6):
                try:
                    os.replace(tam, self.path)
                    return True
                except PermissionError as e:
                    loi = e
                    time.sleep(0.02 * (lan + 1))
            raise loi
        except Exception as e:
            log.warning("token persist fail: %s", e)
            try:
                tam.unlink(missing_ok=True)
            except Exception:
                pass
            return False

    def _sua(self, ham):
        """Đọc-sửa-ghi dưới khoá. `ham(data)` trả True nếu có thay đổi cần ghi."""
        with self._lock:
            data = self._doc_dia()          # đọc lại: tiến trình/instance khác có thể đã ghi
            doi = ham(data)
            self._data = data
            if doi:
                self._ghi_dia(data)
            return doi

    # ---------- chuẩn hoá ----------

    @staticmethod
    def _normalize(tok):
        if not tok:
            return None
        m = _TOKEN_RE.search(str(tok))
        if m:
            return m.group(0)
        return str(tok).strip() if str(tok).startswith("1-") else None

    @staticmethod
    def _dinh_danh(account) -> set:
        """Mọi chuỗi có thể đã từng được dùng làm khoá cho account này."""
        if not isinstance(account, dict):
            return set()
        ra = set()
        for truong in ("id", "name", "username", "character_name"):
            v = chuan(account.get(truong))
            if v:
                ra.add(v)
        return ra

    # ---------- ghi ----------

    def save_for_account(self, account, token, extra=None) -> bool:
        """Ghi token dưới khoá CHÍNH TẮC (`account["id"]`).

        Trả True nếu kho thay đổi. Không có `id` thì lùi về `save()` theo tên —
        thà ghi dưới khoá thô còn hơn vứt mất token.
        """
        if not isinstance(account, dict):
            return False
        acc_id = str(account.get("id") or "").strip()
        if not acc_id:
            return self.save(account.get("name") or account.get("username"),
                             token, extra=extra)

        token = self._normalize(token)
        if not token:
            return False

        rec = {
            "token": token,
            "saved_at": utcnow_iso(),
            "account_id": acc_id,
            "account_name": account.get("name"),
            "username": account.get("username"),
        }
        if extra:
            rec.update(extra)

        def _lam(data):
            cu = data.get(acc_id) or {}
            if cu.get("token") == token and cu.get("account_id") == acc_id:
                return False
            data[acc_id] = rec
            return True

        doi = self._sua(_lam)
        if doi:
            log.info("token store: lưu token cho %s (id=%s)",
                     account.get("name"), acc_id[:8])
        return doi

    def save(self, account_name, token, extra=None) -> bool:
        """Ghi theo TÊN. Giữ cho các chỗ gọi cũ không vỡ.

        Chỗ gọi nào biết account dict thì nên dùng `save_for_account` — khoá
        theo tên sẽ mồ côi ngay khi người dùng đổi tên account.
        """
        if not account_name or not token:
            return False
        token = self._normalize(token)
        if not token:
            return False

        khoa = str(account_name)
        rec = {"token": token, "saved_at": utcnow_iso()}
        if extra:
            rec.update(extra)

        def _lam(data):
            if (data.get(khoa) or {}).get("token") == token:
                return False
            data[khoa] = rec
            return True

        doi = self._sua(_lam)
        if doi:
            log.info("token store: lưu token theo TÊN %r (nên dùng khoá id)", khoa)
        return doi

    # ---------- đọc (KHÔNG BAO GIỜ XOÁ) ----------

    def get(self, account_name):
        with self._lock:
            self._data = self._doc_dia()
            return (self._data.get(account_name) or {}).get("token")

    def get_record(self, account_name):
        with self._lock:
            self._data = self._doc_dia()
            return self._data.get(account_name)

    def find_for_account(self, account):
        """Tìm token cho một account, chịu được kho khoá không nhất quán.

        Kho tích tụ nhiều thế hệ khoá cho cùng một người: `Account 01`,
        `Account01`, và cả tên đăng nhập `nicktestxabai1`. `get()` tra khoá
        chính xác nên sẽ hụt.

        Thứ tự tin cậy: khoá `id` -> bản ghi có `account_id` khớp -> khoá là
        bí danh của tên/username/character_name. Trong mỗi mức chọn bản ghi
        MỚI NHẤT, vì token cũ đã hết hạn (server trả mã 404).

        CHỈ ĐỌC. Không chép, không xoá — xem bất biến 3 ở đầu file.
        Trả `(token, khoá_đã_dùng)`; `(None, None)` nếu không có.
        """
        if not isinstance(account, dict):
            return None, None

        with self._lock:
            self._data = self._doc_dia()
            data = self._data

            acc_id = str(account.get("id") or "").strip()
            if acc_id:
                rec = data.get(acc_id)
                if isinstance(rec, dict) and rec.get("token"):
                    return rec["token"], acc_id

            def _moi_nhat(cap):
                cap = [x for x in cap if (x[1] or {}).get("token")]
                if not cap:
                    return None, None
                cap.sort(key=lambda x: (x[1].get("saved_at") or ""), reverse=True)
                return cap[0][1]["token"], cap[0][0]

            if acc_id:
                t, k = _moi_nhat([(k, r) for k, r in data.items()
                                  if isinstance(r, dict)
                                  and str(r.get("account_id") or "").strip() == acc_id])
                if t:
                    return t, k

            ten = self._dinh_danh(account)
            if not ten:
                return None, None
            return _moi_nhat([(k, r) for k, r in data.items()
                              if isinstance(r, dict) and chuan(k) in ten])

    # ---------- xoá ----------

    def clear(self, account_name=None):
        def _lam(data):
            if account_name:
                return data.pop(account_name, None) is not None
            if not data:
                return False
            data.clear()
            return True

        return self._sua(_lam)

    def clear_for_account(self, account) -> int:
        """Xoá MỌI khoá thuộc về account này (dùng khi xoá profile).

        Token là thông tin đăng nhập; bỏ nó lại sau khi người dùng đã xoá
        profile là để credential sống lâu hơn chủ của nó.
        """
        if not isinstance(account, dict):
            return 0
        acc_id = str(account.get("id") or "").strip()
        ten = self._dinh_danh(account)
        so = {"n": 0}

        def _lam(data):
            bo = [k for k, r in data.items()
                  if k == acc_id
                  or (isinstance(r, dict)
                      and str(r.get("account_id") or "").strip() == acc_id and acc_id)
                  or chuan(k) in ten]
            for k in bo:
                data.pop(k, None)
            so["n"] = len(bo)
            return bool(bo)

        self._sua(_lam)
        return so["n"]

    # ---------- di trú ----------

    def migrate(self, accounts, backup_path=None):
        """Gộp mọi khoá bí danh về khoá `id`. CHỈ ĐÂY mới được xoá khoá cũ.

        Luật nhập nhằng: một khoá khớp từ HAI account trở lên thì GIỮ NGUYÊN,
        không gán cho ai — gán bừa là trao token người này cho người kia.

        Trả về bản báo cáo để người gọi hiển thị; không tự ghi log ồn ào.
        """
        bao_cao = {"gop": [], "giu_nhap_nhang": [], "khong_chu": [],
                   "truoc": 0, "sau": 0, "backup": None}

        with self._lock:
            data = self._doc_dia()
            bao_cao["truoc"] = len(data)
            if not data:
                return bao_cao

            hop_le = [a for a in (accounts or [])
                      if isinstance(a, dict) and str(a.get("id") or "").strip()]

            # khoá -> các account khớp
            khop = {}
            for k, r in data.items():
                if not isinstance(r, dict) or not r.get("token"):
                    continue
                kc = chuan(k)
                aid = str(r.get("account_id") or "").strip()
                chu = [a for a in hop_le
                       if kc == chuan(a.get("id"))
                       or (aid and aid == str(a.get("id")).strip())
                       or kc in self._dinh_danh(a)]
                khop[k] = chu

            moi = {}
            theo_account = {}
            for k, chu in khop.items():
                if len(chu) > 1:
                    bao_cao["giu_nhap_nhang"].append(
                        f"{k} khớp {len(chu)} account: "
                        + ", ".join(str(a.get('name')) for a in chu))
                    moi[k] = data[k]
                elif not chu:
                    bao_cao["khong_chu"].append(k)
                    moi[k] = data[k]
                else:
                    theo_account.setdefault(str(chu[0]["id"]), []).append((k, data[k]))

            for aid, cap in theo_account.items():
                cap.sort(key=lambda x: (x[1].get("saved_at") or ""), reverse=True)
                khoa_cu, rec = cap[0]
                acc = next((a for a in hop_le if str(a.get("id")) == aid), {})
                moi[aid] = {
                    **rec,
                    "account_id": aid,
                    "account_name": acc.get("name"),
                    "username": rec.get("username") or acc.get("username"),
                }
                bo = [k for k, _ in cap if k != aid]
                bao_cao["gop"].append({
                    "account": acc.get("name"),
                    "giu": khoa_cu,
                    "bo": bo,
                    "khoa_moi": aid,
                })

            bao_cao["sau"] = len(moi)
            if moi == data:
                return bao_cao              # không có gì để gộp -> không sao lưu

            # Sao lưu CHỈ KHI sắp thay đổi thật. Ghi .bak mỗi lần khởi động là
            # rải bản sao credential ra đĩa; và không có bản lùi thì KHÔNG được
            # đụng vào dữ liệu.
            if backup_path:
                try:
                    Path(backup_path).write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
                    bao_cao["backup"] = str(backup_path)
                except Exception as e:
                    log.warning("token store: không sao lưu được: %s", e)
                    bao_cao["sau"] = bao_cao["truoc"]
                    bao_cao["gop"] = []
                    return bao_cao

            self._data = moi
            self._ghi_dia(moi)
            return bao_cao

    # ---------- tiện ích ----------

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

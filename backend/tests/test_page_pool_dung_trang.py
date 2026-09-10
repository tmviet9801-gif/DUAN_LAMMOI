"""PagePool.get_or_open phải trả về trang của ĐÚNG account, không phải ids[0].

Lỗi thật, bắt được khi chạy gom bàn 2 account:
    "Không đặt được vai trò anchor/sub trên mọi trang: Account 01: cần anchor, thực tế sub"

Nguyên nhân: `BrowserManager.open_sessions` trả về MỌI session đang có, không
chỉ cái vừa mở. `get_or_open` lấy `ids[0]` — session MỞ SỚM NHẤT — nên khi mở
Account 02 nó nhận về trang của Account 01. Hai tên profile trỏ vào cùng một
trang; lệnh gán `sub` cho Account 02 ghi đè `anchor` trên Account 01.

Dấu vết trong log cũ: "page_pool opened session tab_…_0 for Account 02" cùng
session id với Account 01.
"""
import asyncio
import sys
from pathlib import Path

BE = Path(__file__).parents[1]
if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))

from services.page_pool import PagePool  # noqa: E402


class _Session:
    def __init__(self, sid, account, page):
        self.session_id = sid
        self.account = account
        self.page = page


class _ManagerGia:
    """Mô phỏng đúng hành vi thật: open_sessions trả về MỌI session id."""

    def __init__(self):
        self.sessions = {}
        self._dem = 0

    async def open_sessions(self, count=None, account_ids=None, accounts=None):
        for acc in accounts or []:
            self._dem += 1
            sid = f"tab_{1000 + self._dem}"
            self.sessions[sid] = _Session(sid, acc, page=f"page-of-{acc['name']}")
        return [s.session_id for s in self.sessions.values()]   # <- TẤT CẢ


ACC1 = {"id": "id-01", "name": "Account 01"}
ACC2 = {"id": "id-02", "name": "Account 02"}


def test_mo_account_thu_hai_khong_nhan_trang_account_thu_nhat():
    pool = PagePool(_ManagerGia())
    p1 = asyncio.run(pool.get_or_open(ACC1))
    p2 = asyncio.run(pool.get_or_open(ACC2))
    assert p1 == "page-of-Account 01"
    assert p2 == "page-of-Account 02", f"Account 02 nhận nhầm trang: {p2}"
    assert p1 is not p2


def test_moi_ten_tro_vao_mot_trang_rieng():
    """Đúng điều kiện matching.py cần: gán vai trò lên trang này không được
    ảnh hưởng trang kia."""
    pool = PagePool(_ManagerGia())
    trang = {a["name"]: asyncio.run(pool.get_or_open(a)) for a in (ACC1, ACC2)}
    assert len(set(trang.values())) == 2


def test_da_mo_roi_thi_tra_lai_dung_session_cu():
    m = _ManagerGia()
    pool = PagePool(m)
    p_a = asyncio.run(pool.get_or_open(ACC1))
    p_b = asyncio.run(pool.get_or_open(ACC1))
    assert p_a == p_b
    assert len(m.sessions) == 1, "mở trùng session cho cùng một account"


def test_khong_con_lay_ids0():
    src = (BE / "services" / "page_pool.py").read_text(encoding="utf-8")
    code = "\n".join(d for d in src.splitlines() if not d.strip().startswith("#"))
    i = code.index("async def get_or_open")
    than = code[i:i + 1500]
    assert "ids[0]" not in than, "vẫn lấy session đầu tiên thay vì của đúng account"
    assert than.count("_find_session(account)") >= 2, \
        "sau khi mở phải TRA LẠI theo account"

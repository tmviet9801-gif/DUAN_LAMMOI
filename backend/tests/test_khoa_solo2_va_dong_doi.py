"""Ba việc: ghim danh sách đồng đội, cổng đủ ghế, và khoá bàn Solo 2 người.

Cả ba đều từng hỏng theo cách khó thấy, nên mỗi test dưới đây khoá lại đúng
điểm hỏng chứ không khoá hình dạng mã.
"""
import re
import sys
from pathlib import Path

import pytest

BE = Path(__file__).parents[1]
APP = BE.parent / "app" / "renderer"
AFC = BE / "controllers" / "auto_flow_controller"

if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))

from controllers.auto_flow_controller.constants import (  # noqa: E402
    FIXED_TABLE_RIDS,
    SO_CHO_CHO_PHEP,
    kiem_so_cho,
)
from services.extension_hub import ExtensionHubManager  # noqa: E402


def _code(p: Path) -> str:
    """Chỉ lấy dòng CODE, bỏ cả khối `/** */` và `<!-- -->`."""
    src = p.read_text(encoding="utf-8")
    if p.suffix in (".js", ".html"):
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    mo = "#" if p.suffix == ".py" else "//"
    return "\n".join(d for d in src.splitlines() if not d.strip().startswith(mo))


# ===================== A. Ghim danh sách đồng đội =====================

def test_ghim_theo_tung_profile_khong_gan_de():
    """Các cặp chạy SONG SONG qua `asyncio.gather` và dùng chung `request`.
    Ghim kiểu gán đè một tập chung sẽ xoá ghim của cặp kia."""
    h = ExtensionHubManager()
    h.pin_partners("Account 01", ["a", "b"])
    h.pin_partners("Account 03", ["c"])
    assert h.pinned_partners("Account 01") == ["a", "b"]
    assert h.pinned_partners("Account 03") == ["c"]


def test_go_ghim_chi_go_dung_cap_cua_minh():
    """`finally` của cặp xong trước không được tháo ghim của cặp đang chạy."""
    h = ExtensionHubManager()
    h.pin_partners("Account 01", ["a"])
    h.pin_partners("Account 03", ["c"])
    h.unpin_partners(["Account 01", "Account 02"])
    assert h.pinned_partners("Account 01") is None
    assert h.pinned_partners("Account 03") == ["c"], "đã tháo nhầm ghim cặp khác"


def test_ten_profile_khong_phan_biet_hoa_thuong():
    h = ExtensionHubManager()
    h.pin_partners("Account 01", ["a"])
    assert h.pinned_partners("account 01") == ["a"]
    assert h.pinned_partners("  ACCOUNT 01 ") == ["a"]


def test_ghim_la_ban_sao_khong_dung_chung_tham_chieu():
    h = ExtensionHubManager()
    goc = ["a"]
    h.pin_partners("P", goc)
    goc.append("b")
    assert h.pinned_partners("P") == ["a"], "sửa danh sách gốc làm đổi bản ghim"


def test_hub_gui_lai_ban_ghim_thay_vi_bo_qua():
    """Bỏ qua hẳn thì trang mất sạch danh sách sau khi service worker MV3 bị
    kill rồi đăng ký lại — thay danh sách quá rộng bằng danh sách RỖNG."""
    code = _code(BE / "services" / "extension_hub.py")
    khoi = code[code.index("async def broadcast_partners"):][:3000]
    assert "_pinned_partners.get(name_low)" in khoi
    i = khoi.index("_pinned_partners.get(name_low)")
    sau = khoi[i:i + 700]
    assert "SYNC_PARTNERS" in sau, "phải GỬI LẠI bản ghim, không chỉ `continue`"
    assert "continue" in sau


def test_matching_ghim_ngay_dau_luot_va_go_o_finally():
    code = _code(AFC / "matching.py")
    assert "pin_partners(" in code
    assert "unpin_partners(profiles_input)" in code, "phải gỡ theo tên của lượt này"
    assert "set_scoped_profiles" not in code, "cách gán đè cũ đã bỏ"
    i = code.index("finally:")
    assert "unpin_partners" in code[i:], "gỡ ghim phải nằm trong finally"


# ===================== B. Cổng đủ số ghế =====================

def _than_trigger() -> str:
    code = _code(BE / "extension" / "content_main.js")
    i = code.index("function triggerVerifiedMatchReadyAndStart")
    return code[i:code.index("setTimeout(executeHandshakeAction", i)]


def test_cong_ghe_nam_trong_executeHandshakeAction():
    """Thoát sớm ở ĐẦU hàm sẽ bỏ qua cả `__is_matched_locked`, việc huỷ
    `__hunt_wait_timer`/`__hunt_retry_timer`, gói AUTOTOOL_MATCH_SUCCESS và nhịp
    nhắc lại — bàn coi như chưa khớp và không còn gì đánh thức nó khi người thứ
    ba, thứ tư ngồi xuống."""
    than = _than_trigger()
    assert "soGheCan" in than
    assert than.index("G.__is_matched_locked = true") < than.index("soGheCan"), \
        "cổng ghế phải nằm SAU khối khoá trạng thái"
    assert than.index("AUTOTOOL_MATCH_SUCCESS") < than.index("soGheCan"), \
        "cổng ghế phải nằm SAU gói báo khớp bàn"
    i = than.index("const executeHandshakeAction")
    assert than.index("soGheCan") > i, "cổng phải nằm TRONG executeHandshakeAction"


def test_cong_ghe_chan_truoc_ca_hai_vai():
    than = _than_trigger()
    i = than.index("soGheCan")
    sau = than[i:]
    assert sau.index("return;") < sau.index("isAnchorMatchProfile()"), \
        "phải chặn trước khi phân vai, không thì nick chính vẫn Bắt đầu"


def test_cong_ghe_doc_o_slot_nguoi_dung_chon():
    than = _than_trigger()
    assert "G.__target_hunt_mu" in than
    assert "|| 2" in than[than.index("soGheCan"):][:120], "thiếu giá trị lùi an toàn"


def test_van_giu_goi_cmd5_trong_exec_ready():
    """Đo trên bản ghi WS thật: gửi cmd 5 khi đồng đội chưa bỏ phiếu thì nhận
    "Không đủ người chơi để bắt đầu"; chỉ sau khi nhận phiếu của đồng đội rồi
    gửi lại mới có cmd 250 chia bài. Trong 9348 khung có 116 gói cmd 363 và
    TOÀN BỘ là `aRd:"false"` — không một gói `aRd:"true"` nào, tức cmd 363 KHÔNG
    thay thế được cmd 5. Bỏ gói này khỏi nick phụ là bàn không bao giờ vào ván.
    """
    code = _code(BE / "extension" / "content_main.js")
    i = code.index("G.__autotool_exec_ready = function")
    than = code[i:i + 1600]
    assert '{"cmd":5}' in than, "đã bỏ mất phiếu Bắt đầu của nick phụ"


# ===================== C. Khoá bàn Solo 2 =====================

def test_chi_mo_ban_solo_2():
    assert SO_CHO_CHO_PHEP == (2,)
    assert kiem_so_cho(2) == 2
    for xau in (4, 3, 0, -2, "4", None, "abc", 2.5):
        with pytest.raises(ValueError):
            kiem_so_cho(xau)


def test_moi_cua_vao_deu_qua_cong():
    """Ba nơi đọc `body["mu"]`; sót một nơi là thủng."""
    for f in ("matching.py", "routes_basic.py"):
        code = _code(AFC / f)
        so_doc = code.count('body.get("mu"')
        so_cong = code.count("kiem_so_cho(")
        assert so_cong >= so_doc, f"{f}: {so_doc} chỗ đọc mu nhưng chỉ {so_cong} cổng"


def test_luong_gom_ban_thu_hai_cung_bi_khoa():
    """`/api/autoplay/start` là một luồng gom bàn HOÀN CHỈNH THỨ HAI, không nhận
    tham số `mu` nên cổng ở controller không chạm tới được: nó chọn bàn theo số
    người đang ngồi và có thể rơi thẳng vào bàn 4 chỗ."""
    code = _code(BE / "game_sim" / "adapters" / "hitclub.py")
    assert "SO_CHO_CHO_PHEP" in code
    i = code.index('empty = [r for r in rooms.values() if r["uC"] == 0]')
    assert "SO_CHO_CHO_PHEP" in code[:i], "phải lọc TRƯỚC khi chọn bàn"


def test_bang_rid_van_giu_du_ca_hai_cot():
    """Mở lại bàn 4 người phải rẻ — không phải dựng lại bảng."""
    assert FIXED_TABLE_RIDS.get("100_4") == 1
    assert FIXED_TABLE_RIDS.get("100_2") == 2
    assert len(FIXED_TABLE_RIDS) == 28


def test_mo_lai_ban_4_chi_can_doi_mot_hang_so():
    src = _code(AFC / "constants.py")
    assert "SO_CHO_CHO_PHEP = (2,)" in src
    for f in ("matching.py", "routes_basic.py"):
        assert "kiem_so_cho(" in _code(AFC / f), f"{f}: phải dùng hằng số chung"


def test_giao_dien_khoa_o_cho_ve_2():
    """Không ẩn ô: ẩn thì người dùng không biết đang chạy loại bàn nào."""
    html = (APP / "index.html").read_text(encoding="utf-8")
    khoi = html.split('id="gcSlotCount"', 1)[1][:300]
    assert 'value="2"' in khoi and 'min="2"' in khoi and 'max="2"' in khoi
    assert "readonly" in khoi


def test_giao_dien_van_gui_mu_len_backend():
    """Khoá ô nhưng vẫn phải gửi `mu` — bỏ đi là backend nhận mặc định ngầm."""
    code = _code(APP / "js" / "autoplay.js")
    assert "gcSlotCount" in code
    assert "mu: targetMu" in code

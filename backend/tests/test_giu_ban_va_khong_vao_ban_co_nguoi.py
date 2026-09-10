"""Chế độ GIỮ BÀN sau ván xả — và vì sao KHÔNG có cổng "bàn có người thì chờ".

GIỮ BÀN. Sau khi phụ out, chính ở lại bàn với cổng kích hoạt MỞ và auto-xả
BẬT: khách lạ vào và Sẵn sàng thì tự Bắt đầu, bộ xả hiện có tự đánh. Không
đổi một dòng nào ở luật chọn nước; chỉ tắt các lớp gác "thấy khách lạ ->
rời bàn" vốn dành cho lúc đang gom đồng đội.

KHÔNG CHỜ THEO uC. Từng thử (10/09/2026) hỏi `uC` của rid #2 qua cmd 300 rồi
đứng ở sảnh khi uC >= 1, để khỏi nhảy vào bàn có khách ngồi sẵn. Bản bắt WS
cho thấy `uC` của "DemLa#1" là 10-11: đó là số người CẢ PHÒNG, server tự xếp
ghế vào bàn con ("Chống Vây"). Cổng ấy luôn đóng -> Account chính đứng ở
sảnh mãi, không vào được bàn nào. Test dưới chốt: không được đưa lại.
"""
import ast
import sys
from pathlib import Path

BE = Path(__file__).parents[1]
if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))

from controllers.auto_flow_controller import kich_hoat as KH  # noqa: E402

AF = BE / "controllers" / "auto_flow_controller"
MATCHING = AF / "matching.py"
LOBBY = AF / "lobby.py"
EXT = BE / "extension" / "content_main.js"


def _code_py(p: Path) -> str:
    src = p.read_text(encoding="utf-8")
    cay = ast.parse(src)
    bo = set()
    for node in ast.walk(cay):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and ast.get_docstring(node, clean=False) is not None:
                s0 = node.body[0]
                bo.update(range(s0.lineno, (s0.end_lineno or s0.lineno) + 1))
    return "\n".join(
        d for i, d in enumerate(src.splitlines(), 1)
        if i not in bo and not d.strip().startswith("#"))


def _code_js(p: Path) -> str:
    dong = []
    for d in p.read_text(encoding="utf-8").splitlines():
        s = d.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        dong.append(d)
    return "\n".join(dong)


# ===================== 1. Không có cổng uC =====================

def test_khong_dung_uC_lam_cong_vao_ban():
    code = _code_py(MATCHING)
    assert "so_nguoi_trong_ban" not in code
    assert "__autotool_so_nguoi_ban" not in code
    assert not (AF / "ban_trong.py").exists(), "ban_trong.py đã gỡ — uC là số người cả phòng"
    src = _code_js(EXT)
    assert "__ban_theo_rid" not in src


def test_chinh_van_join_ngay_moi_luot_do():
    """Đường dò của chính: không có bước nào đứng chờ trước lệnh join."""
    code = _code_py(MATCHING)
    i = code.index('log.info("find-and-match: [%s] Account 1 (%s) tìm bàn trống')
    j = code.index("window.__autotool_leave_then_join(", i)
    assert "await asyncio.sleep(2.0)" not in code[i:j]


# ===================== 2. Chế độ GIỮ BÀN =====================

def test_js_giu_ban_mo_cong_bat_xa_xoa_dong_doi():
    js = KH.js_giu_ban(True, True, 100, 2)
    for dong in ("window.__AUTOTOOL_ENGAGED = true;",
                 "window.__AUTOTOOL_GIU_BAN = true;",
                 "window.__AUTOTOOL_ARMED = true;",
                 "window.__AUTOTOOL_AUTO_HUNT = false;",
                 "window.__AUTOTOOL_AUTO_DISCARD = true;",
                 "window.__auto_start_guest_ss = true;",
                 "window.__autotool_partners = [];",
                 'window.__AUTOTOOL_ROLE = "winner";',
                 "localStorage.removeItem('AUTOTOOL_STOPPED')"):
        assert dong in js, dong
    assert "__stranger_leave_timer" in js, "phải huỷ lệnh rời đang hẹn từ lúc gom"


def test_js_giu_ban_ton_trong_tuy_chon():
    js = KH.js_giu_ban(False, False, 500, 2)
    assert "window.__AUTOTOOL_AUTO_DISCARD = false;" in js
    assert "window.__auto_start_guest_ss = false;" in js


def test_kich_hoat_luc_gom_KHONG_giu_ban():
    assert "window.__AUTOTOOL_GIU_BAN = false;" in KH.js_kich_hoat("sub", True, [], 100, 2)


def test_dung_va_dong_luot_deu_tat_giu_ban():
    code = _code_py(LOBBY)
    assert code.count("window.__AUTOTOOL_GIU_BAN = false;") >= 2, \
        "_clear_hunt_state (Dừng) và dong_luot_chay đều phải tắt"


def test_extension_khong_roi_ban_khi_dang_giu():
    src = _code_js(EXT)
    # cmd 200: khách vào bàn
    i = src.index("VÀO BÀN -> Hủy lệnh cho đồng đội & Out bàn ngay")
    truoc = src[i - 700:i]
    assert "else if (G.__AUTOTOOL_GIU_BAN)" in truoc, "cmd 200 chưa gác giữ bàn"
    # cmd 202: bàn có khách lạ / full
    j = src.index("const guestSS = strangers.some(")
    sau = src[j:j + 900]
    assert "G.__AUTOTOOL_GIU_BAN && !isSubProfile" in sau
    assert "G.__autotool_exec_start()" in sau
    k = sau.index("G.__AUTOTOOL_GIU_BAN && !isSubProfile")
    # Nhánh này có thêm đường "mình là khách -> Sẵn sàng" (test_tu_danh.py),
    # nên dài hơn bản đầu; vẫn phải kết bằng return trước nhánh rời bàn.
    assert "return;" in sau[k:k + 1000], "giữ bàn thì phải thoát trước nhánh rời bàn"


def test_extension_cac_lop_gac_dong_doi_nhuong_cho_giu_ban():
    src = _code_js(EXT)
    for ham in ("function dangChoDongDoi()", "function khongDuocBatDauVoiNguoiLa()"):
        i = src.index(ham)
        assert "if (G.__AUTOTOOL_GIU_BAN) return false;" in src[i:i + 300], ham
    i = src.index("function clearRunConfig()")
    assert "G.__AUTOTOOL_GIU_BAN = false;" in src[i:i + 900]


def test_controller_bat_giu_ban_khi_chinh_khong_out():
    code = _code_py(MATCHING)
    i = code.index("Ván xả bài hoàn tất")
    khoi = code[i:i + 5000]
    j = khoi.index("if auto_leave_after:")
    k = khoi.index("js_giu_ban(auto_xa, auto_start_guest_ss", j)
    assert "else:" in khoi[j:k], "giữ bàn phải nằm ở nhánh KHÔNG out"
    assert "await eval_page(anchor_page, js_giu_ban(" in khoi


def test_dong_luot_chay_chua_trang_chinh_khi_giu_ban():
    code = _code_py(MATCHING)
    assert "pages_dong = pages if auto_leave_after else" in code
    assert "t != anchor_name" in code
    assert 'dong_luot_chay(pages_dong, "ván đã kết thúc"' in code

"""Hai việc sau ván xả (10/09/2026):

1. KHÔNG NHẢY VÀO BÀN ĐANG CÓ KHÁCH. Bàn $100 Solo chỉ có rid #2. Log
   16:04:27: chính dò bàn #2 đúng lúc khách `chiiritroi6879` ngồi sẵn, server
   chia bài ngay trong giây đó, lệnh rời không kịp -> chính bị kéo vào một ván
   tiền thật với khách. Server đẩy `uC` từng bàn qua cmd 305 -> hỏi trước,
   bàn có người thì đứng ở sảnh chờ.

2. GIỮ BÀN. Sau khi phụ out, chính ở lại bàn với cổng kích hoạt MỞ và auto-xả
   BẬT: khách lạ vào và Sẵn sàng thì tự Bắt đầu, bộ xả hiện có tự đánh. Không
   đổi một dòng nào ở luật chọn nước; chỉ tắt các lớp gác "thấy khách lạ ->
   rời bàn" vốn dành cho lúc đang gom đồng đội.
"""
import ast
import asyncio
import sys
from pathlib import Path

BE = Path(__file__).parents[1]
if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))

from controllers.auto_flow_controller import ban_trong as BT  # noqa: E402
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


# ===================== 1. Hỏi số người trước khi vào =====================

def test_doc_so_nguoi_khong_doan():
    assert BT.doc_so_nguoi({"uC": 1}) == 1
    assert BT.doc_so_nguoi({"uC": "0"}) == 0
    assert BT.doc_so_nguoi({"uC": None}) is None
    assert BT.doc_so_nguoi(None) is None
    assert BT.doc_so_nguoi({}) is None


def test_js_hoi_ban_dung_cache_moi_va_hoi_server_khi_cu():
    js = BT.JS_SO_NGUOI_BAN
    assert "window.__ban_theo_rid" in js
    assert "simms.send(reqFrame)" in js, "cache cũ thì phải hỏi server"
    assert "(b.ts || 0) >= t0" in js, "chỉ nhận khung MỚI sau lúc hỏi, không nhận số cũ"
    assert str(BT.TUOI_MOI_MS) in js
    assert BT.TUOI_MOI_MS <= 1500, "khách vừa ngồi là uC đổi; tin số cũ 2-3s là lại đua"


def test_so_nguoi_trong_ban_qua_trang():
    async def _eval(page, js, arg=None):
        # eval_page chỉ nhận MỘT tham số -> phải gói thành object
        assert arg == {"rid": 2, "req": "[6,x]", "cho": 700}
        assert "a.rid, a.req, a.cho" in js
        return {"uC": 1, "nguon": "hoi"}
    assert asyncio.run(BT.so_nguoi_trong_ban("p", 2, "[6,x]", eval_page=_eval)) == 1


def test_khong_doc_duoc_thi_None_khong_no():
    async def _eval(page, js, arg=None):
        raise RuntimeError("closed")
    assert asyncio.run(BT.so_nguoi_trong_ban("p", 2, "[6,x]", eval_page=_eval)) is None
    assert asyncio.run(BT.so_nguoi_trong_ban("p", None, "[6,x]")) is None


def test_extension_ghi_uC_theo_rid_tu_cmd_305_va_300():
    src = _code_js(EXT)
    assert "function ghiBanTheoRid(" in src
    assert "p.cmd === 305 && p.ri" in src
    assert "p.cmd === 300 && Array.isArray(p.rs)" in src
    assert "G.__autotool_ban_theo_rid = function" in src


def test_controller_hoi_truoc_roi_moi_join_va_cho_khi_co_nguoi():
    code = _code_py(MATCHING)
    i = code.index("await so_nguoi_trong_ban(first_page")
    j = code.index("window.__autotool_leave_then_join(", i)
    assert i < j, "phải hỏi số người TRƯỚC lệnh join của chính"
    khoi = code[i:j]
    assert "so_nguoi >= 1" in khoi
    assert "continue" in khoi, "bàn có người thì bỏ lượt, không vào"
    assert "KHÔNG vào" in khoi


def test_controller_cai_ham_hoi_len_trang():
    code = _code_py(MATCHING)
    assert "window.__autotool_so_nguoi_ban = {JS_SO_NGUOI_BAN}" in code


def test_phu_khong_bi_chan_boi_kiem_so_nguoi():
    """Phụ vào bàn mà chính ĐANG GIỮ (uC=1). Kiểm số người chỉ dành cho lượt dò
    của chính, tuyệt đối không nằm trong đường join của phụ."""
    code = _code_py(MATCHING)
    i = code.index("Gửi lệnh JOIN trực tiếp bàn")
    assert "so_nguoi_trong_ban" not in code[i - 3000:i]


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
    assert "return;" in sau[k:k + 700], "giữ bàn thì phải thoát trước nhánh rời bàn"


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

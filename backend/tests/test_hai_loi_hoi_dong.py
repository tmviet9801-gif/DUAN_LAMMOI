"""Hai lỗi hội đồng tìm ra, cả hai đều làm mất tiền hoặc mất lượt.

LỖI 1 — `_do_leave_room` gửi gói rời GIỮA VÁN.
    `__autotool_exec_leave()` trả `false` khi hoãn vì đang giữa ván, rồi đoạn
    JS dự phòng lại gửi thẳng `[4,"Simms",-1]` — vô hiệu hoá đúng lớp bảo vệ
    vừa áp. Bỏ giữa ván là mất cược và bị phạt bài.

LỖI 2 — Xác minh "cùng bàn" chỉ lấy ĐÚNG MỘT mẫu.
    Vòng `for _ in range(9)` viết ra để thử 9 lần, nhưng nhánh lệch kết bằng
    `break` ngay lần đầu. Thêm nữa, hai danh sách người ngồi đọc bằng hai lời
    gọi `eval_page` nối tiếp, cách nhau ít nhất một vòng CDP, mà mỗi trang cập
    nhật theo khung WS của riêng nó — rất dễ thấy "một bên đã có, bên kia chưa"
    rồi kết luận sai là không cùng bàn và rời bàn oan.
"""
import ast
import re
from pathlib import Path

BE = Path(__file__).parents[1]
LOBBY = BE / "controllers" / "auto_flow_controller" / "lobby.py"
MATCHING = BE / "controllers" / "auto_flow_controller" / "matching.py"


def _code(p: Path) -> str:
    """Chỉ lấy dòng CODE: bỏ `#` và DOCSTRING, nhưng GIỮ chuỗi ba nháy khác.

    Không được cắt mọi chuỗi ba nháy: JS nhúng trong `eval_page(\"\"\"...\"\"\")`
    chính là phần cần kiểm. Bản đầu của test này cắt sạch và đỏ oan 5 chỗ.
    Dùng `ast` để chỉ bỏ đúng docstring.
    """
    src = p.read_text(encoding="utf-8")
    try:
        cay = ast.parse(src)
    except SyntaxError:
        return src
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


def _than_do_leave() -> str:
    code = _code(LOBBY)
    i = code.index("async def _do_leave_room")
    return code[i:i + 3000]


# ===================== LỖI 1: rời bàn giữa ván =====================

def test_khong_gui_goi_roi_khi_dang_giua_van():
    than = _than_do_leave()
    assert "giuaVan" in than, "không còn kiểm đang giữa ván"
    i = than.index("giuaVan")
    j = than.index("__ws_send('[4,\"Simms\",-1]')")
    assert i < j, "phải kiểm giữa ván TRƯỚC khi có đường gửi gói thô"


def test_kiem_giua_van_DOC_LAP_voi_exec_leave():
    """Extension cũ chưa export `exec_leave` thì không có ai chốt, và gói thô đi
    thẳng. Phải tự kiểm bằng state của trang."""
    than = _than_do_leave()
    assert "window.__game_in_progress" in than
    assert "window.__my_cards" in than
    i = than.index("giuaVan")
    assert than.index("__autotool_exec_leave") > i, \
        "phải kiểm giữa ván trước cả khi gọi exec_leave"


def test_exec_leave_tra_false_thi_KHONG_lui_ve_goi_tho():
    """`false` nghĩa là extension đã cố ý hoãn. Lùi về gói thô là phá chốt."""
    than = _than_do_leave()
    assert "ketQua === false" in than
    i = than.index("ketQua === false")
    khoi = than[i:i + 200]
    assert "hoan" in khoi and "return" in khoi


def test_chi_gui_goi_tho_khi_extension_chua_co_helper():
    than = _than_do_leave()
    assert "ketQua !== null" in than
    i = than.index("ketQua !== null")
    j = than.index("__ws_send('[4,\"Simms\",-1]')")
    assert i < j, "gói thô phải nằm sau cửa 'extension chưa export helper'"


def test_hoan_thi_DUNG_va_bao_len_log():
    than = _than_do_leave()
    assert 'ket_qua.get("hoan")' in than
    i = than.index('ket_qua.get("hoan")')
    khoi = than[i:i + 400]
    assert "return" in khoi, "hoãn thì phải dừng, không đi tiếp sang click"
    assert "mất cược" in khoi


def test_van_mo_duong_buoc_roi_khi_that_su_can():
    than = _than_do_leave()
    assert "buoc_ngay=False" in than, "phải có tham số ép rời, mặc định AN TOÀN"
    assert "bool(buoc_ngay)" in than


def test_khong_co_cho_goi_nao_dang_ep_roi():
    """Mặc định an toàn chỉ có nghĩa khi không ai bật ép rời một cách vô ý."""
    code = _code(MATCHING)
    assert "buoc_ngay=True" not in code


# ===================== LỖI 2: xác minh chỉ một mẫu =====================

def _than_xac_minh() -> str:
    code = _code(MATCHING)
    i = code.index("for _ in range(9):")
    return code[i:i + 9000]


def test_doc_hai_danh_sach_trong_cung_mot_nhip():
    than = _than_xac_minh()
    assert "asyncio.gather(" in than, "vẫn đọc nối tiếp -> lệch nhịp"
    i = than.index("asyncio.gather(")
    khoi = than[i:i + 300]
    assert "sub_p" in khoi and "anchor_page" in khoi


def test_chua_thay_nhau_thi_THU_LAI_khong_bo_cuoc():
    than = _than_xac_minh()
    i = than.index("has_anchor and has_sub")
    sau = than[i:]
    # nhánh else phải kết bằng `continue`, không phải `break`
    assert "continue" in sau, "vẫn bỏ cuộc sau một mẫu"
    j = sau.index("chưa thấy nhau")
    assert "continue" in sau[j:j + 400]


def test_chi_roi_ban_khi_co_khang_dinh_DUONG_ve_nguoi_la():
    """"Chưa thấy" là thiếu dữ liệu, không phải bằng chứng có người lạ."""
    than = _than_xac_minh()
    assert "has_stranger" in than
    i = than.index("co_khach_la")
    khoi = than[i:i + 900]
    assert "_do_leave_room" in khoi
    # và lời gọi rời bàn phải nằm TRONG nhánh có người lạ
    j = than.index("if co_khach_la:")
    k = than.index("_do_leave_room", j)
    assert k - j < 500, "rời bàn không nằm trong nhánh khẳng định dương"


def test_van_giu_dieu_kien_hai_chieu():
    """Kiên trì hơn KHÔNG được nới điều kiện: vẫn phải CẢ HAI cùng thấy nhau."""
    than = _than_xac_minh()
    assert "if has_anchor and has_sub:" in than
    assert "sub_matched = True" in than
    i = than.index("if has_anchor and has_sub:")
    assert than.index("sub_matched = True") > i


def test_khong_dung_dem_so_nguoi_hay_rid_ao():
    """Chống hồi quy về cách so trùng rid hoặc đếm >= 2 người."""
    than = _than_xac_minh()
    assert "len(sub_pls) >= 2" not in than
    assert "sub_rid ==" not in than

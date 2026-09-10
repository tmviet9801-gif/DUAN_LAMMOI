"""Phụ phải TỰ ĐÁNH khi tới lượt và TỰ OUT sau ván — hai triệu chứng, một cổng.

Lỗi thật (gom bàn 2 account, 10/09/2026): vào chung bàn, chia bài xong,
Account 01 (chính) tự đánh còn Account 02 (phụ) không đánh cũng không bỏ,
mỗi nước cách nhau đúng ~21 giây (server tự bỏ lượt hộ). Hết ván phụ không
rời bàn, khách ngoài không vào được.

Cả hai đều do `isAutoEngaged()` trả false trên trang phụ: khối cấu hình
anchor xoá cờ Dừng và đặt ARMED, khối cấu hình phụ thì không; bước đọc lại
chỉ kiểm vai trò. Thêm vào đó controller chỉ theo dõi ván 45 giây rồi bỏ đi,
nên nhánh "phụ out sau ván" không bao giờ tới lượt chạy.
"""
import asyncio
import ast
import sys
from pathlib import Path

BE = Path(__file__).parents[1]
if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))

from controllers.auto_flow_controller import kich_hoat as KH  # noqa: E402

AF = BE / "controllers" / "auto_flow_controller"
MATCHING = AF / "matching.py"
EXT = BE / "extension"


def _code_py(p: Path) -> str:
    """Bỏ `#` và docstring, GIỮ chuỗi ba nháy khác (JS nhúng là phần cần kiểm)."""
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


# ===================== 1. Luật "trang đã kích hoạt chưa" =====================

def _ok(role="sub", auto_xa=True):
    return {"role": role, "co_dung": False, "engaged": True, "auto_xa": auto_xa}


def test_trang_dung_thi_khong_co_ly_do():
    assert KH.ly_do_chua_kich_hoat(_ok(), "sub", True) is None
    assert KH.ly_do_chua_kich_hoat(_ok("anchor", False), "anchor", False) is None


def test_con_co_dung_la_chua_kich_hoat():
    st = _ok()
    st["co_dung"] = True
    st["engaged"] = False
    assert "AUTOTOOL_STOPPED" in KH.ly_do_chua_kich_hoat(st, "sub", True)


def test_mat_engaged_la_chua_kich_hoat():
    st = _ok()
    st["engaged"] = False
    assert "cổng kích hoạt đóng" in KH.ly_do_chua_kich_hoat(st, "sub", True)


def test_auto_xa_lech_la_chua_kich_hoat():
    assert "auto-xả" in KH.ly_do_chua_kich_hoat(_ok(auto_xa=False), "sub", True)
    assert "auto-xả" in KH.ly_do_chua_kich_hoat(_ok(auto_xa=True), "sub", False)


def test_vai_tro_sai_bao_dung_kieu_cu():
    """Giữ đúng câu "cần X, thực tế Y" — người dùng đã quen đọc câu này."""
    assert KH.ly_do_chua_kich_hoat(_ok("sub"), "anchor", True) == "cần anchor, thực tế sub"


def test_khong_doc_duoc_trang():
    assert KH.ly_do_chua_kich_hoat(None, "sub", True)


# ===================== 2. JS đặt cấu hình — cả hai vai trò cùng một khuôn =====================

def test_js_phu_xoa_co_dung_va_mo_cong():
    js = KH.js_kich_hoat("sub", True, ["Account 01"], 100, 2)
    assert "localStorage.removeItem('AUTOTOOL_STOPPED')" in js
    assert "window.__AUTOTOOL_ENGAGED = true;" in js
    assert "window.__AUTOTOOL_MATCH_ROLE = \"sub\";" in js
    assert "window.__AUTOTOOL_ROLE = \"dump\";" in js
    assert "window.__AUTOTOOL_AUTO_DISCARD = true;" in js
    assert "window.__AUTOTOOL_ARMED = false;" in js
    assert "window.__is_hunt_initiator = false;" in js
    assert 'window.__AUTOTOOL_PARTNER_PROFILES = ["Account 01"];' in js


def test_js_anchor_cung_khuon_nhung_armed():
    js = KH.js_kich_hoat("anchor", False, ["Account 02"], 500, 2)
    assert "localStorage.removeItem('AUTOTOOL_STOPPED')" in js
    assert "window.__AUTOTOOL_ENGAGED = true;" in js
    assert "window.__AUTOTOOL_MATCH_ROLE = \"anchor\";" in js
    assert "window.__AUTOTOOL_ROLE = \"winner\";" in js
    assert "window.__AUTOTOOL_AUTO_DISCARD = false;" in js
    assert "window.__AUTOTOOL_ARMED = true;" in js
    assert "window.__target_hunt_bet = 500;" in js
    assert "window.__target_hunt_mu = 2;" in js


def test_js_khong_bao_gio_bat_tu_san():
    """Backend-driven: không có trang nào được tự săn/join."""
    for vt in ("anchor", "sub"):
        assert "window.__AUTOTOOL_AUTO_HUNT = false;" in KH.js_kich_hoat(vt, True, [], 100, 2)


def test_js_doc_trang_thai_doc_dung_thu_isAutoEngaged_doc():
    js = KH.JS_DOC_TRANG_THAI
    assert "localStorage.getItem('AUTOTOOL_STOPPED')" in js
    for co in ("__AUTOTOOL_ENGAGED", "__AUTOTOOL_ARMED", "__AUTOTOOL_AUTO_HUNT",
               "__AUTOTOOL_AUTO_DISCARD", "__AUTOTOOL_MATCH_ROLE"):
        assert co in js


# ===================== 3. bao_dam_kich_hoat: đặt -> đọc lại -> bật lại =====================

class _TrangGia:
    """Mô phỏng trang: đọc trả `trang_thai`; JS đặt cấu hình thì sửa trang thái
    theo `sua_duoc` (False = trang chết, đặt gì cũng không ăn)."""

    def __init__(self, ten, trang_thai, sua_duoc=True):
        self.ten = ten
        self.trang_thai = trang_thai
        self.sua_duoc = sua_duoc
        self.so_lan_dat = 0


async def _eval_gia(trang, js, *args):
    if js == KH.JS_DOC_TRANG_THAI:
        return dict(trang.trang_thai)
    assert "__AUTOTOOL_ENGAGED = true" in js, "chỉ có hai loại JS: đọc và đặt"
    trang.so_lan_dat += 1
    if trang.sua_duoc:
        vai_tro = "anchor" if '__AUTOTOOL_MATCH_ROLE = "anchor"' in js else "sub"
        trang.trang_thai = {"role": vai_tro, "co_dung": False, "engaged": True,
                            "auto_xa": "__AUTOTOOL_AUTO_DISCARD = true" in js}
    return None


def _chay(pages, auto_xa=True):
    return asyncio.run(KH.bao_dam_kich_hoat(
        pages, "Account 01", auto_xa, 100, 2, eval_page=_eval_gia))


def test_phu_con_co_dung_thi_duoc_bat_lai_va_bao_ten():
    """Đúng ca lỗi thật: anchor ổn, phụ còn cờ Dừng."""
    a = _TrangGia("Account 01", _ok("anchor"))
    b = _TrangGia("Account 02", {"role": "sub", "co_dung": True, "engaged": False, "auto_xa": True})
    loi, bat_lai = _chay({"Account 01": a, "Account 02": b})
    assert loi == []
    assert bat_lai == ["Account 02"], "phải nêu ĐÚNG trang đã phải bật lại"
    assert a.so_lan_dat == 0, "trang đang đúng thì không đặt lại"
    assert b.so_lan_dat == 1
    assert b.trang_thai["engaged"] and not b.trang_thai["co_dung"]


def test_phu_mat_auto_xa_cung_duoc_bat_lai():
    b = _TrangGia("Account 02", _ok("sub", auto_xa=False))
    loi, bat_lai = _chay({"Account 01": _TrangGia("Account 01", _ok("anchor")), "Account 02": b})
    assert loi == [] and bat_lai == ["Account 02"]
    assert b.trang_thai["auto_xa"] is True


def test_trang_chet_thi_bao_loi_co_ten_va_ly_do():
    b = _TrangGia("Account 02", {"role": None, "co_dung": False, "engaged": False, "auto_xa": False},
                  sua_duoc=False)
    loi, bat_lai = _chay({"Account 01": _TrangGia("Account 01", _ok("anchor")), "Account 02": b})
    assert bat_lai == []
    assert len(loi) == 1 and loi[0].startswith("Account 02: ")
    assert "cần sub, thực tế None" in loi[0]
    assert b.so_lan_dat == 2, "thử đặt lại đủ số lần rồi mới bỏ cuộc"


def test_moi_trang_dung_thi_khong_dong_gi():
    pages = {"Account 01": _TrangGia("Account 01", _ok("anchor")),
             "Account 02": _TrangGia("Account 02", _ok("sub"))}
    assert _chay(pages) == ([], [])
    assert all(t.so_lan_dat == 0 for t in pages.values())


def test_doc_trang_loi_thi_khong_no_ma_bao():
    async def _eval_no(trang, js, *args):
        raise RuntimeError("Target page closed")
    loi, bat_lai = asyncio.run(KH.bao_dam_kich_hoat(
        {"Account 01": object(), "Account 02": object()}, "Account 01", True, 100, 2,
        eval_page=_eval_no))
    assert len(loi) == 2 and all("Target page closed" in x for x in loi)


# ===================== 4. Controller dùng nó ở ĐỦ ba chỗ =====================

def test_controller_goi_bao_dam_o_ba_thoi_diem():
    code = _code_py(MATCHING)
    assert code.count("await bao_dam_kich_hoat(") >= 3, \
        "sau khi gán vai trò, trước Sẵn sàng, và trong lúc theo dõi ván"


def test_truoc_san_sang_phai_khang_dinh_lai():
    code = _code_py(MATCHING)
    i = code.index("await bao_dam_kich_hoat(", code.index("if not auto_xa:"))
    j = code.index('send_command(sub_name, "READY")')
    assert i < j, "khẳng định lại kích hoạt phải nằm TRƯỚC vòng Sẵn sàng"
    khoi = code[i:j]
    assert "_do_leave_room" in khoi and "dong_luot_chay" in khoi, \
        "không bật được thì hủy bàn, không cho ván chạy với cổng đóng"


def test_theo_doi_van_theo_dien_bien_khong_45s():
    code = _code_py(MATCHING)
    i = code.index("game_completed = False")
    khoi = code[i:i + 3500]
    assert "45.0" not in khoi, "vẫn cắt cứng 45 giây"
    assert "HAN_IM_LANG" in khoi and "HAN_CUNG" in khoi
    assert "__cards_played" in khoi, "phải nhìn diễn biến (lá đã ra) để gia hạn"
    assert "await bao_dam_kich_hoat(" in khoi, "phải tự chữa cổng giữa ván"


def test_het_han_van_ra_lenh_phu_roi():
    code = _code_py(MATCHING)
    i = code.index("Hết thời gian theo dõi ván")
    khoi = code[i:i + 1200]
    assert "_do_leave_room" in khoi
    assert "for p_name in other_profiles" in khoi
    assert "_ensure_in_tldl_lobby" not in khoi, \
        "có thể còn giữa ván — không được click điều hướng"


# ===================== 5. Extension nói rõ vì sao bỏ lượt =====================

def test_extension_bao_ly_do_khi_toi_luot_ma_cong_dong():
    src = _code_js(EXT / "content_main.js")
    i = src.index("function handleAutoTurn()")
    than = src[i:i + 900]
    assert "baoBoLuotViCongDong()" in than
    assert "if (!isAutoEngaged()) return;" in than, "cổng vẫn phải giữ nguyên"
    ham = src[src.index("function baoBoLuotViCongDong()"):]
    ham = ham[:ham.index("function handleAutoTurn()")]
    assert 'type: "AUTOTOOL_TURN_SKIPPED"' in ham
    for ly_do in ("AUTOTOOL_STOPPED=1", "__AUTOTOOL_ENGAGED/ARMED", "__AUTOTOOL_AUTO_DISCARD=false"):
        assert ly_do in ham, f"thiếu lý do {ly_do}"


def test_ly_do_di_toi_duoc_log_backend():
    content = _code_js(EXT / "content.js")
    background = _code_js(EXT / "background.js")
    hub = _code_py(BE / "services" / "extension_hub.py")
    assert 'ev.data.type === "AUTOTOOL_TURN_SKIPPED"' in content
    assert 'type: "TURN_SKIPPED"' in content
    assert 'message.type === "TURN_SKIPPED"' in background, "background chưa cho qua"
    assert '"TURN_SKIPPED"' in hub
    i = hub.index('"TURN_SKIPPED"')
    assert "log.warning" in hub[i:i + 500]

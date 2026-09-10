"""Chờ đủ profile vào sảnh chọn bàn — LẶP LẠI, không bỏ cuộc sau một vòng.

Bản trước chạy `_prepare_lobby` đúng MỘT vòng (45 giây) rồi trả `ok: False` và
tắt lượt chạy. Thực tế: một profile còn popup quảng cáo hoặc đang tải chậm là cả
lượt chết, người dùng phải bấm chạy lại bằng tay — trong khi chỉ cần thêm một
vòng nữa là xong.

Kèm theo: thông điệp lý do từng báo SAI. Nó kiểm popup TRƯỚC rồi thoát luôn, nên
khi bộ dò popup báo nhầm thì người dùng đọc được "có popup/quảng cáo che màn
hình" cho một profile mà họ đang nhìn thấy rõ là không có popup nào — và lý do
thật (đang đứng ở sảnh chính) bị giấu mất.
"""
import re
from pathlib import Path

BE = Path(__file__).parents[1]
AFC = BE / "controllers" / "auto_flow_controller"
EXT = BE / "extension" / "content_main.js"


def _code(p: Path) -> str:
    """Chỉ lấy dòng CODE, bỏ cả khối `/** */`."""
    src = p.read_text(encoding="utf-8")
    if p.suffix != ".py":
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    mo = "#" if p.suffix == ".py" else "//"
    return "\n".join(d for d in src.splitlines() if not d.strip().startswith(mo))


def _khoi_cho_sanh() -> str:
    code = _code(AFC / "matching.py")
    i = code.index("_prepare_lobby(p_name, p) for p_name, p in pages.items()")
    return code[max(0, i - 700):i + 3000]


# ---------- lặp lại, không bỏ cuộc ----------

def test_khong_con_tra_ve_that_bai_vi_chua_vao_duoc_sanh():
    """Đúng triệu chứng người dùng gặp: log một dòng rồi dừng luôn."""
    khoi = _khoi_cho_sanh()
    assert 'dong_luot_chay(pages, "không vào được sảnh")' not in khoi, \
        "vẫn tắt lượt chạy khi chưa vào được sảnh"
    assert "KHÔNG chạy gom bàn" not in khoi, "vẫn còn thông điệp bỏ cuộc"


def test_co_vong_lap_cho_toi_khi_du_profile():
    khoi = _khoi_cho_sanh()
    assert "while True:" in khoi
    assert "if not not_ready:" in khoi and "break" in khoi, \
        "phải thoát vòng khi mọi profile đã vào sảnh"


def test_van_thoat_duoc_bang_nut_dung():
    """Lặp vô hạn mà không có đường thoát là treo cứng."""
    khoi = _khoi_cho_sanh()
    i = khoi.index("while True:")
    than = khoi[i:]
    assert than.count("_should_stop()") >= 2, \
        "phải kiểm nút Dừng cả sau khi chuẩn bị lẫn sau khi chờ"
    assert "asyncio.sleep(3.0)" in than, "thiếu nghỉ giữa hai vòng -> quay tít"


def test_van_giu_tieu_chuan_moi_profile_phai_o_chon_ban():
    """Kiên trì KHÔNG có nghĩa là hạ tiêu chuẩn: một nick kẹt ngoài sảnh chính
    là nick giữ tiền vào bàn rồi ngồi một mình với người lạ."""
    khoi = _khoi_cho_sanh()
    assert 'man != "chon_ban"' in khoi
    assert "not_ready.append(p_name)" in khoi


def test_khong_spam_thong_bao_moi_vong():
    khoi = _khoi_cho_sanh()
    assert "da_bao_ly_do" in khoi
    assert "if mo_ta != da_bao_ly_do:" in khoi, "báo lại mỗi vòng sẽ trôi mất log khác"


def test_thong_bao_noi_ro_van_dang_thu_tiep():
    khoi = _khoi_cho_sanh()
    assert "vẫn thử tiếp" in khoi, "người dùng phải biết tool chưa bỏ cuộc"


# ---------- lý do phải đúng ----------

def test_ly_do_bao_man_hinh_truoc_popup_sau():
    """Popup chỉ là ghi chú kèm. Báo popup rồi thoát luôn là giấu mất lý do thật."""
    code = _code(AFC / "lobby.py")
    i = code.index("async def ly_do_chua_o_sanh")
    than = code[i:i + 2500]
    assert than.index("__autotool_man_hinh") < than.index("__autotool_ten_popup"), \
        "phải xác định màn hình TRƯỚC khi xét popup"
    assert "return 'có popup/quảng cáo che màn hình';" not in than, \
        "vẫn thoát sớm khi thấy popup -> giấu lý do thật"


def test_ly_do_kem_ten_node_bi_coi_la_popup():
    """Không có tên node thì không truy được vì sao nó báo nhầm."""
    than = _code(AFC / "lobby.py")
    assert "__autotool_ten_popup" in than
    assert 'node "' in than, "phải in tên node ra thông điệp"


def test_extension_xuat_ham_khai_ten_popup():
    code = _code(EXT)
    assert "function tenPopupDangChe()" in code
    assert "G.__autotool_ten_popup = tenPopupDangChe;" in code
    # hasBlockingPopup phải dùng lại đúng một nguồn, không dò hai lần hai kiểu
    i = code.index("function hasBlockingPopup()")
    assert "tenPopupDangChe()" in code[i:i + 200]


def test_ten_popup_kem_kich_thuoc_de_doi_chieu():
    """`PopupNode` rỗng phủ toàn màn 1560x720 từng làm hàm này luôn trả true.
    Có kích thước trong log thì nhận ra ngay trường hợp đó."""
    code = _code(EXT)
    i = code.index("function tenPopupDangChe()")
    than = code[i:i + 2200]
    assert "getBoundingBoxToWorld()" in than

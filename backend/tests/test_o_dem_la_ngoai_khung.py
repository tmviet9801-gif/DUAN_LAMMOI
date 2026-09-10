"""Ô "Tiến Lên Đếm Lá" nằm ngoài khung nhìn — kéo danh sách rồi mới bấm.

ĐO ĐƯỢC trên máy người dùng (2 account chạy thật, 07:13–07:15):

    Account 01: bấm 'tab_game_bai' tại (333, 125) — node=GameBai     <- vào được
    Account 01: chưa bấm được ô TIẾN LÊN ĐẾM LÁ — không tính được vị trí
    Account 01: sau vòng 3 vẫn ở màn 'game_bai' -> thử lại.

Cả hai account vào được màn Game Bài nhưng ô Đếm Lá luôn ngoài khung. Cửa sổ
profile đo được rộng ~780px, còn dãy card game là một `cc.ScrollView` cuộn
ngang — ô Đếm Lá nằm ngoài mép phải nên `viTriNodeTrenCanvas` trả null.

Và thông điệp báo lý do lại chỉ ra:

    đang bị chặn bởi node "Banner 759x450"

trên CẢ Account 01 (người dùng xác nhận không có popup nào) lẫn Account 02.
`Banner` là banner quảng cáo của màn Game Bài, luôn hiện, không chặn thao tác.
Nó nằm trong biểu thức khớp tên popup nên làm `isAlreadyInTLDLLobby()` luôn
false — profile không bao giờ được coi là sẵn sàng.
"""
import re
from pathlib import Path

EXT = Path(__file__).parents[1] / "extension" / "content_main.js"


def _code() -> str:
    """Chỉ lấy dòng CODE, bỏ cả khối `/** */` — chú thích chứa chuỗi đang cấm."""
    src = re.sub(r"/\*.*?\*/", "", EXT.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(d for d in src.splitlines() if not d.strip().startswith("//"))


# ---------- Banner không phải popup ----------

def test_banner_khong_con_tinh_la_popup_theo_ten():
    code = _code()
    i = code.index("function tenPopupDangChe()")
    than = code[i:i + 2500]
    m = re.search(r"/\^\(([a-z|]+)\)/", than)
    assert m, "không tìm thấy biểu thức khớp tên popup"
    ten = m.group(1).split("|")
    assert "banner" not in ten, f"`banner` vẫn bị tính là popup: {ten}"
    # các tên còn lại phải giữ
    for can in ("popup", "dialog", "quangcao", "announce", "notice"):
        assert can in ten, f"mất `{can}` khỏi danh sách"


def test_van_bat_duoc_canh_bao_lua_dao_bang_CHU():
    """Bỏ khớp tên `banner` không được làm mất popup cảnh báo thật — nó có chữ."""
    code = _code()
    i = code.index("function tenPopupDangChe()")
    than = code[i:i + 2500]
    assert 'text === "CẢNH BÁO LỪA ĐẢO"' in than
    assert 'text === "BỎ QUA"' in than


# ---------- kéo danh sách để lộ ô ----------

def test_co_ham_keo_node_vao_khung():
    code = _code()
    assert "function keoNodeVaoKhung(node)" in code
    than = code[code.index("function keoNodeVaoKhung(node)"):][:2200]
    assert "cc.ScrollView" in than, "phải tìm ScrollView, không kéo mò"
    assert "scrollToOffset" in than


def test_keo_tuc_thoi_khong_dung_tween():
    """Có thời lượng thì Cocos chạy tween và phép đo ngay sau đó vẫn ra vị trí cũ."""
    code = _code()
    than = code[code.index("function keoNodeVaoKhung(node)"):][:2200]
    m = re.search(r"scrollToOffset\(.*?,\s*([0-9.]+)\s*\)", than, re.S)
    assert m, "không đọc được thời lượng cuộn"
    assert float(m.group(1)) == 0, f"thời lượng phải là 0, đang là {m.group(1)}"
    # Đường thứ hai: một số bản Cocos chỉ áp dụng offset ở khung hình kế tiếp.
    assert "noiDung.x = -dx" in than


def test_thu_keo_TRUOC_khi_bao_that_bai():
    code = _code()
    i = code.index("G.__autotool_vi_tri_muc = function")
    than = code[i:i + 1800]
    assert "keoNodeVaoKhung(node)" in than
    assert than.index("keoNodeVaoKhung(node)") < than.index("ngoài khung nhìn"), \
        "phải thử kéo trước khi kết luận không bấm được"


def test_hong_an_toan_khi_khong_co_scrollview():
    """Không có ScrollView thì trả false, không được ném lỗi hay kéo bừa."""
    code = _code()
    than = code[code.index("function keoNodeVaoKhung(node)"):][:2200]
    assert "if (!sv) return false;" in than
    assert than.count("catch (e)") >= 3, "mọi truy cập Cocos phải bọc try/catch"


# ---------- thông điệp phải nói số đo ----------

def test_bao_so_do_that_khi_ngoai_khung():
    """"ngoài khung hình?" trần không truy được gì: lệch bao nhiêu, chiều nào?"""
    code = _code()
    i = code.index("G.__autotool_vi_tri_muc = function")
    than = code[i:i + 1800]
    assert "viTriNodeChiTiet(node)" in than
    for can in ("nx=", "ny=", "cỡ=", "khung="):
        assert can in than, f"thiếu số đo `{can}` trong thông điệp"


def test_chi_tiet_tra_ve_ca_khi_ngoai_khung():
    """`viTriNodeTrenCanvas` trả null khi ngoài khung — nên cần hàm thứ hai."""
    code = _code()
    than = code[code.index("function viTriNodeChiTiet(node)"):][:1600]
    assert "trongKhung:" in than
    assert "return null" not in than.split("trongKhung:")[0].split("const nx")[-1], \
        "không được từ chối sớm — phải trả số đo kể cả khi ngoài khung"


def test_bao_kem_ten_node_va_sprite():
    code = _code()
    i = code.index("G.__autotool_vi_tri_muc = function")
    than = code[i:i + 1800]
    khoi = than[than.index("ngoài khung nhìn"):][:400]
    assert "node.name" in khoi and "tenSprite(node)" in khoi

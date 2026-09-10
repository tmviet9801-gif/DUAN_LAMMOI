"""Lời mời vào bàn: LUÔN từ chối, không bao giờ nhận.

Người dùng nêu rõ lý do: nhận lời mời nghĩa là ngồi vào bàn của khách, trong khi
cả luồng gom bàn được dựng để các tài khoản của chính họ ngồi cùng nhau.

Kiểm chứng được rằng từ chối hết là AN TOÀN: tool join bằng `cmd 308` theo rid,
không có đường nào bấm "CHẤP NHẬN". `__active_room_invite` chỉ là cờ điều phối
nội bộ do controller đặt (matching.py), không dính gì tới popup của game.

ĐO ĐƯỢC trên ảnh chụp thật khung 1264×705:
    popup mời vào bàn      -> 1.000 tại (531, 456)
    popup cảnh báo lừa đảo -> 0.390   (không bắt nhầm)
    sảnh ALL GAMES         -> 0.433
    màn Game Bài           -> 0.404
    sảnh chọn bàn          -> 0.400
"""
import re
import sys
from pathlib import Path

import pytest

BE = Path(__file__).parents[1]
ASSETS = BE / "assets" / "templates"
LOBBY = BE / "controllers" / "auto_flow_controller" / "lobby.py"
EXT = BE / "extension" / "content_main.js"

if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from controllers.auto_flow_controller.lobby import _match_template_cv  # noqa: E402

MAU = ASSETS / "tu_choi_het_1264.png"


def _code(p: Path) -> str:
    """Chỉ lấy dòng CODE.

    Với .py phải bỏ CẢ DOCSTRING chứ không chỉ dòng `#`: docstring giải thích
    "vì sao không bấm nút nhận lời mời" chứa đúng chuỗi đang cấm, và chính test
    này đã đỏ lần đầu vì thế.
    """
    src = p.read_text(encoding="utf-8")
    if p.suffix == ".py":
        src = re.sub(r'"""[\s\S]*?"""', "", src)
        src = re.sub(r"'''[\s\S]*?'''", "", src)
    else:
        src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    mo = "#" if p.suffix == ".py" else "//"
    return "\n".join(d for d in src.splitlines() if not d.strip().startswith(mo))


# ---------- ảnh mẫu ----------

def test_co_anh_mau_tu_choi_het():
    assert MAU.is_file(), "thiếu ảnh mẫu nút TỪ CHỐI HẾT"


def test_khop_dung_nut_va_khong_bat_nham_nen():
    tpl = cv2.imread(str(MAU), cv2.IMREAD_COLOR)
    nen = np.full((705, 1264, 3), 25, np.uint8)
    nen[434:434 + tpl.shape[0], 441:441 + tpl.shape[1]] = tpl
    ok, buf = cv2.imencode(".png", nen)
    loc, diem = _match_template_cv(buf.tobytes(), str(MAU))
    assert loc is not None and diem > 0.9
    assert abs(loc[0] - (441 + tpl.shape[1] // 2)) <= 4

    trong = np.full((705, 1264, 3), 25, np.uint8)
    ok, buf = cv2.imencode(".png", trong)
    loc2, diem2 = _match_template_cv(buf.tobytes(), str(MAU))
    assert loc2 is None, f"bắt nhầm trên nền trơn (điểm {diem2:.3f})"


@pytest.mark.parametrize("rong", [800, 1264, 1920])
def test_khop_o_moi_kich_thuoc(rong):
    tpl = cv2.imread(str(MAU), cv2.IMREAD_COLOR)
    nen = np.full((705, 1264, 3), 25, np.uint8)
    nen[434:434 + tpl.shape[0], 441:441 + tpl.shape[1]] = tpl
    r = cv2.resize(nen, (rong, int(rong * 705 / 1264)))
    ok, buf = cv2.imencode(".png", r)
    loc, diem = _match_template_cv(buf.tobytes(), str(MAU))
    assert loc is not None, f"cửa sổ rộng {rong}: không khớp (điểm {diem:.3f})"


# ---------- luồng điều hướng ----------

def test_tu_choi_TRUOC_khi_bam_nut_X():
    """Đóng bằng X thì lời mời còn nguyên và popup hiện lại ở bước sau."""
    code = _code(LOBBY)
    assert "async def _tu_choi_moi" in code, "thiếu hàm từ chối lời mời"
    # Mốc cắt phải là CODE, không phải chú thích "Bước 1" (đã bị lọc).
    i = code.index("await _tu_choi_moi()")
    j = code.index("loc_close, score_close = _match_template_cv")
    assert i < j, "phải từ chối lời mời TRƯỚC khi dò nút X"


def test_xet_lai_loi_moi_o_giua_luong():
    """Lời mời có thể tới bất cứ lúc nào, không chỉ ở đầu."""
    code = _code(LOBBY)
    assert code.count("_tu_choi_moi(") >= 3, "chỉ xét một lần là bỏ sót"


def test_khong_bao_gio_bam_chap_nhan():
    """Nhận lời mời = ngồi vào bàn của khách. Không có đường nào được phép."""
    for f in (LOBBY, EXT):
        code = _code(f)
        assert "CHẤP NHẬN" not in code, f"{f.name}: có đường bấm CHẤP NHẬN"
        assert "chap_nhan" not in code.lower().replace("chapnhan", "chap_nhan")


def test_extension_cung_nhan_dien_bang_CHU():
    """Đường Cocos-native nhận theo chữ, độc lập với ảnh mẫu."""
    code = _code(EXT)
    assert 'text === "TỪ CHỐI HẾT"' in code


def test_khong_lan_voi_nut_THOAT_HET():
    """`THOÁT HẾT` là thoát game — vẫn phải nằm trong danh sách cấm."""
    code = _code(EXT)
    assert 'text !== "THOÁT HẾT"' in code
    i = code.index('text === "TỪ CHỐI HẾT"')
    assert 'text !== "THOÁT"' in code[i:i + 700], "mất lớp chặn nút Thoát"


def test_hong_an_toan_khi_khong_co_loi_moi():
    """Không thấy lời mời thì trả False, không bấm gì."""
    code = _code(LOBBY)
    i = code.index("async def _tu_choi_moi")
    than = code[i:i + 1200]
    assert "return False" in than
    assert "except Exception" in than


def test_co_moi_khong_lam_hong_luong_gom_ban():
    """`__active_room_invite` là cờ nội bộ do controller đặt, KHÔNG phải popup
    của game — từ chối popup không được đụng tới nó."""
    code = _code(LOBBY)
    i = code.index("async def _tu_choi_moi")
    than = code[i:i + 1200]
    assert "__active_room_invite" not in than

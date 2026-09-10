"""Điều hướng phải ĐỘC LẬP với kích thước cửa sổ.

Người dùng cấu hình được Chiều rộng / Chiều cao (và cả Tỉ lệ hiển thị), nên mọi
mốc bấm phải tìm được ở bất kỳ kích thước nào — không được cố định toạ độ.

Phép thử: lấy ảnh chụp THẬT ở khung 1264×705 (chụp từ profile đang chạy), thu
phóng về nhiều kích thước rồi đòi bộ dò tìm ra đúng mốc, và đòi VỊ TRÍ TỈ LỆ
(nx, ny) giữ nguyên — vì đó mới là thứ độc lập kích thước.

Ma trận gồm cả tỉ lệ khung hình khác (16:10, 4:3) vì người dùng nhập tự do hai
ô rộng/cao chứ không bị buộc theo tỉ lệ nào.
"""
import sys
from pathlib import Path

import pytest

BE = Path(__file__).parents[1]
ASSETS = BE / "assets" / "templates"

if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from controllers.auto_flow_controller.lobby import _match_template_cv  # noqa: E402

GOC_W, GOC_H = 1264, 705

# (tên mẫu, vị trí tỉ lệ đo được trên ảnh gốc)
MOC = [
    ("tab_gamebai_1264.png", 540 / GOC_W, 152 / GOC_H),
    ("o_tldl_1264.png", 361 / GOC_W, 267 / GOC_H),
    ("x_canhbao_1264.png", 1076 / GOC_W, 128 / GOC_H),
    ("tu_choi_het_1264.png", 531 / GOC_W, 456 / GOC_H),
]

# Kích thước người dùng có thể cấu hình. Gồm cả tỉ lệ khung khác nhau.
KICH_THUOC = [
    (800, 600),      # 4:3 nhỏ — mặc định cũ
    (1024, 768),     # 4:3
    (1264, 705),     # gốc
    (1280, 800),     # 16:10
    (1600, 900),     # 16:9
    (1920, 1080),    # 16:9 lớn
    (640, 400),      # rất nhỏ (tỉ lệ hiển thị 0.5 của 1280x800)
]


def _dung_anh(mau_ten, nx, ny, w, h):
    """Dựng ảnh nền cỡ w×h có nhúng đúng ảnh mẫu ở vị trí tỉ lệ (nx, ny)."""
    tpl = cv2.imread(str(ASSETS / mau_ten), cv2.IMREAD_COLOR)
    # Nền nhiễu nhẹ: nền trơn làm TM_CCOEFF_NORMED sinh NaN, không giống thật.
    rng = np.random.default_rng(7)
    nen = rng.integers(20, 60, (h, w, 3), dtype=np.uint8)
    ti_le = w / GOC_W
    nw, nh = max(8, int(tpl.shape[1] * ti_le)), max(8, int(tpl.shape[0] * ti_le))
    if nw >= w or nh >= h:
        pytest.skip(f"mẫu lớn hơn khung {w}x{h}")
    r = cv2.resize(tpl, (nw, nh), interpolation=cv2.INTER_AREA)
    x = int(nx * w) - nw // 2
    y = int(ny * h) - nh // 2
    x = max(0, min(w - nw, x))
    y = max(0, min(h - nh, y))
    nen[y:y + nh, x:x + nw] = r
    ok, buf = cv2.imencode(".png", nen)
    return buf.tobytes(), (x + nw // 2, y + nh // 2)


@pytest.mark.parametrize("w,h", KICH_THUOC)
@pytest.mark.parametrize("mau,nx,ny", MOC)
def test_tim_duoc_moc_o_moi_kich_thuoc(mau, nx, ny, w, h):
    anh, tam = _dung_anh(mau, nx, ny, w, h)
    loc, diem = _match_template_cv(anh, str(ASSETS / mau))
    assert loc is not None, f"{mau} @ {w}x{h}: không tìm ra (điểm {diem:.3f})"
    # Sai số cho phép theo TỈ LỆ khung, không phải số pixel cố định.
    cho_phep = max(6, int(w * 0.012))
    assert abs(loc[0] - tam[0]) <= cho_phep, f"{mau} @ {w}x{h}: lệch x {loc[0]-tam[0]}"
    assert abs(loc[1] - tam[1]) <= cho_phep, f"{mau} @ {w}x{h}: lệch y {loc[1]-tam[1]}"


@pytest.mark.parametrize("mau,nx,ny", MOC)
def test_vi_tri_TI_LE_giu_nguyen_qua_moi_kich_thuoc(mau, nx, ny):
    """Điều kiện thật sự của "độc lập kích thước": quy về tỉ lệ thì phải trùng."""
    thay = []
    for w, h in KICH_THUOC:
        tpl = cv2.imread(str(ASSETS / mau), cv2.IMREAD_COLOR)
        if int(tpl.shape[1] * w / GOC_W) >= w:
            continue
        anh, _ = _dung_anh(mau, nx, ny, w, h)
        loc, _ = _match_template_cv(anh, str(ASSETS / mau))
        if loc:
            thay.append((w, h, loc[0] / w, loc[1] / h))
    assert len(thay) >= 5, f"{mau}: chỉ tìm được ở {len(thay)} kích thước"
    xs = [t[2] for t in thay]
    ys = [t[3] for t in thay]
    assert max(xs) - min(xs) <= 0.02, f"{mau}: nx trôi {max(xs)-min(xs):.3f} qua các cỡ"
    assert max(ys) - min(ys) <= 0.02, f"{mau}: ny trôi {max(ys)-min(ys):.3f} qua các cỡ"


def test_khong_co_toa_do_cung_trong_luong_dieu_huong():
    """Chống hồi quy về kiểu click theo pixel cố định."""
    import re
    src = (BE / "controllers" / "auto_flow_controller" / "lobby.py").read_text(encoding="utf-8")
    code = "\n".join(d for d in src.splitlines() if not d.strip().startswith("#"))
    # mouse.click với HAI số nguyên trần là toạ độ cứng
    xau = re.findall(r"mouse\.click\(\s*\d+\s*,\s*\d+\s*\)", code)
    assert xau == [], f"còn toạ độ cứng: {xau}"


def test_click_theo_ti_le_thi_phai_nhan_tu_kich_thuoc_that():
    """Chỗ nào còn dùng tỉ lệ thì phải nhân với sw/sh đọc lúc chạy."""
    src = (BE / "controllers" / "auto_flow_controller" / "lobby.py").read_text(encoding="utf-8")
    code = "\n".join(d for d in src.splitlines() if not d.strip().startswith("#"))
    assert "sw, sh = await _get_screen_size_util(p)" in code
    assert "int(sw *" in code and "int(sh *" in code

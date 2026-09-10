"""Tỉ lệ hiển thị: cửa sổ nhỏ trên màn hình, trang vẫn thấy đủ khung hình.

Vì sao cần: đo trên máy người dùng, cửa sổ 800×600 làm ô "Tiến Lên Đếm Lá" nằm
ngoài mép phải dãy card game — luồng đứng mãi ở màn Game Bài. Nâng lên 1280×800
thì đủ khung, nhưng không xếp nổi 10 tab trên một màn hình.

Cách của các trình duyệt antidetect: `--window-size` tính bằng DIP, còn
`--force-device-scale-factor=f` đặt devicePixelRatio = f. Trang VẪN thấy đúng
`width × height` pixel CSS, nhưng cửa sổ chỉ chiếm `width*f × height*f` pixel
thật. 1280×800 với tỉ lệ 0.5 -> cửa sổ 640×400.

Điểm dễ hỏng nhất là PHÉP BẤM: `_get_screen_size_util` đọc
`window.innerWidth/innerHeight` (pixel CSS) và chuột Playwright cũng nhận pixel
CSS. Hai bên cùng đơn vị nên toạ độ vẫn đúng — test dưới khoá đúng điều đó.
"""
import json
import re
from pathlib import Path

BE = Path(__file__).parents[1]
APP = BE.parent / "app" / "renderer"
BROWSER = BE / "services" / "browser_service.py"
LOBBY = BE / "controllers" / "auto_flow_controller" / "lobby.py"


def _code(p: Path) -> str:
    src = p.read_text(encoding="utf-8")
    if p.suffix in (".js", ".html"):
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    mo = "#" if p.suffix == ".py" else "//"
    return "\n".join(d for d in src.splitlines() if not d.strip().startswith(mo))


# ---------- cờ Chrome ----------

def test_dat_co_force_device_scale_factor():
    code = _code(BROWSER)
    assert "--force-device-scale-factor=" in code
    assert "win_scale" in code


def test_khong_dat_co_khi_ti_le_bang_1():
    """Tỉ lệ 1 là kích thước thật — thêm cờ thừa chỉ tạo khác biệt vô cớ giữa
    các profile."""
    code = _code(BROWSER)
    i = code.index("--force-device-scale-factor=")
    truoc = code[max(0, i - 200):i]
    assert "if win_scale != 1.0:" in truoc


def test_window_size_KHONG_bi_nhan_ti_le():
    """`--window-size` tính bằng DIP. Nhân thêm tỉ lệ là thu nhỏ HAI lần, trang
    lại hụt khung hình đúng như lỗi ban đầu."""
    code = _code(BROWSER)
    m = re.search(r'--window-size=\{([^}]*)\},\{([^}]*)\}', code)
    assert m, "không tìm thấy tham số --window-size"
    assert "scale" not in m.group(1) and "scale" not in m.group(2), \
        f"window-size bị nhân tỉ lệ: {m.group(0)}"


def test_ti_le_bi_chan_trong_khoang_an_toan():
    code = _code(BROWSER)
    i = code.index("win_scale = min(")
    assert "min(1.0, max(0.25, win_scale))" in code[i:i + 80]


def test_gia_tri_hong_khong_lam_do_chuong_trinh():
    code = _code(BROWSER)
    i = code.index("win_scale = float(")
    khoi = code[i - 60:i + 200]
    assert "except (TypeError, ValueError)" in khoi
    assert "win_scale = 1.0" in khoi, "hỏng phải lùi về kích thước thật"


def test_offset_xep_chong_theo_ti_le():
    """Cửa sổ thu nhỏ mà vẫn dịch 40px mỗi tab thì xếp chồng thưa vô lý."""
    code = _code(BROWSER)
    assert "40 * win_scale" in code


# ---------- phép bấm không được đổi ----------

def test_toa_do_bam_van_tinh_bang_pixel_CSS():
    """Đây là chỗ dễ hỏng nhất khi đổi tỉ lệ. `window.innerWidth` là pixel CSS,
    chuột Playwright cũng nhận pixel CSS — không được chèn devicePixelRatio."""
    code = _code(LOBBY)
    i = code.index("async def _get_screen_size_util")
    than = code[i:i + 400]
    assert "window.innerWidth" in than and "window.innerHeight" in than
    assert "devicePixelRatio" not in than, "đừng quy đổi — hai bên đã cùng đơn vị"


def test_khong_noi_devicePixelRatio_vao_phep_nhan_toa_do():
    code = _code(LOBBY)
    i = code.index("sw, sh = await _get_screen_size_util(p)")
    khoi = code[i:i + 300]
    assert 'int(sw * float(vt["nx"]))' in khoi
    assert "devicePixelRatio" not in khoi


# ---------- cấu hình + giao diện ----------

def test_mac_dinh_la_kich_thuoc_that():
    import sys
    if str(BE) not in sys.path:
        sys.path.insert(0, str(BE))
    from models.config_model import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["window"]["scale"] == 1.0


def test_giao_dien_co_o_nhap_ti_le():
    html = INDEX = (APP / "index.html").read_text(encoding="utf-8")
    khoi = html.split('id="cfgWinScale"', 1)
    assert len(khoi) == 2, "thiếu ô nhập tỉ lệ"
    sau = khoi[1][:260]
    assert 'min="0.25"' in sau and 'max="1"' in sau


def test_giao_dien_doc_va_ghi_ti_le():
    assert 'cfgWinScale").value = w.scale || 1' in _code(APP / "js" / "render.js")
    luu = _code(APP / "js" / "actions.js")
    assert "scale:" in luu
    i = luu.index("scale:")
    assert "Math.min(1" in luu[i:i + 80] and "Math.max(0.25" in luu[i:i + 80], \
        "giao diện phải chặn cùng khoảng với backend"

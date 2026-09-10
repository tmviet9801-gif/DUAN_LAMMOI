"""Ảnh mẫu điều hướng: phải có trong git, và phải khớp ở mọi kích thước cửa sổ.

ĐO ĐƯỢC bằng cách mở profile thật, chụp màn hình rồi khớp lại (khung 1264×705):

    ô Tiến Lên Đếm Lá : mẫu cũ 0.447  ->  mẫu mới 1.000 tại (361, 267)
    tab Game Bài      : mẫu cũ 0.477  ->  mẫu mới 1.000 tại (540, 152)
    nút X cảnh báo    : mẫu cũ 0.761  ->  mẫu mới 1.000 tại (1076, 128)

Ngưỡng là 0.75 nên hai mẫu đầu TRƯỢT SẠCH — đúng dòng log lặp suốt hai phút
"không nhận ra tab GAME BÀI (độ khớp cao nhất 0.00 < 0.75)". Đường OpenCV chưa
bao giờ chạy được, và không phải vì thuật toán.

Hai nguyên nhân cộng dồn:
  1. Ảnh mẫu chụp ở cửa sổ nhỏ, cũ so với giao diện hiện tại.
  2. Chúng nằm trong `backend/data/` vốn bị gitignore -> chưa từng được commit,
     nên máy cài mới không có file nào.
"""
import shutil
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

MAU_CAN = ("o_tldl_1264.png", "tab_gamebai_1264.png", "x_canhbao_1264.png")


# ---------- ảnh mẫu phải đi kèm mã nguồn ----------

def test_anh_mau_nam_ngoai_thu_muc_bi_gitignore():
    """`backend/data/` chứa thông tin đăng nhập thật nên bị gitignore. Để ảnh
    mẫu ở đó là chúng không bao giờ tới được máy người dùng."""
    assert ASSETS.is_dir(), "thiếu backend/assets/templates/"
    for ten in MAU_CAN:
        assert (ASSETS / ten).is_file(), f"thiếu ảnh mẫu {ten}"


def test_lobby_doc_tu_assets_truoc():
    src = (BE / "controllers" / "auto_flow_controller" / "lobby.py").read_text(encoding="utf-8")
    code = "\n".join(d for d in src.splitlines() if not d.strip().startswith("#"))
    assert '"assets" / "templates"' in code
    assert "tpl_dir = _assets if _assets.exists() else _data" in code


def test_van_lui_ve_thu_muc_cu_neu_thieu():
    """Không được phá máy đang chạy có ảnh mẫu ở chỗ cũ."""
    src = (BE / "controllers" / "auto_flow_controller" / "lobby.py").read_text(encoding="utf-8")
    code = "\n".join(d for d in src.splitlines() if not d.strip().startswith("#"))
    i = code.index("def _mau(")
    assert "for thu_muc in (tpl_dir, _data)" in code[i:i + 400]


# ---------- khớp được ở mọi kích thước cửa sổ ----------

def _anh(w, h=None):
    """Dựng ảnh nền có nhúng đúng ảnh mẫu ở một vị trí biết trước."""
    tpl = cv2.imread(str(ASSETS / "o_tldl_1264.png"), cv2.IMREAD_COLOR)
    nen = np.full((h or int(w * 705 / 1264), w, 3), 30, np.uint8)
    ti_le = w / 1264.0
    nw, nh = max(10, int(tpl.shape[1] * ti_le)), max(10, int(tpl.shape[0] * ti_le))
    r = cv2.resize(tpl, (nw, nh))
    x, y = int(277 * ti_le), int(185 * ti_le)
    nen[y:y + nh, x:x + nw] = r
    ok, buf = cv2.imencode(".png", nen)
    return buf.tobytes(), (x + nw // 2, y + nh // 2)


@pytest.mark.parametrize("rong", [800, 1024, 1264, 1600, 1920])
def test_khop_o_moi_kich_thuoc_cua_so(rong):
    """`cv2.matchTemplate` KHÔNG bất biến theo tỉ lệ, mà người dùng đổi được
    kích thước cửa sổ và cả tỉ lệ hiển thị. Dải cũ 0.7–1.3 không phủ nổi."""
    anh, tam = _anh(rong)
    loc, diem = _match_template_cv(anh, str(ASSETS / "o_tldl_1264.png"))
    assert loc is not None, f"cửa sổ rộng {rong}: không khớp (điểm {diem:.3f})"
    assert abs(loc[0] - tam[0]) <= max(8, rong // 100)
    assert abs(loc[1] - tam[1]) <= max(8, rong // 100)


def test_dai_ti_le_du_rong():
    src = (BE / "controllers" / "auto_flow_controller" / "lobby.py").read_text(encoding="utf-8")
    code = "\n".join(d for d in src.splitlines() if not d.strip().startswith("#"))
    assert "np.linspace(0.4, 2.0" in code, "dải tỉ lệ chưa đủ rộng cho 800 -> 1920"


# ---------- ba nguyên nhân hỏng phải phân biệt được ----------

def test_thieu_file_mau_bao_rieng(tmp_path, caplog):
    anh, _ = _anh(1264)
    with caplog.at_level("WARNING"):
        loc, diem = _match_template_cv(anh, str(tmp_path / "khong-co.png"))
    assert loc is None and diem == 0.0
    assert "THIẾU FILE MẪU" in caplog.text


def test_anh_chup_hong_bao_rieng(caplog):
    with caplog.at_level("WARNING"):
        loc, diem = _match_template_cv(b"khong-phai-anh", str(ASSETS / "o_tldl_1264.png"))
    assert loc is None and diem == 0.0
    assert "KHÔNG GIẢI MÃ ĐƯỢC" in caplog.text


def test_khop_kem_that_thi_tra_diem_that():
    """Khớp kém phải ra ĐIỂM THẬT, không được lẫn với 0.00 của lỗi kỹ thuật —
    đó là thứ khiến hai phút log không nói được nguyên nhân."""
    nen = np.random.randint(0, 255, (705, 1264, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", nen)
    loc, diem = _match_template_cv(buf.tobytes(), str(ASSETS / "o_tldl_1264.png"))
    assert loc is None
    assert 0.0 <= diem < 0.75


def test_khong_bat_nham_o_game_khac():
    """Ô Đếm Lá không được khớp với nền trơn hay ô game khác."""
    nen = np.full((705, 1264, 3), 60, np.uint8)
    ok, buf = cv2.imencode(".png", nen)
    loc, diem = _match_template_cv(buf.tobytes(), str(ASSETS / "o_tldl_1264.png"))
    assert loc is None, f"bắt nhầm trên nền trơn (điểm {diem:.3f})"


def test_duong_dan_thu_muc_mau_dung_ba_cap():
    """Bản cũ dùng hai cấp parent -> trỏ vào `backend/controllers/data/templates`
    vốn không tồn tại. Ảnh mẫu CHƯA BAO GIỜ được đọc, và mọi lần khớp trả 0.00
    vì thiếu file — nguyên nhân gốc của dòng log lặp hai phút.

    Kiểm bằng chính phép tính đường dẫn, không kiểm chuỗi ký tự.
    """
    lobby = BE / "controllers" / "auto_flow_controller" / "lobby.py"
    goc = lobby.resolve().parent.parent.parent
    assert goc.name == "backend", f"ba cấp parent phải ra backend, ra {goc}"
    assert (goc / "assets" / "templates").is_dir()
    # và hai cấp thì KHÔNG ra được — khoá lại để không ai rút bớt
    assert not (lobby.resolve().parent.parent / "data" / "templates").exists()

    src = lobby.read_text(encoding="utf-8")
    code = "\n".join(d for d in src.splitlines() if not d.strip().startswith("#"))
    assert "parent.parent.parent" in code
    assert 'Path(__file__).resolve().parent.parent / "data"' not in code


def test_moi_anh_mau_deu_doc_duoc_that():
    """Có file mà cv2 không đọc nổi cũng ra 0.00 — kiểm luôn."""
    for f in sorted(ASSETS.glob("*.png")):
        img = cv2.imread(str(f), cv2.IMREAD_COLOR)
        assert img is not None, f"cv2 không đọc được {f.name}"
        assert img.shape[0] >= 10 and img.shape[1] >= 10, f"{f.name} quá nhỏ"

"""Kiểm điều kiện trước khi mở profile vào bàn.

Mở Chrome rồi mới phát hiện account hết tiền là quá muộn — lúc đó đã ngồi vào
bàn. Account thiếu tiền còn bị server đá ra giữa chừng, để account giữ tiền
ngồi lại một mình với người lạ.
"""
from pathlib import Path

import pytest

from controllers.auto_flow_controller.preflight import (
    SO_DU_TOI_THIEU_DO_DUOC,
    danh_gia,
    loc_profile_du_dieu_kien,
    so_du_toi_thieu,
)


# ---------- số dư tối thiểu: ĐO được, không phỏng đoán ----------

def test_ban_100_chi_can_5_lan_khong_phai_10():
    """Quy tắc KHÔNG đều. Đo từ trường `mM` của khung cmd 300: bàn $100 cần 500."""
    assert so_du_toi_thieu(100) == 500
    assert so_du_toi_thieu(100) == 5 * 100


def test_tu_500_tro_len_la_10_lan():
    for bet in (500, 1_000, 2_000, 5_000, 10_000, 50_000, 1_000_000):
        assert so_du_toi_thieu(bet) == bet * 10, f"bàn ${bet}"


def test_bang_khop_voi_so_do_that():
    """Bảng phải khớp đúng số đo, không được sửa tay lệch đi."""
    assert SO_DU_TOI_THIEU_DO_DUOC[100] == 500
    for bet, m in SO_DU_TOI_THIEU_DO_DUOC.items():
        if bet != 100:
            assert m == bet * 10


def test_muc_cuoc_la_thi_dung_he_so_du_phong():
    assert so_du_toi_thieu(777) == 7_770


def test_muc_cuoc_khong_hop_le():
    assert so_du_toi_thieu(0) == 0
    assert so_du_toi_thieu(None) == 0
    assert so_du_toi_thieu("abc") == 0


# ---------- đánh giá một account ----------

ACC = {"name": "Account 01", "character_name": "nicktestxxabai1"}


def test_du_dieu_kien():
    dat, ly_do = danh_gia(
        {"ten_in_game": "nicktestxxabai1", "so_du": 95_745}, ACC, 100)
    assert dat is True and ly_do == ""


def test_thieu_tien_thi_bi_loai_va_noi_ro_con_thieu_bao_nhieu():
    dat, ly_do = danh_gia(
        {"ten_in_game": "nicktestxxabai1", "so_du": 400}, ACC, 100)
    assert dat is False
    assert "400" in ly_do and "500" in ly_do


def test_vua_du_thi_qua():
    dat, _ = danh_gia({"ten_in_game": "x", "so_du": 500}, ACC, 100)
    assert dat is True


def test_thieu_mot_dong_o_ban_500():
    dat, ly_do = danh_gia({"ten_in_game": "x", "so_du": 4_999}, ACC, 500)
    assert dat is False and "5.000" in ly_do


def test_khong_doc_duoc_trang_thai_thi_khong_mo():
    """Không biết gì về account thì mở ra là mò mẫm."""
    dat, ly_do = danh_gia(
        {"ten_in_game": None, "so_du": None,
         "loi": "Token hết hạn hoặc không hợp lệ"}, ACC, 100)
    assert dat is False
    assert "hết hạn" in ly_do


def test_thieu_ten_in_game_thi_bi_loai():
    """Xác minh đồng đội khớp CHÍNH XÁC tên in-game; thiếu nó thì vào bàn vô nghĩa."""
    acc = {"name": "Account03", "character_name": None}
    dat, ly_do = danh_gia({"ten_in_game": None, "so_du": 999_999}, acc, 100)
    assert dat is False
    assert "tên in-game" in ly_do


def test_ten_in_game_trong_database_van_duoc_chap_nhan():
    """Đọc hụt tên nhưng database đã có thì vẫn đủ dùng."""
    dat, _ = danh_gia({"ten_in_game": None, "so_du": 10_000}, ACC, 100)
    assert dat is True


# ---------- lọc danh sách ----------

class _FakeAdapter:
    """Adapter KHÔNG mở Chrome — `peek_page` chỉ tra session sẵn có."""

    def __init__(self):
        self.da_goi_page = False

    def peek_page(self, name):
        return None

    async def _page(self, name):
        self.da_goi_page = True
        raise AssertionError("_page() mở Chrome — preflight không được gọi")


def _gia_lap_live(monkeypatch, theo_ten):
    import controllers.auto_flow_controller.preflight as pf

    async def _fake(adapter, hub, account, **kw):
        return theo_ten.get(account.get("name"), {})
    monkeypatch.setattr(pf, "check_one_profile", _fake)


@pytest.mark.anyio
async def test_loc_bo_account_thieu_tien_va_giu_thu_tu(monkeypatch):
    _gia_lap_live(monkeypatch, {
        "Account 01": {"ten_in_game": "ten01", "so_du": 95_745},
        "Account 02": {"ten_in_game": "ten02", "so_du": 300},      # thiếu
        "Account03":  {"ten_in_game": "ten03", "so_du": 28_200},
    })
    accs = [{"name": "Account 01"}, {"name": "Account 02"}, {"name": "Account03"}]
    ad = _FakeAdapter()

    dat, bi_loai = await loc_profile_du_dieu_kien(ad, None, accs, 100)

    assert [a["name"] for a in dat] == ["Account 01", "Account03"], "phải giữ thứ tự"
    assert len(bi_loai) == 1
    assert bi_loai[0]["profile"] == "Account 02"
    assert bi_loai[0]["so_du"] == 300
    assert ad.da_goi_page is False, "preflight KHÔNG được mở Chrome"


@pytest.mark.anyio
async def test_ghi_lai_ten_in_game_vua_doc_duoc(monkeypatch):
    """Tên vừa đọc tươi hơn bản trong database."""
    _gia_lap_live(monkeypatch, {
        "Account 01": {"ten_in_game": "ten_moi", "so_du": 10_000},
    })
    accs = [{"name": "Account 01", "character_name": "ten_cu"}]
    dat, _ = await loc_profile_du_dieu_kien(_FakeAdapter(), None, accs, 100)
    assert dat[0]["character_name"] == "ten_moi"
    assert accs[0]["character_name"] == "ten_cu", "không được sửa bản gốc tại chỗ"


@pytest.mark.anyio
async def test_loi_khi_doc_khong_lam_do_ca_luot(monkeypatch):
    import controllers.auto_flow_controller.preflight as pf

    async def _no(adapter, hub, account, **kw):
        if account["name"] == "Account 02":
            raise RuntimeError("mạng hỏng")
        return {"ten_in_game": "ok", "so_du": 99_999}
    monkeypatch.setattr(pf, "check_one_profile", _no)

    accs = [{"name": "Account 01"}, {"name": "Account 02"}]
    dat, bi_loai = await loc_profile_du_dieu_kien(_FakeAdapter(), None, accs, 100)
    assert [a["name"] for a in dat] == ["Account 01"]
    assert "mạng hỏng" in bi_loai[0]["ly_do"]


@pytest.mark.anyio
async def test_bo_qua_ban_ghi_hong(monkeypatch):
    _gia_lap_live(monkeypatch, {})
    dat, bi_loai = await loc_profile_du_dieu_kien(
        _FakeAdapter(), None, [None, {}, {"name": ""}], 100)
    assert dat == [] and bi_loai == []


# ---------- nối vào luồng join ----------

def _matching():
    return (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
            / "matching.py").read_text(encoding="utf-8")


def test_kiem_dieu_kien_chay_TRUOC_khi_mo_chrome():
    """Thứ tự là toàn bộ giá trị của tính năng này."""
    src = _matching()
    i_loc = src.index("loc_profile_du_dieu_kien(")
    i_mo = src.index("page_a = await adapter._page(profile_a)")
    assert i_loc < i_mo, "preflight phải chạy TRƯỚC khi mở profile"


def test_account_giu_tien_khong_dat_thi_dung_han():
    src = _matching()
    assert "Account giữ tiền" in src
    assert "không vào bàn được" in src


def test_khong_con_tu_chon_account_thay_nguoi_dung():
    """Bản trước lùi về ["Account 01", "Account 02"] khi không ai chọn gì."""
    code = "\n".join(d for d in _matching().splitlines()
                     if not d.strip().startswith("#"))
    assert '["Account 01", "Account 02"]' not in code


def test_co_duong_tat_khi_can():
    """Cần chạy được cả khi đường kiểm hỏng — nhưng phải chủ động tắt."""
    assert 'body.get("kiem_truoc", True)' in _matching()


# ---------- giao diện ----------

def _renderer(*phan):
    return (Path(__file__).parents[2] / "app" / "renderer"
            ).joinpath(*phan).read_text(encoding="utf-8")


def test_ui_va_backend_dung_cung_nguong_so_du():
    """Hai bảng lệch nhau thì giao diện báo xanh còn backend chặn — người dùng
    không hiểu vì sao."""
    ui = _renderer("js", "autoplay.js")
    assert "soDuToiThieu" in ui
    assert "b === 100 ? 500 : b * 10" in ui, "ngưỡng UI phải khớp preflight.py"


def test_ui_canh_bao_truoc_khi_bam():
    ui = _renderer("js", "autoplay.js")
    assert "sẽ KHÔNG được mở" in ui
    assert "Chưa biết số dư" in ui
    # đổi mức cược thì ngưỡng đổi theo
    assert 'gcBetSelect").addEventListener("change"' in ui


def test_loi_backend_hien_ra_ly_do_khong_phai_json_tho():
    """FastAPI trả {"detail": "..."} — ném cả JSON ra thì người dùng đọc cái vỏ."""
    api = _renderer("js", "api.js")
    assert "j.detail" in api
    assert "JSON.parse(raw)" in api

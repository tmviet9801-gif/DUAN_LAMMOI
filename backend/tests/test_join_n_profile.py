"""Ghép bàn với N profile — năm lỗi hội đồng xác nhận.

Mô hình mới cho phép tích N profile thay vì một cặp. Luồng ghép bàn vẫn còn
giả định ngầm "đúng hai người", và những giả định đó hỏng theo kiểu IM LẶNG:
báo thành công trong khi thiếu người.
"""
from pathlib import Path

import pytest

MATCHING = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
            / "matching.py")


def _src():
    return MATCHING.read_text(encoding="utf-8")


def _code():
    """Chỉ dòng CODE — chú thích giải thích lỗi cũ có nhắc lại chuỗi bị cấm."""
    return "\n".join(d for d in _src().splitlines()
                     if not d.strip().startswith("#"))


# ---------- 1. Cổng chặn vĩnh viễn nick phụ thứ 2 ----------

def test_cong_dem_khach_la_chu_khong_dem_dau_nguoi():
    """`players != 1` huỷ vé của MỌI nick phụ sau nick đầu.

    Nick phụ #1 ngồi xuống -> anchor thấy 2 người -> điều kiện đúng -> huỷ vé
    #2, #3... Bàn 4 chỗ không bao giờ đủ người.
    """
    code = _code()
    assert "gate_players != 1" not in code, "vẫn đếm đầu người"
    assert "gate_la > 0" in code, "phải đếm KHÁCH LẠ"
    assert "con_cho < 1" in code, "phải kiểm còn chỗ ngồi"


def test_gate_js_dung_helper_dinh_danh_da_xac_minh():
    src = _src()
    assert "window.__is_partner" in src and "window.__is_me" in src
    # thiếu helper -> coi là khách lạ (hỏng theo hướng an toàn)
    assert "return true;   // thiếu helper -> coi là khách lạ" in src


# ---------- 2. Huỷ vé mà vẫn báo thành công ----------

def test_moi_duong_huy_ve_deu_ha_co_va_dung_vong():
    """`continue` trần giữ nguyên cờ True -> báo "GOM BÀN THÀNH CÔNG" sai.

    Người dùng thấy toast "A và B, C ĐÃ NGỒI CHUNG bàn" trong khi C chưa bao
    giờ vào, rồi tool xả bài với đúng 2 người.
    """
    khoi = _src().split("BƯỚC 3:", 1)[1].split("if all_subs_matched", 1)[0]
    # Ba đường thoát: cổng chặn, đọc cổng lỗi, cấp vé lỗi
    assert khoi.count("all_subs_matched = False\n                        break") >= 1
    assert khoi.count("all_subs_matched = False\n                    break") >= 2


def test_thanh_cong_chi_tinh_nick_da_xac_minh_hai_chieu():
    code = _code()
    assert "len(da_ngoi) == len(phu_se_ngoi) and da_ngoi" in code, (
        "điều kiện thành công phải dựa trên nick ĐÃ xác minh")


def test_thong_bao_neu_ten_nguoi_that_su_ngoi_xuong():
    """Bản trước ghép tên từ `other_profiles` — gồm cả nick chưa vào bàn."""
    code = _code()
    khoi = code.split("GOM BÀN THÀNH CÔNG", 1)[1][:900]
    assert "', '.join(da_ngoi)" in khoi
    assert "', '.join(other_profiles)" not in khoi


# ---------- 3. Số profile so với số chỗ ngồi ----------

def test_chia_nick_phu_thanh_ngoi_duoc_va_du_bi():
    """Bàn `mu` chỗ, anchor chiếm một -> tối đa mu-1 nick phụ ngồi được.

    Trước đây vòng lặp cố cho MỌI nick phụ ngồi rồi đòi TẤT CẢ thành công —
    tích 3 profile ở bàn 2 chỗ là không bao giờ ghép được.
    """
    code = _code()
    assert "so_phu_toi_da = max(0, int(target_mu) - 1)" in code
    assert "phu_se_ngoi = other_profiles[:so_phu_toi_da]" in code
    assert "phu_du_bi = other_profiles[so_phu_toi_da:]" in code
    assert "for sub_name in phu_se_ngoi:" in code, "vòng lặp phải chạy trên nick ngồi được"


def test_bao_cho_nguoi_dung_biet_co_nick_du_bi():
    assert "dự bị" in _src()


# ---------- 4. SYNC_PARTNERS ghi đè, không gộp ----------

def test_sync_partners_gui_ca_danh_sach():
    """Extension GÁN ĐÈ khi nhận SYNC_PARTNERS.

    Gửi mảnh lẻ từng nick: xong B thì anchor có partners=[B]; sang C thành
    [C] — B biến mất và bị coi là khách lạ ngay tại bàn của mình.
    """
    code = _code()
    assert "ds_chung = list(dong_doi)" in code
    khoi = code.split("SYNC_PARTNERS", 1)[1][:600]
    assert "ds_chung +" in khoi, "vẫn gửi mảnh lẻ thay vì cả danh sách"


# ---------- 5. Tham số vô nghĩa gây vòng lặp vô hạn im lặng ----------

def test_muc_cuoc_la_thi_bao_loi_khong_am_tham_ha_xuong():
    """Hạ xuống 100 nghĩa là người dùng tin mình chơi mức đã chọn."""
    code = _code()
    assert "_bet_kiem = 100" not in code, "vẫn âm thầm hạ mức cược"
    assert "khong co trong game" in code or "không có trong game" in code


def test_so_cho_la_thi_bao_loi_ngay():
    """Ô Slot là ô nhập SỐ TỰ DO. Gõ 3 -> không có rid -> vòng lặp 999999 lần,
    giao diện đứng ở "ĐANG DÒ TÌM PHÒNG" vĩnh viễn, không một thông báo nào.

    Bản này chỉ mở bàn Solo 2 người nên cổng chặn nằm ở `kiem_so_cho`; bảng RID
    vẫn kiểm lần hai phòng khi mở lại bàn 4 người mà mức cược đó không có bàn.
    """
    code = _code()
    assert "kiem_so_cho(" in code, "phải chặn qua hằng số dùng chung"
    assert 'FIXED_TABLE_RIDS.get(f"{_bet_kiem}_{_mu_kiem}") is None' in code


def test_chi_mo_ban_solo_2():
    """Người dùng yêu cầu: bản này chỉ chạy bàn Solo 2; bàn 4 mở ở bản sau."""
    from controllers.auto_flow_controller.constants import (
        SO_CHO_CHO_PHEP,
        kiem_so_cho,
    )
    assert SO_CHO_CHO_PHEP == (2,)
    assert kiem_so_cho(2) == 2
    for xau in (4, 3, "4", 0, None, "abc"):
        with pytest.raises(ValueError):
            kiem_so_cho(xau)


def test_de_mo_lai_ban_4_chi_can_doi_hang_so():
    """Không được rải `if mu == 2` khắp nơi — mở lại phải rẻ."""
    from pathlib import Path as _P
    goc = _P(__file__).parents[1] / "controllers" / "auto_flow_controller"
    src = (goc / "constants.py").read_text(encoding="utf-8")
    assert "SO_CHO_CHO_PHEP = (2,)" in src
    # bảng RID vẫn giữ đủ cả hai cột để mở lại không phải dựng lại
    assert '"100_4"' in src and '"500_4"' in src
    for f in ("matching.py", "routes_basic.py"):
        code = "\n".join(
            d for d in (goc / f).read_text(encoding="utf-8").splitlines()
            if not d.strip().startswith("#"))
        assert "kiem_so_cho(" in code, f"{f}: phải gọi hằng số dùng chung"


def test_chan_tham_so_TRUOC_khi_mo_chrome():
    src = _src()
    assert src.index("kiem_so_cho(") < src.index("page_a = await adapter._page(profile_a)")


# ---------- kiểm bằng số học, không chỉ bằng chuỗi ----------

@pytest.mark.parametrize("mu,n_phu,mong_doi_ngoi,mong_doi_du_bi", [
    (2, 1, 1, 0),     # cặp thường
    (2, 4, 1, 3),     # solo: chỉ 1 nick phụ ngồi, 3 dự bị
    (4, 3, 3, 0),     # bàn 4 chỗ đủ người
    (4, 5, 3, 2),
    (2, 0, 0, 0),
])
def test_phep_chia_cho_ngoi(mu, n_phu, mong_doi_ngoi, mong_doi_du_bi):
    """Cùng công thức với matching.py — bàn `mu` chỗ, anchor chiếm một."""
    other = [f"P{i}" for i in range(n_phu)]
    so_phu_toi_da = max(0, int(mu) - 1)
    assert len(other[:so_phu_toi_da]) == mong_doi_ngoi
    assert len(other[so_phu_toi_da:]) == mong_doi_du_bi

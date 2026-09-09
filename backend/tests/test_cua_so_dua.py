"""Cửa sổ đua ~1 giây giữa "anchor còn một mình" và lúc nick phụ ngồi xuống.

Bàn 2 ghế. Xác minh anchor ngồi một mình -> cấp vé -> nick phụ join mất
0.5–1.5s (bốn lượt eval qua CDP + lệnh hub + join). Trong khoảng đó một người
chơi thật chiếm ghế còn lại và bấm Sẵn Sàng; khung cmd 363 tới trong ~200ms,
TRƯỚC khi hẹn giờ rời bàn kịp chạy.
"""
from pathlib import Path

EXT = Path(__file__).parents[1] / "extension" / "content_main.js"


def _code():
    return "\n".join(d for d in EXT.read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith("//"))


# ---------- một nút thắt duy nhất ----------

def test_exec_start_co_lop_gac_giong_exec_ready():
    """`exec_start` có BỐN đường gọi, trong đó đường từ khung cmd 363 đi thẳng
    vào chứ không qua `exec_ready` — nơi lớp gác từng nằm."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("G.__autotool_exec_start = function", 1)[1][:900]
    assert "khongDuocBatDauVoiNguoiLa()" in khoi
    assert "return false;" in khoi


def test_lop_gac_dung_chung_mot_ham():
    """Rải logic ở từng chỗ gọi là chắc chắn sót một chỗ."""
    code = _code()
    assert "function khongDuocBatDauVoiNguoiLa()" in code
    assert code.count("khongDuocBatDauVoiNguoiLa()") >= 3   # 1 khai báo + 2 dùng


def test_khong_chan_cung_theo_MATCH_ROLE():
    """`triggerVerifiedMatchReadyAndStart` cũng gọi exec_start và LUÔN chạy với
    MATCH_ROLE khác null — chặn cứng là nick chính không bao giờ bắt đầu được
    ván hợp lệ."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function khongDuocBatDauVoiNguoiLa()", 1)[1][:600]
    assert "find(isPartner)" in khoi, "phải xét CÓ đồng đội trong bàn hay không"
    assert "length > 1" in khoi


# ---------- ván đã đặt cược thì đánh hết ván ----------

def test_khong_roi_ban_giua_van():
    """Bỏ giữa chừng là mất cược và bị phạt bài — đắt hơn đánh hết ván."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("G.__autotool_exec_leave = function", 1)[1][:900]
    assert "G.__game_in_progress" in khoi
    assert "G.__leave_after_round = true" in khoi


def test_co_duong_roi_ngay_khi_can():
    """Cuối ván phải rời được thật, không bị chính chốt của mình chặn."""
    code = _code()
    assert "function (buocNgay)" in code
    assert "G.__autotool_exec_leave(true)" in code


def test_ket_van_thi_thuc_hien_lenh_roi_da_hoan():
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("AUTOTOOL_GAME_ENDED", 1)[1][:900]
    assert "G.__leave_after_round" in khoi
    assert "__autotool_exec_leave(true)" in khoi


# ---------- hẹn giờ rời bàn phải huỷ được ----------

def test_hen_gio_roi_ban_giu_handle():
    code = _code()
    assert "G.__stranger_leave_timer = setTimeout(" in code


def test_chia_bai_thi_huy_lenh_roi_dang_hen():
    """Ván đã chia bài = tiền đã đặt."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("if (p.cmd === 250)", 1)[1][:1600]
    assert "clearTimeout(G.__stranger_leave_timer)" in khoi
    assert "G.__leave_after_round = true" in khoi


def test_khach_la_tu_roi_thi_huy_lenh_out():
    """Bàn lại sạch thì không có lý do gì bỏ bàn mình đang giữ."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("actionType === 2", 1)[1][:1200]
    assert "clearTimeout(G.__stranger_leave_timer)" in khoi


def test_dang_cho_dong_doi_thi_khong_dung_cho_khach_bam_SS():
    """Nhánh chờ 3 giây nằm TRONG khối đã bị `dangChoDongDoi()` chặn, nên khi
    còn nick phụ chưa vào thì rơi thẳng xuống nhánh out."""
    src = EXT.read_text(encoding="utf-8")
    i_gac = src.index("if (!dangChoDongDoi() && G.__auto_start_guest_ss")
    i_cho = src.index("chờ tối đa 3s xem khách có SẴN SÀNG")
    i_out = src.index("HỦY LỆNH & Out bàn ngay!", i_gac)
    assert i_gac < i_cho < i_out, "nhánh chờ phải nằm trong khối bị chặn"

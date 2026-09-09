"""Bộ đo "bàn bị chen": chỉ đo và báo, KHÔNG tự dừng lượt chạy.

Không mang luật `chongPha` của Sunwin sang, vì đo trên chính bản ghi WS của dự
án cho thấy hai tín hiệu tương đương đều là sinh hoạt bình thường của sảnh:

  - "Vừa join đã thấy có người": 68/117 khung cmd 202 trong ws_capture.jsonl
    (58%). Mỗi (mức cược, số ghế) chỉ có ĐÚNG MỘT rid nên server tự xếp chỗ.
  - "Có người chen lúc đang giữ bàn": bốn người chơi thật khác nhau ngồi rồi đi
    ở cùng một bàn $100 trong chưa đầy một phút.

Nên cảnh báo chỉ bật khi CÙNG MỘT uid chen nhiều lần trong cửa sổ.
"""
import re
from pathlib import Path

from controllers.auto_flow_controller.thong_ke_pha import (
    CUA_SO_MAC_DINH,
    LY_DO_HOP_LE,
    NGUONG_CUNG_NGUOI,
    ghi_moc,
    tom_tat,
)

MATCHING = Path(__file__).parents[1] / "controllers" / "auto_flow_controller" / "matching.py"
THONG_KE = Path(__file__).parents[1] / "controllers" / "auto_flow_controller" / "thong_ke_pha.py"


def _code(p: Path) -> str:
    """Chỉ lấy dòng CODE — chú thích chứa đúng chuỗi đang cấm."""
    return "\n".join(d for d in p.read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith("#"))


# ---------- hàm thuần ----------

def test_ghi_moc_khong_sua_danh_sach_goc():
    goc = []
    ra = ghi_moc(goc, "khach_chen_khi_giu", 5, 1000.0, "u1")
    assert goc == [], "phải trả danh sách mới, không sửa tại chỗ"
    assert len(ra) == 1 and ra[0]["uid"] == "u1"


def test_ly_do_la_chuan_hoa_ve_khong_doc_duoc():
    ra = ghi_moc([], "linh tinh", 1, 0.0)
    assert ra[0]["ly_do"] == "khong_doc_duoc"
    for ly_do in LY_DO_HOP_LE:
        assert ghi_moc([], ly_do, 1, 0.0)[0]["ly_do"] == ly_do


def test_tom_tat_loai_moc_ngoai_cua_so():
    now = 10_000.0
    ds = []
    for i in range(6):
        ds = ghi_moc(ds, "khach_chen_khi_giu", 1, now - CUA_SO_MAC_DINH - 10 - i, "u1")
    for i in range(4):
        ds = ghi_moc(ds, "khach_chen_khi_giu", 1, now - i, "u1")
    tk = tom_tat(ds, now)
    assert tk["tong"] == 10
    assert tk["trong_cua_so"] == 4


def test_tom_tat_dem_theo_ly_do():
    ds = []
    ds = ghi_moc(ds, "khach_la", 1, 0.0)
    ds = ghi_moc(ds, "khach_la", 1, 0.0)
    ds = ghi_moc(ds, "ban_full", 1, 0.0)
    tk = tom_tat(ds, 0.0)
    assert tk["theo_ly_do"] == {"khach_la": 2, "ban_full": 1}


# ---------- điểm mấu chốt: khách KHÁC NHAU không phải bị phá ----------

def test_khach_khac_nhau_moi_lan_khong_canh_bao():
    """Đo được: bốn người chơi thật khác nhau ngồi rồi đi ở cùng một bàn trong
    chưa đầy một phút. Đếm tuyệt đối sẽ báo phá cho sinh hoạt bình thường."""
    ds = []
    for i, uid in enumerate(["Thongcat", "vanbidinh0704", "loijhddcsscc",
                             "baophat2015", "nguoila5", "nguoila6"]):
        ds = ghi_moc(ds, "khach_chen_khi_giu", 1, 100.0 + i, uid)
    tk = tom_tat(ds, 110.0)
    assert tk["trong_cua_so"] == 6
    assert tk["canh_bao"] is False, "khách khác nhau mỗi lần là sinh hoạt sảnh"


def test_cung_mot_nguoi_lap_lai_moi_canh_bao():
    ds = []
    for i in range(NGUONG_CUNG_NGUOI - 1):
        ds = ghi_moc(ds, "khach_chen_khi_giu", 1, 100.0 + i, "keypha")
    assert tom_tat(ds, 110.0)["canh_bao"] is False
    ds = ghi_moc(ds, "khach_chen_khi_giu", 1, 105.0, "keypha")
    tk = tom_tat(ds, 110.0)
    assert tk["canh_bao"] is True
    assert tk["ke_lap_lai"] == ["keypha"]


def test_join_trung_ban_co_nguoi_khong_bao_gio_canh_bao():
    """58% lần join rơi vào bàn đã có người — không được tính vào cảnh báo."""
    ds = []
    for i in range(50):
        ds = ghi_moc(ds, "khach_la", 1, 100.0 + i, "cung_mot_nguoi")
        ds = ghi_moc(ds, "ban_full", 1, 100.0 + i, "cung_mot_nguoi")
    tk = tom_tat(ds, 120.0)
    assert tk["tong"] == 100
    assert tk["canh_bao"] is False


def test_moc_khong_co_uid_khong_tinh():
    ds = []
    for i in range(10):
        ds = ghi_moc(ds, "khach_chen_khi_giu", 1, 100.0 + i)
    assert tom_tat(ds, 110.0)["canh_bao"] is False


def test_cau_hinh_xau_khong_canh_bao():
    ds = []
    for i in range(10):
        ds = ghi_moc(ds, "khach_chen_khi_giu", 1, 100.0 + i, "keypha")
    assert tom_tat([], 0.0)["canh_bao"] is False
    assert tom_tat(ds, 110.0, nguong_cung_nguoi=0)["canh_bao"] is False
    assert tom_tat(ds, 110.0, cua_so_giay=0)["canh_bao"] is False


def test_moc_lon_xon_thu_tu_van_dung():
    ds = [
        {"ly_do": "khach_chen_khi_giu", "rid": 1, "t": 108.0, "uid": "k"},
        {"ly_do": "khach_chen_khi_giu", "rid": 1, "t": 100.0, "uid": "k"},
        {"ly_do": "khach_chen_khi_giu", "rid": 1, "t": 104.0, "uid": "k"},
    ]
    assert tom_tat(ds, 110.0)["canh_bao"] is True


# ---------- nối vào matching.py ----------

def test_nhanh_join_phan_biet_ba_nguyen_nhan():
    """Gộp ba nguyên nhân thành một con số là làm số liệu vô nghĩa."""
    code = _code(MATCHING)
    khoi = code[code.index("if not is_empty:"):][:1400]
    for ly_do in ('"khong_doc_duoc"', '"khach_la"', '"ban_full"'):
        assert ly_do in khoi, f"thiếu {ly_do}"
    assert "r_info_cuoi" in khoi


def test_nhanh_bi_chen_ghi_kem_uid():
    code = _code(MATCHING)
    khoi = code[code.index("if not still_alone:"):][:1600]
    assert '"khach_chen_khi_giu"' in khoi
    assert "uid_la" in khoi, "phải ghi kèm danh tính người chen"


def test_alive_check_doc_duoc_uid_nguoi_la():
    code = _code(MATCHING)
    assert "uid_la" in code
    assert "__is_partner" in code[code.index("uid_la") - 800:code.index("uid_la")], \
        "phải loại đồng đội ra trước khi coi là người lạ"


def test_thong_ke_khong_dung_luot_chay():
    """Không được biến bộ đo thành nút Dừng ẩn."""
    code = _code(MATCHING)
    i = code.index("if not still_alone:")
    khoi = code[i:i + 1600]
    assert "gom_ban_stop_epoch" not in khoi
    assert "_dung_auto" not in khoi
    assert '"ok": False' not in khoi
    assert "VẪN CHẠY TIẾP" in khoi, "thông báo phải nói rõ tool không dừng"


def test_khong_dung_lai_ten_co_chong_pha():
    """`chong_pha` đã tồn tại với nghĩa khác ở routes_basic.py và auto_flow.py."""
    assert "chong_pha" not in _code(THONG_KE)
    assert "chong_pha" not in _code(MATCHING)


def test_thong_ke_co_trong_ca_hai_duong_tra_ve():
    code = _code(MATCHING)
    assert code.count('"thong_ke_pha": tom_tat(') == 2


def test_module_do_la_thuan():
    code = _code(THONG_KE)
    for cam in ("import fastapi", "from fastapi", "open(", "requests", "async def"):
        assert cam not in code, f"module đo phải thuần, không được có `{cam}`"

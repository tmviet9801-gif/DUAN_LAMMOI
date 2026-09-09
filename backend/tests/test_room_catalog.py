"""Bảng RID đọc từ server thay cho ảnh chụp chép cứng.

`FIXED_TABLE_RIDS` hôm nay đúng — đối chiếu 28 phòng trong bản bắt thật không
lệch dòng nào. Rủi ro là TRÔI: server thêm một mức cược hoặc đổi thứ tự là rid 2
thôi không còn là "$100 Solo", mà tool không có cách nào biết.
"""
import json
from pathlib import Path

from game_sim import room_catalog as rc

PHONG = [
    {"rid": 2, "b": 100, "Mu": 2, "gid": 1, "mM": 500, "rn": "DemLa#1"},
    {"rid": 1, "b": 100, "Mu": 4, "gid": 1, "mM": 500, "rn": "DemLa#0"},
    {"rid": 4, "b": 500, "Mu": 2, "gid": 1, "mM": 5000, "rn": "DemLa#3"},
    {"rid": 142, "b": 2000, "Mu": 4, "gid": 8, "mM": 0, "rn": "Phom#3"},
]


def test_chi_nhan_phong_dung_game():
    """Khung cmd 300 liệt kê bàn của MỌI game — Phom gid=8 lẫn vào là bắn nick
    phụ sang bàn Phom $2.000."""
    rid, _ = rc.gop_phong(PHONG, gid=1)
    assert rid == {"100_2": 2, "100_4": 1, "500_2": 4}
    assert 142 not in rid.values()


def test_lay_ca_so_du_toi_thieu():
    """`mM` cũng đang bị chép cứng ở preflight — đọc luôn từ đây."""
    _, so_du = rc.gop_phong(PHONG, gid=1)
    assert so_du == {"100": 500, "500": 5000}


def test_bo_phong_thieu_du_lieu_chu_khong_doan():
    """Đoán sai ở đây là gửi cả nhóm vào bàn khác mức cược."""
    rid, _ = rc.gop_phong([
        {"rid": 5, "Mu": 2, "gid": 1},              # thiếu b
        {"rid": 6, "b": 100, "gid": 1},             # thiếu Mu
        {"b": 100, "Mu": 2, "gid": 1},              # thiếu rid
        {"rid": 0, "b": 100, "Mu": 2, "gid": 1},    # rid không hợp lệ
        {"rid": 7, "b": 0, "Mu": 2, "gid": 1},      # cược 0
        "khong phai dict",
    ], gid=1)
    assert rid == {}


def test_quet_khung_cmd300():
    msgs = [{"text": json.dumps([5, {"cmd": 300, "rs": PHONG, "pR": 1}])}]
    rooms, nguon = rc._quet_khung(msgs, gid=1)
    assert nguon == "cmd300"
    assert len(rooms) == 4


def test_quet_khung_cmd305_lam_nguon_phu():
    """cmd 305 là đường game đẩy từng bàn một, có thể tới trước."""
    msgs = [{"text": json.dumps([5, {"cmd": 305, "ri": PHONG[0]}])},
            {"text": json.dumps([5, {"cmd": 305, "ri": PHONG[2]}])}]
    rooms, nguon = rc._quet_khung(msgs, gid=1)
    assert nguon == "cmd305"
    assert {r["rid"] for r in rooms} == {2, 4}


def test_khung_hong_khong_lam_do_ca_luot():
    msgs = [{"text": "khong phai json"}, {"text": "[]"}, {},
            {"text": json.dumps([5, {"cmd": 300, "rs": PHONG}])}]
    rooms, _ = rc._quet_khung(msgs, gid=1)
    assert len(rooms) == 4


# ---------- đối chiếu với ảnh chụp ----------

def test_phat_hien_bang_chep_cung_da_troi():
    lech = rc.doi_chieu({"100_2": 9}, {"100_2": 2})
    assert len(lech) == 1
    assert "rid 2" in lech[0] and "rid 9" in lech[0]


def test_khong_bao_lech_khi_van_khop():
    assert rc.doi_chieu({"100_2": 2, "500_2": 4},
                        {"100_2": 2, "500_2": 4, "1000_2": 6}) == []


def test_anh_chup_hien_tai_van_khop_so_do_that():
    """Chốt lại: bảng chép cứng khớp đúng 28 phòng đo được."""
    from controllers.auto_flow_controller.constants import FIXED_TABLE_RIDS

    do_duoc = {}
    thu_muc = Path(__file__).parents[1] / "data" / "game_sim_debug"
    if not thu_muc.exists():
        return
    for f in thu_muc.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if "rs" not in line:
                continue
            try:
                msg = json.loads(json.loads(line).get("text") or "null")
            except Exception:
                continue
            rooms, _ = rc._quet_khung([{"text": json.dumps(msg)}], gid=1)
            rid, _ = rc.gop_phong(rooms, gid=1)
            do_duoc.update(rid)
    if not do_duoc:
        return
    lech = rc.doi_chieu(do_duoc, FIXED_TABLE_RIDS)
    assert lech == [], f"ảnh chụp đã lệch số đo: {lech}"


# ---------- lưu / nạp ----------

def test_luu_roi_nap_lai(tmp_path):
    """Preflight chạy khi CHƯA có page nào nên phải đọc bản đã lưu."""
    dm = {"rid": {"100_2": 2}, "so_du_toi_thieu": {"100": 500}, "nguon": "cmd300"}
    assert rc.luu(tmp_path, dm, gid=1) is True
    muc = rc.nap(tmp_path, gid=1)
    assert muc["rid"] == {"100_2": 2}
    assert muc["so_du_toi_thieu"] == {"100": 500}
    assert muc["doc_luc"]


def test_khong_luu_danh_muc_rong(tmp_path):
    assert rc.luu(tmp_path, {"rid": {}}, gid=1) is False
    assert rc.nap(tmp_path, gid=1) is None


def test_nap_file_hong_khong_ne_loi(tmp_path):
    rc.duong_dan(tmp_path).write_text("{ hong", encoding="utf-8")
    assert rc.nap(tmp_path, gid=1) is None


def test_luu_nhieu_game_khong_de_len_nhau(tmp_path):
    rc.luu(tmp_path, {"rid": {"100_2": 2}}, gid=1)
    rc.luu(tmp_path, {"rid": {"2000_4": 142}}, gid=8)
    assert rc.nap(tmp_path, gid=1)["rid"] == {"100_2": 2}
    assert rc.nap(tmp_path, gid=8)["rid"] == {"2000_4": 142}


# ---------- nối vào luồng ----------

def test_luong_gom_ban_uu_tien_bang_doc_tu_server():
    src = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
           / "matching.py").read_text(encoding="utf-8")
    assert "room_catalog.doc_tu_server(" in src
    assert "room_catalog.doi_chieu(" in src
    assert "ctx.requested_rid = int(_rid_moi)" in src
    assert "DANH MỤC BÀN ĐÃ ĐỔI" in src


def test_preflight_uu_tien_so_du_doc_tu_server():
    src = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
           / "preflight.py").read_text(encoding="utf-8")
    assert "room_catalog.nap(" in src
    khoi = src.split("def so_du_toi_thieu", 1)[1][:700]
    assert khoi.index("_tu_danh_muc(") < khoi.index("SO_DU_TOI_THIEU_DO_DUOC[bet]")

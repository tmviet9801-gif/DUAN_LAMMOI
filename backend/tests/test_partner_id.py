"""Xác định đồng đội (backend/extension/partner_id.js).

Hàm này quyết định `findBestPlay(..., isPartnerActor)` — tức có cố tình đánh
nhẹ / bỏ lượt để người kia ăn hay không. Nhận nhầm một người chơi lạ thành
đồng đội = nạp bài cho họ, nên đây là hàm đắt nhất trong dự án khi sai.

Bản trước đoán theo HÌNH DẠNG TÊN (cắt số đuôi, gộp ký tự lặp, so chuỗi con).
Các test dưới khoá lại đúng những tên đã đo được là bị nhận nhầm.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PARTNER_ID = Path(__file__).parents[1] / "extension" / "partner_id.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="cần node để chạy partner_id.js")


def run_js(body: str):
    script = f"const P = require({json.dumps(str(PARTNER_ID))});\n{body}"
    out = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=120,
        encoding="utf-8",
    )
    assert out.returncode == 0, f"node lỗi:\n{out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


def la_dong_doi(target: dict, ctx: dict) -> bool:
    return run_js(
        f"console.log(JSON.stringify(P.laDongDoi({json.dumps(target)},"
        f" {json.dumps(ctx)})))"
    )


# tên in-game thật của hai account trong dự án
TOI = "nicktestxxabai1"
DONG_DOI = "nicktestxxabai2"


# ---------- phải nhận đúng đồng đội thật ----------

def test_nhan_dong_doi_qua_ten_in_game():
    assert la_dong_doi({"dn": DONG_DOI}, {"partners": [DONG_DOI]}) is True


def test_nhan_dong_doi_khong_phan_biet_hoa_thuong_va_khoang_trang():
    assert la_dong_doi({"dn": "  NickTestXXAbai2 "}, {"partners": [DONG_DOI]}) is True


def test_nhan_dong_doi_qua_uid():
    assert la_dong_doi({"uid": "1_643156423"},
                       {"partners": [{"uid": "1_643156423"}]}) is True


def test_nhan_dong_doi_qua_character_name_trong_database():
    """`character_name` do Check Live đọc về chính là tên in-game đã xác minh."""
    assert la_dong_doi({"dn": DONG_DOI},
                       {"partners": [{"profile_name": "Account 02",
                                      "character_name": DONG_DOI}]}) is True


def test_nhan_uid_khi_controller_gui_dang_chuoi_tran():
    """Extension đẩy `anchor_uid` vào danh sách dưới dạng chuỗi, không phải object.

    uid của game có dạng `1_643156061` — có gạch dưới. Phép thử "toàn chữ số"
    trượt, làm mất đường khớp uid.
    """
    assert la_dong_doi({"uid": "1_643156423"},
                       {"partners": ["1_643156423"]}) is True
    assert la_dong_doi({"uid": "1_643156999"},
                       {"partners": ["1_643156423"]}) is False


def test_ten_co_chu_cai_khong_bi_hieu_thanh_uid():
    """`player777` là TÊN, không phải uid — không được khớp uid `777`."""
    assert la_dong_doi({"uid": "777"}, {"partners": ["player777"]}) is False


def test_nhan_anchor_dang_cho_ghep_ban():
    assert la_dong_doi({"dn": DONG_DOI}, {"expected": {"dn": DONG_DOI}}) is True


def test_nhan_qua_loi_moi_con_han():
    ctx = {"invite": {"anchor_dn": DONG_DOI, "ts": 1000}, "now": 5000,
           "inviteTTL": 20000}
    assert la_dong_doi({"dn": DONG_DOI}, ctx) is True


def test_loi_moi_het_han_thi_khong_nhan():
    ctx = {"invite": {"anchor_dn": DONG_DOI, "ts": 1000}, "now": 999_000,
           "inviteTTL": 20000}
    assert la_dong_doi({"dn": DONG_DOI}, ctx) is False


# ---------- KHÔNG được nhận nhầm khách lạ ----------

@pytest.mark.parametrize("ten_khach", [
    # Đã đo: với tên tôi `nicktestxxabai1` (gốc `nicktestxabai`), bản cũ nhận
    # NHẦM cả 10 tên này thành đồng đội — gốc của họ là chuỗi con của gốc tôi
    # và số đuôi khác.
    "ai2", "i3", "bai3", "test5", "nick9", "cktest7", "xabai8", "abai2",
    "Ai9", "nic2",
])
def test_khach_la_co_ten_giong_hinh_dang_khong_duoc_nhan(ten_khach):
    ctx = {"partners": [DONG_DOI], "me": {"dn": TOI}}
    assert la_dong_doi({"dn": ten_khach}, ctx) is False, (
        f"'{ten_khach}' là người chơi lạ — nhận nhầm là nạp bài cho họ"
    )


def test_ten_dai_hon_khong_duoc_nhan():
    """`nicktestxxabai11` khác người với `nicktestxxabai1`."""
    assert la_dong_doi({"dn": "nicktestxxabai11"}, {"partners": [TOI]}) is False


def test_ten_profile_khong_bao_gio_duoc_dem_doi_chieu():
    """Tên profile trong app KHÔNG phải danh tính trong game.

    Đây chính là cầu nối sai đã sinh ra lỗi. Bản đầu chỉ siết từ so-mờ xuống
    so-khít — nghe an toàn, nhưng vẫn là cùng cây cầu: một người chơi thật đặt
    tên in-game trùng khít tên profile ("Account 01") sẽ được nhận là đồng đội.
    Controller nay luôn cấp `character_name` đã xác minh nên không cần nó nữa.
    """
    ctx = {"partners": [{"profile_name": "profile1"}]}
    assert la_dong_doi({"dn": "myprofile123"}, ctx) is False
    assert la_dong_doi({"dn": "profile12"}, ctx) is False
    assert la_dong_doi({"dn": "profile1"}, ctx) is False, (
        "trùng khít tên profile cũng không được coi là đồng đội")

    # Nhưng có character_name thì vẫn nhận bình thường
    ctx2 = {"partners": [{"profile_name": "Account 01",
                          "character_name": "nicktestxxabai1"}]}
    assert la_dong_doi({"dn": "nicktestxxabai1"}, ctx2) is True
    assert la_dong_doi({"dn": "Account 01"}, ctx2) is False


def test_controller_khong_day_ten_profile_vao_danh_sach():
    """Chặn ở cả phía gửi, không chỉ phía nhận."""
    from pathlib import Path

    src = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
           / "matching.py").read_text(encoding="utf-8")
    # Kiểm đúng NỘI DUNG danh sách, không kiểm cả dòng: `send_command(anchor_name,
    # ...)` chứa tên profile ở vị trí ĐÍCH GỬI, chuyện đó là đúng.
    #
    # Bắt theo phép NỐI `ds_chung + [...]` chứ không theo một dòng cụ thể: danh
    # sách có thể được đặt tên biến trung gian trước khi gửi, và bản trước của
    # test này đã đỏ đúng vì lý do đó dù ý định vẫn được giữ nguyên.
    noi = [d.strip() for d in src.splitlines() if "ds_chung +" in d]
    assert noi, "không tìm thấy chỗ dựng danh sách đồng đội từ ds_chung"
    for dong in noi:
        them = dong.split("ds_chung", 1)[1]
        assert "anchor_name" not in them and "sub_name" not in them, (
            f"còn đẩy tên profile vào danh sách đồng đội: {dong}")


def test_khach_la_hoan_toan_khong_duoc_nhan():
    ctx = {"partners": [DONG_DOI]}
    for ten in ("hihihihi23eee", "vodanh", "player777", "MinhAnh"):
        assert la_dong_doi({"dn": ten}, ctx) is False


def test_uid_khac_khong_duoc_nhan():
    assert la_dong_doi({"uid": "1_643156999"},
                       {"partners": [{"uid": "1_643156423"}]}) is False


# ---------- hỏng theo hướng an toàn ----------

def test_khong_co_danh_sach_thi_khong_ai_la_dong_doi():
    """Thiếu danh tính đã xác minh -> đánh như người thường, không đoán."""
    assert la_dong_doi({"dn": DONG_DOI}, {}) is False
    assert la_dong_doi({"dn": DONG_DOI}, {"partners": []}) is False


def test_danh_tinh_rong_khong_khop_bua():
    """Chuỗi rỗng không được khớp với chuỗi rỗng rồi nhận cả bàn là đồng đội."""
    ctx = {"partners": [{"dn": "", "u": "", "uid": ""}, ""]}
    assert la_dong_doi({"dn": "", "u": "", "uid": ""}, ctx) is False
    assert la_dong_doi({"dn": "nguoila"}, ctx) is False


def test_khong_co_nguoi_choi_thi_tra_false():
    assert la_dong_doi(None, {"partners": [DONG_DOI]}) is False


# ---------- nối vào dự án ----------

def _doc(*phan):
    return (Path(__file__).parents[1].joinpath(*phan)).read_text(encoding="utf-8")


def _dong_code(*phan):
    """Các dòng CODE của file, bỏ dòng chú thích.

    Phần giải thích lỗi cũ có nhắc lại chính những tên bị cấm, và đó là chủ ý —
    kiểm cả chú thích thì test đỏ vì tài liệu, không phải vì code.
    """
    return [d for d in _doc(*phan).splitlines() if not d.strip().startswith("//")]


def test_khong_con_danh_sach_dong_doi_hardcode():
    """Danh sách cứng trộn tên đăng nhập / tên in-game / tên profile.

    `profile1`, `account01` là những chuỗi quá chung; với so khớp chuỗi con cũ
    thì người chơi thật cũng dính. Danh sách thật phải do controller bơm xuống.
    """
    ds = _dong_code("extension", "content_main.js")
    for ten in ("nicktestxabai1", "nicktestxxabai1", "account01", "profile1",
                "profile2"):
        assert not any(f'"{ten}"' in d for d in ds), (
            f"còn hardcode '{ten}' trong content_main.js")
    assert any("G.__autotool_partners = [];" in d for d in ds)


def test_isPartner_khong_con_doan_theo_hinh_dang_ten():
    """Không được còn cắt số đuôi / gộp ký tự lặp / so chuỗi con để đoán."""
    ds = _dong_code("extension", "content_main.js")
    assert not any("collapseRepeats" in d for d in ds), (
        "vẫn còn so khớp theo hình dạng tên")
    assert any("AutoToolPartner" in d for d in ds), (
        "isPartner chưa uỷ quyền cho partner_id.js")


def test_partner_id_duoc_nap_truoc_content_main():
    import json as _j

    manifest = _j.loads(_doc("extension", "manifest.json"))
    js = manifest["content_scripts"][0]["js"]
    assert "partner_id.js" in js
    assert js.index("partner_id.js") < js.index("content_main.js"), js

    ctx = _doc("controllers", "auto_flow_controller", "context.py")
    thu_tu = ctx.split("for fname in (", 1)[1].split(")", 1)[0]
    assert "partner_id.js" in thu_tu
    assert thu_tu.index("partner_id.js") < thu_tu.index("content_main.js")


def test_preflight_bom_danh_sach_dong_doi_tu_database():
    """Extension khởi tạo rỗng -> không bơm xuống thì không ai nhận ai."""
    src = _doc("controllers", "auto_flow_controller", "matching.py")
    assert "danh_sach_dong_doi(list(pages.keys()), accounts)" in src
    assert "window.__autotool_partners = {_json.dumps(dong_doi)};" in src


# ---------- dựng danh sách từ database ----------

def test_danh_sach_dong_doi_dung_ten_in_game_khong_dung_ten_dang_nhap():
    from controllers.auto_flow_controller.context import danh_sach_dong_doi

    accounts = [
        {"name": "Account 01", "username": "nicktestxabai1",
         "character_name": "nicktestxxabai1", "uid": "1_643156061"},
        {"name": "Account 02", "username": "nicktestxabai2",
         "character_name": "nicktestxxabai2"},
    ]
    ds, thieu = danh_sach_dong_doi(["Account 01", "Account 02"], accounts)
    assert thieu == []
    assert [x["dn"] for x in ds] == ["nicktestxxabai1", "nicktestxxabai2"]
    # tên đăng nhập chỉ khác MỘT ký tự — tuyệt đối không được lọt vào
    moi_gia_tri = {v for x in ds for v in x.values()}
    assert "nicktestxabai1" not in moi_gia_tri
    assert "nicktestxabai2" not in moi_gia_tri


def test_bao_thieu_khi_profile_chua_co_ten_in_game():
    from controllers.auto_flow_controller.context import danh_sach_dong_doi

    accounts = [
        {"name": "Account 01", "character_name": "nicktestxxabai1"},
        {"name": "Account03", "character_name": None},
    ]
    ds, thieu = danh_sach_dong_doi(["Account 01", "Account03"], accounts)
    assert len(ds) == 1 and ds[0]["dn"] == "nicktestxxabai1"
    assert thieu == ["Account03"], "phải báo để người dùng chạy Check Live"


def test_khop_ten_profile_khong_phan_biet_hoa_thuong():
    from controllers.auto_flow_controller.context import danh_sach_dong_doi

    accounts = [{"name": "Account 01", "character_name": "nicktestxxabai1"}]
    ds, thieu = danh_sach_dong_doi(["account 01"], accounts)
    assert len(ds) == 1 and thieu == []

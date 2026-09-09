"""Chưa bật tool — hoặc đã chạy xong — thì phải hành xử như người dùng thường.

Hai đường làm mất tiền:
  1. Người lạ bấm Sẵn Sàng -> tool tự Bắt đầu ván tiền thật.
  2. Lượt chạy kết thúc nhưng cờ kích hoạt còn nguyên -> tool tự đánh bài,
     tự rời bàn, tự out khi người dùng chơi tay.
"""
from pathlib import Path

EXT = Path(__file__).parents[1] / "extension" / "content_main.js"
CTRL = Path(__file__).parents[1] / "controllers" / "auto_flow_controller"


def _js_dong_luot():
    """Chỉ KHỐI JS của `dong_luot_chay`, bỏ docstring.

    Docstring giải thích vì sao KHÔNG được đặt cờ Dừng, nên nó có nhắc lại
    chính chuỗi bị cấm — kiểm cả hàm là đỏ vì tài liệu, không phải vì code.
    """
    src = (CTRL / "lobby.py").read_text(encoding="utf-8")
    than = src.split("async def dong_luot_chay", 1)[1]
    return than.split('js = """', 1)[1].split('"""', 1)[0]


def _code(path):
    return "\n".join(d for d in path.read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith(("//", "#")))


# ---------- 1. START với người lạ ----------

def test_nhanh_cmd_363_co_du_ba_lop_gac():
    """Nhánh này TỪNG không có lớp gác nào.

    Không isAutoEngaged, không kiểm vai trò, không kiểm đang chờ đồng đội —
    bất kỳ ai bấm Sẵn Sàng là ván tiền thật chạy.
    """
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("if (p.cmd === 364 || p.cmd === 363)", 1)[1][:2200]
    assert "if (!isAutoEngaged())" in khoi, "thiếu cổng kích hoạt"
    assert "isSubMatchProfile()" in khoi, "nick phụ vẫn tự Bắt đầu được"
    assert "dangChoDongDoi()" in khoi, "vẫn Bắt đầu được khi đang chờ đồng đội"


def test_guard_dem_dong_doi_that_thay_cho_bien_da_chet():
    """`huntModeActive` đọc __AUTOTOOL_AUTO_HUNT, mà luồng gom bàn đặt cờ đó
    = false trên MỌI trang -> điều kiện `!huntModeActive` luôn đúng, lớp gác
    mà chú thích tuyên bố có thực ra không gác gì."""
    code = _code(EXT)
    assert "const huntModeActive =" not in code
    assert "function dangChoDongDoi()" in code
    khoi = code.split("function dangChoDongDoi()", 1)[1][:700]
    assert "__autotool_partners" in khoi
    assert "isPartner" in khoi
    assert "return true;" in khoi, "không chắc thì phải coi là đang chờ (hỏng an toàn)"


def test_controller_tat_co_guest_ss_khi_con_nick_phu_cho():
    """Có nick phụ mà bắt đầu với người lạ là phụ không vào được bàn nữa.

    Lớp gác Python đã đúng (`auto_start_guest_ss and not other_profiles`) nhưng
    extension hành động độc lập theo khung WS nên qua mặt được.
    """
    src = (CTRL / "matching.py").read_text(encoding="utf-8")
    assert "bool(auto_start_guest_ss) and not other_profiles" in src


# ---------- 2. Kết thúc lượt chạy phải tắt chế độ tự động ----------

def test_co_ham_dong_luot_chay_chay_tren_MOI_trang():
    src = (CTRL / "lobby.py").read_text(encoding="utf-8")
    assert "async def dong_luot_chay(pages" in src
    khoi = src.split("async def dong_luot_chay", 1)[1].split("async def ly_do_chua_o_sanh", 1)[0]
    assert "for ten, p in list((pages or {}).items())" in khoi, "phải chạy trên mọi trang"


def test_dong_luot_chay_tat_du_co_kich_hoat():
    """isAutoEngaged() là phép OR ba cờ — thiếu một cái là vẫn còn kích hoạt."""
    src = (CTRL / "lobby.py").read_text(encoding="utf-8")
    khoi = src.split("async def dong_luot_chay", 1)[1].split("async def ly_do_chua_o_sanh", 1)[0]
    for co in ("__AUTOTOOL_ENGAGED = false", "__AUTOTOOL_ARMED = false",
               "__AUTOTOOL_AUTO_HUNT = false", "__AUTOTOOL_AUTO_DISCARD = false",
               "__auto_start_guest_ss = false", "__target_hunt_bet = 0",
               "__AUTOTOOL_MATCH_ROLE = null", "__AUTOTOOL_SUB_JOIN_TICKET = null"):
        assert co in khoi, f"còn sót cờ: {co}"


def test_dong_luot_chay_xoa_bai_cua_dong_doi():
    """Không xoá thì ván đầu lượt sau đánh theo bài của lượt trước."""
    src = (CTRL / "lobby.py").read_text(encoding="utf-8")
    khoi = src.split("async def dong_luot_chay", 1)[1].split("async def ly_do_chua_o_sanh", 1)[0]
    assert "__partner_cards = null" in khoi


def test_dong_luot_chay_KHONG_dat_co_da_dung():
    """Chạy xong không phải là "người dùng đã bấm Dừng".

    Đặt AUTOTOOL_STOPPED ở đây sẽ làm lượt sau phải tự xoá, và dễ sinh lại
    đúng lỗi "nick phụ không bao giờ đánh bài" đã từng gặp.
    """
    assert "AUTOTOOL_STOPPED" not in _js_dong_luot(), (
        "khối JS của dong_luot_chay không được đặt cờ Dừng")


def test_moi_duong_thoat_deu_dong_luot_chay():
    """Preflight bật cờ trên mọi trang -> mọi đường ra đều phải tắt lại."""
    src = (CTRL / "matching.py").read_text(encoding="utf-8")
    assert src.count("await dong_luot_chay(pages") >= 4, "còn đường thoát bỏ sót"
    for ly_do in ("không vào được sảnh", "không gom được bàn",
                  "không bắt đầu được ván", "ván đã kết thúc"):
        assert ly_do in src, f"thiếu đường thoát: {ly_do}"


def test_khong_dong_luot_chay_khi_van_con_dang_chay():
    """Nhánh hết 45 giây cố ý giữ nguyên bàn để kiểm tra.

    Tắt AUTO_DISCARD giữa ván là nick phụ ngưng đánh -> bị treo lượt/phạt bài.
    """
    src = (CTRL / "matching.py").read_text(encoding="utf-8")
    assert "if game_completed:\n            await dong_luot_chay(pages" in src

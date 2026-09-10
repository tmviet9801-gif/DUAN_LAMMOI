"""Mọi account phải sẵn sàng ở SẢNH CHỌN BÀN trước khi chạy gom bàn.

Người dùng gặp thật: nick phụ đứng ở sảnh chính với popup quảng cáo, nhưng bị
báo là đã sẵn sàng — nên nick chính vẫn vào bàn và cả lượt chạy tiến hành trong
khi thiếu người.
"""
from pathlib import Path

EXT = Path(__file__).parents[1] / "extension" / "content_main.js"
CTRL = Path(__file__).parents[1] / "controllers" / "auto_flow_controller"


def _code(path):
    """Chỉ dòng CODE — chú thích giải thích lỗi cũ nhắc lại chuỗi bị cấm."""
    return "\n".join(d for d in path.read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith(("//", "#")))


# ---------- nhận diện sảnh ----------

def test_socket_dang_noi_khong_con_duoc_coi_la_da_o_sanh():
    """Socket nối KHÔNG đồng nghĩa đang ở sảnh chọn bàn.

    `lobby.py` đã ghi rõ luật cấm điều này, nhưng phía JS lại vi phạm bằng
    nhánh `hasSimmsWs && hasTLDLScene -> true`. Đó chính là đường làm nick phụ
    đứng ở sảnh chính vẫn được báo sẵn sàng.
    """
    code = _code(EXT)
    assert "if (hasSimmsWs && hasTLDLScene) return true;" not in code
    assert "return sanSang;" in code


def test_popup_che_man_thi_coi_la_chua_san_sang():
    """Popup che màn thì mọi click đều vô nghĩa — không thể gọi là sẵn sàng."""
    code = _code(EXT)
    assert "function hasBlockingPopup()" in code
    assert "if (hasBlockingPopup()) return false;" in code


def test_phat_hien_popup_dung_activeInHierarchy():
    """Cocos tắt UI bằng cách hạ cờ active của node CHA.

    Kiểm `node.active` của chính node sẽ thấy "đang bật" ở popup đã đóng —
    đúng lỗi đã sửa ở chỗ nhận diện bàn trước đây.
    """
    src = EXT.read_text(encoding="utf-8")
    # Phép dò nằm trong `tenPopupDangChe` (trả TÊN node để truy được khi báo
    # nhầm); `hasBlockingPopup` chỉ còn là lớp bọc trả boolean.
    khoi = src.split("function tenPopupDangChe()", 1)[1].split("function isAlreadyInTLDLLobby", 1)[0]
    assert "isNodeVisible(node)" in khoi
    assert "node.active" not in khoi, "vẫn kiểm node.active thay vì activeInHierarchy"


def test_dau_hieu_sanh_chinh_dem_theo_tap_khong_theo_co():
    """Một nhãn lạc trên màn chọn bàn không được làm hỏng nhận diện.

    Sảnh chính hiện đủ bộ GAME BÀI + SLOTS + MINI GAME + QUAY SỐ cùng lúc.
    """
    code = _code(EXT)
    assert "const dauHieuSanhChinh = new Set();" in code
    assert "dauHieuSanhChinh.size >= 2" in code


def test_khong_dung_quet_som_lam_mat_dau_hieu():
    """Điều kiện dừng sớm cũ thoát ngay khi đủ cờ -> đếm hụt dấu hiệu sảnh chính."""
    code = _code(EXT)
    assert "(hasTLDLScene && hasMainLobbyButtons)) return;" not in code


# ---------- thứ tự: dẹp popup TRƯỚC khi hỏi ----------

def test_dep_popup_truoc_khi_hoi_da_o_sanh_chua():
    """Thứ tự cũ hỏi trước; khi nhận nhầm thì trả True ngay và KHÔNG BAO GIỜ
    chạy tới bước dẹp popup / điều hướng bên dưới."""
    src = (CTRL / "lobby.py").read_text(encoding="utf-8")
    than = src.split("async def _ensure_in_tldl_lobby_util", 1)[1]
    i_dep = than.index("__autotool_dismiss_popups")
    i_hoi = than.index("if await _is_in_tldl_lobby_util(p):")
    assert i_dep < i_hoi, "vẫn hỏi trạng thái trước khi dẹp popup"


# ---------- rào chắn phải nói rõ lý do ----------

def test_rao_chan_noi_ro_ly_do_tung_profile():
    """Chỉ liệt kê tên thì người dùng không biết phải làm gì."""
    src = (CTRL / "matching.py").read_text(encoding="utf-8")
    assert "ly_do_chua_o_sanh(pages.get(p_name))" in src
    # Thông điệp đổi từ "KHÔNG chạy gom bàn" (bỏ cuộc) sang "vẫn thử tiếp":
    # tool không dừng nữa mà lặp lại tới khi đủ profile hoặc người dùng bấm Dừng.
    assert "vẫn thử tiếp" in src


def test_ly_do_phan_biet_ba_nguyen_nhan():
    src = (CTRL / "lobby.py").read_text(encoding="utf-8")
    khoi = src.split("async def ly_do_chua_o_sanh", 1)[1].split("def _match_template_cv", 1)[0]
    assert "extension chưa nạp" in khoi
    assert "popup" in khoi
    assert "__autotool_ly_do_chua_o_sanh" in khoi


def test_rao_chan_van_chan_that_su():
    """Rào chắn phải THẬT SỰ chặn, không được chỉ ghi log rồi chạy tiếp.

    Trước đây chặn bằng cách trả `ok: False` và tắt lượt chạy. Nay chặn bằng
    vòng lặp: chỉ `break` khi `not_ready` rỗng. Bất biến không đổi — chưa đủ
    profile ở sảnh chọn bàn thì tuyệt đối không được chạy tới bước chọn anchor.
    """
    src = (CTRL / "matching.py").read_text(encoding="utf-8")
    khoi = src.split("not_ready = [", 1)[1][:2500]
    assert "if not not_ready:" in khoi and "break" in khoi, "không còn đường thoát vòng"
    assert khoi.index("if not not_ready:") < khoi.index("break")
    toan = src.split("not_ready = [", 1)[1]
    assert toan.index("break") < toan.index("first_name = profile_a"), \
        "chọn anchor trước khi đủ profile -> nick giữ tiền ngồi một mình với người lạ"


def test_ham_bao_ly_do_duoc_xuat_ra_cho_python():
    code = _code(EXT)
    assert "G.__autotool_has_popup = hasBlockingPopup;" in code
    assert "G.__autotool_ly_do_chua_o_sanh" in code

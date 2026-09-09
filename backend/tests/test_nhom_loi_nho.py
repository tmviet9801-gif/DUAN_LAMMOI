"""Nhóm lỗi mức nhỏ — phần lớn là "hỏng theo hướng MỞ" và ô điều khiển chết.

Không cái nào tự làm mất tiền ngay, nhưng chúng che mất lỗi thật: cổng kiểm
xanh oan, người dùng chỉnh một ô không nối vào đâu, dữ liệu hiện sai dòng.
"""
from pathlib import Path

BE = Path(__file__).parents[1]
UI = Path(__file__).parents[2] / "app" / "renderer"


def _code(p):
    return "\n".join(d for d in p.read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith(("//", "#")))


# ---------- hỏng theo hướng MỞ ----------

def test_khong_biet_muc_cuoc_thi_khong_di_tiep():
    """Bản trước coi `None` và lỗi phân tích đều là "hợp lệ" -> cổng xanh oan."""
    src = (BE / "controllers/auto_flow_controller/matching.py").read_text(encoding="utf-8")
    khoi = src.split("wrong_bet = False", 1)[1][:1800]
    assert "if room_b is None:" in khoi
    assert khoi.split("if room_b is None:", 1)[1][:200].count("wrong_bet = True") == 1
    # lỗi phân tích cũng phải là SAI, không phải bỏ qua
    assert khoi.count("wrong_bet = True") >= 3


def test_extension_khong_bia_muc_cuoc():
    """Đo thực tế: 292/292 khung cmd 202 đều có `b`. Thiếu nó là bất thường."""
    code = _code(BE / "extension/content_main.js")
    assert "b: p.b || 100," not in code
    assert "typeof p.b === 'number' ? p.b : null" in code


def test_khong_tu_lay_5_chrome_dang_mo():
    """Gọi API mà quên `profiles` sẽ chạy trên 5 account BẤT KỲ đang đăng nhập."""
    code = _code(BE / "controllers/auto_flow_controller/matching.py")
    assert "profiles_input = open_acc_names[:5]" not in code


# ---------- họ lỗi so-chuỗi-con (bản sao 4 và 5) ----------

def test_page_current_room_khop_chinh_xac():
    """Tên tài khoản ngắn ('xabai1') là chuỗi con của tên người chơi bất kỳ
    ('nicktestxabai1') -> bàn $500 của NGƯỜI KHÁC bị nhận là phòng của mình."""
    code = _code(BE / "game_sim/adapters/hitclub.py")
    # Có HAI chỗ trong cùng file — test này đã bắt được chỗ thứ hai bị bỏ sót.
    assert "game_user in u or u in game_user" not in code
    assert code.count("u == game_user") >= 2


def test_ws_js_khong_doan_theo_chu_so_cuoi():
    """nicktestxabai1 / nicktestxxabai1 / nicktestxabai11 đều tận cùng '1'.

    Khớp chính xác trượt thì `endsWith("1")` gán cho account ĐẦU TIÊN tận cùng
    '1' — bài, số dư, số phòng của nick này hiện trên dòng nick khác.
    """
    code = _code(UI / "js/ws.js")
    assert 'p.endsWith("1")' not in code
    assert 'p.endsWith("2")' not in code
    assert "p === n || p === u || p === c || p === i" in code


# ---------- lệnh tồn đọng sau khi Dừng ----------

def test_trigger_ghep_ban_qua_cong_kich_hoat():
    """Controller/Hub phát lệnh bằng task RỜI — huỷ task gom bàn KHÔNG huỷ
    chúng. Vài chục ms sau khi Dừng, extension vẫn nhận được CONFIRM_MATCH."""
    src = (BE / "extension/content_main.js").read_text(encoding="utf-8")
    khoi = src.split("function triggerVerifiedMatchReadyAndStart", 1)[1][:900]
    assert "if (!isAutoEngaged())" in khoi


def test_nut_san_ban_noi_dung_trang_thai():
    """`__AUTOTOOL_AUTO_HUNT` không được khởi tạo (undefined) -> engine TẮT.

    Nhãn ghi "BẬT" là nói sai: bấm lần 1 tưởng tắt (không đổi gì), bấm lần 2 vì
    tưởng vừa tắt nhầm -> lúc này mới thật sự bật và xoá cờ AUTOTOOL_STOPPED.
    """
    code = _code(BE / "extension/content.js")
    assert "let isHuntOn = false;" in code
    assert 'huntBtn.innerHTML = "⚪ Săn Bàn: TẮT";' in code


# ---------- giao diện: ô chết và thông báo sai ----------

def test_khong_con_o_dieu_khien_chet():
    """Ô chết còn tệ hơn không có ô: người dùng chỉnh rồi kết luận tool hỏng.

    `gcSlotNum` nguy nhất — nhãn "Slot" trùng tên với ô Slot THẬT (gcSlotCount).
    """
    html = (UI / "index.html").read_text(encoding="utf-8")
    for o in ("gcWaitSS", "gcSSWhenEnter", "gcAutoLeave\"", "gcSlotNum",
              "gcWinW", "gcWinH", "gcDelay"):
        assert f'id="{o.rstrip(chr(34))}"' not in html, f"ô chết còn lại: {o}"


def test_khong_gui_truong_endpoint_khong_doc():
    code = _code(UI / "js/autoplay.js")
    for k in ("xa_delay_ms", "chong_pha", "out_guest"):
        assert k not in code, f"vẫn gửi {k} mà endpoint gom bàn không đọc"


def test_o_slot_that_co_gioi_han():
    """Ô nhập số tự do: gõ 3 là vòng lặp vô hạn im lặng (đã chặn ở backend,
    nhưng chặn từ giao diện thì người dùng biết ngay).

    Bản này chỉ mở bàn Solo 2 nên ô khoá cứng ở 2 và để `readonly`. Không ẩn ô:
    ẩn thì người dùng không biết đang chạy loại bàn nào.
    """
    html = (UI / "index.html").read_text(encoding="utf-8")
    khoi = html.split('id="gcSlotCount"', 1)[1][:260]
    assert 'min="2"' in khoi and 'max="2"' in khoi
    assert "readonly" in khoi


def test_phan_hoi_cua_luot_cu_khong_ghi_de_thong_bao():
    """Bấm Dừng xong ~1 giây, request cũ trả về và ô trạng thái nhảy sang XANH
    "THÀNH CÔNG" — ngay sau khi người dùng vừa bảo dừng."""
    code = _code(UI / "js/autoplay.js")
    assert "if (App.state.gcRunId !== runId) return;" in code


def test_khong_con_handler_cua_nut_da_xoa():
    """Nút đã xoá nhưng handler còn lại là cái bẫy: người sửa sau thêm lại nút
    với đúng id, tin rằng handler đã sẵn sàng."""
    code = _code(UI / "js/actions.js")
    for ten in ("btnGcCreateRoom", "btnGcFindId", "btnReconnect",
                "btnModePhom", "btnModeMauBinh", "gcTargetRoomId"):
        assert f'"{ten}"' not in code, f"handler mồ côi còn lại: {ten}"


# ---------- biến chết gây hiểu nhầm ----------

def test_khong_con_cong_tac_dung_gia():
    """Đọc code thấy `_GOM_BAN_STOP = True` là tưởng có công tắc tắt toàn cục
    rồi bỏ qua việc kiểm `stop_epoch` — đúng loại hiểu nhầm đã đẻ ra mấy lỗ
    hổng vừa vá."""
    code = _code(BE / "controllers/auto_flow_controller/routes_basic.py")
    assert "_GOM_BAN_STOP" not in code
    assert "_GOM_BAN_ACTIVE_RUN_ID" not in code


def test_khong_con_bien_profile_b_chet():
    code = _code(BE / "controllers/auto_flow_controller/matching.py")
    assert "profile_b = profiles_input[1]" not in code

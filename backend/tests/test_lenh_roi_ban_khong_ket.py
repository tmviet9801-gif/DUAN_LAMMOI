"""Lệnh rời bàn: không kẹt, không trùng, không rời giữa ván.

`__leave_after_round` được ĐẶT ở hai chỗ (cmd 250 hoãn lệnh rời, và exec_leave
khi gặp giữa ván) nhưng trước đây chỉ được XOÁ ở hai chỗ trong cùng luồng.
Không có ở `clearRunConfig`, cmd 203, hay khối reset đầu vòng bên Python — nên
cờ sống sót qua nhiều lượt chạy rồi kích hoạt một lệnh rời bàn oan.

Nhánh thực thi nó cũng không có cổng kích hoạt: lượt chạy đã tắt, người dùng
đang chơi tay, nick vẫn tự rời bàn. Đúng lỗi mà `dong_luot_chay` được viết ra
để chặn.
"""
import re
from pathlib import Path

BE = Path(__file__).parents[1]
EXT = BE / "extension" / "content_main.js"
MATCHING = BE / "controllers" / "auto_flow_controller" / "matching.py"


def _code(p: Path) -> str:
    """Chỉ lấy dòng CODE, bỏ cả khối `/** */`.

    Chú thích mô tả lỗi cũ chứa đúng chuỗi đang cấm — bẫy này đã vấp nhiều lần.
    """
    src = p.read_text(encoding="utf-8")
    if p.suffix != ".py":
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    mo = "#" if p.suffix == ".py" else "//"
    return "\n".join(d for d in src.splitlines() if not d.strip().startswith(mo))


def _khoi(code: str, moc: str, dai: int = 4000) -> str:
    return code[code.index(moc):][:dai]


def _khoi_252() -> str:
    """cmd 252 là khối `if (p.cmd === ...)` cuối cùng — cắt theo độ dài."""
    return _khoi(_code(EXT), "if (p.cmd === 252)", 4000)


# ---------- B: cờ không được kẹt ----------

def test_clearRunConfig_xoa_lenh_hoan():
    than = _khoi(_code(EXT), "function clearRunConfig()", 900)
    assert "__leave_after_round = false" in than


def test_cmd_203_xoa_lenh_hoan():
    than = _khoi(_code(EXT), "if (p.cmd === 203)", 1200)
    assert "__leave_after_round = false" in than


def test_reset_dau_vong_ben_python_cung_xoa():
    """`leave_then_join` gửi gói rời thẳng qua socket, không đi qua exec_leave,
    nên cờ không bao giờ được xoá nếu Python không tự dọn."""
    code = _code(MATCHING)
    assert code.count("window.__leave_after_round = false") == 2, \
        "phải dọn trên cả trang chính lẫn từng trang phụ"


def test_RESET_STATE_KHONG_dung_toi_lenh_hoan():
    """Khoá mặt KHÔNG: `RESET_STATE` là lệnh phát toàn cục (broadcast). Xoá cờ
    ở đó là huỷ lệnh rời đã hoãn của một cặp khác đang giữa ván."""
    than = _khoi(_code(EXT), 'action === "RESET_STATE"', 1500)
    assert "__leave_after_round" not in than


def test_nhanh_thuc_thi_lenh_hoan_co_cong_kich_hoat():
    khoi = _khoi_252()
    i = khoi.index("if (G.__leave_after_round)")
    sau = khoi[i:i + 700]
    j = sau.index("exec_leave(true)")
    assert "isAutoEngaged()" in sau[:j], \
        "lượt chạy đã tắt mà vẫn tự rời bàn -> đúng lỗi dong_luot_chay chặn"


# ---------- C: không hẹn hai lệnh rời chồng nhau ----------

def test_cmd_252_khong_hen_hai_lenh_roi():
    khoi = _khoi_252()
    assert "const coLenhHoan" in khoi
    # phải chốt TRƯỚC khi nhánh lệnh hoãn xoá cờ
    assert khoi.index("const coLenhHoan") < khoi.index("G.__leave_after_round = false")
    i = khoi.index("isSubMatchProfile()")
    assert "if (coLenhHoan)" in khoi[i:i + 400]


def test_nhanh_phu_van_khong_buoc_roi_giua_van():
    """Nhánh nick phụ phải gọi `exec_leave()` KHÔNG tham số, để chốt "đang giữa
    ván -> hoãn" còn hiệu lực. Bỏ giữa ván là mất cược."""
    khoi = _khoi_252()
    i = khoi.index("isSubMatchProfile()")
    nhanh = khoi[i:i + 1800]
    assert "G.__autotool_exec_leave()" in nhanh
    assert "exec_leave(true)" not in nhanh, "nhánh phụ không được ép rời giữa ván"


def test_bao_roi_ban_chua_xong_dung_khang_dinh_duong():
    """`__autotool_is_inside_table` là khẳng định ÂM, trả true chỉ vì
    `__room_players.length > 0` — mảng đó chỉ được dọn khi có cmd 203."""
    khoi = _khoi_252()
    assert "__autotool_is_in_tldl_lobby" in khoi
    assert "AUTOTOOL_AUTO_LEAVING" in khoi
    assert "__autotool_is_inside_table" not in khoi


def test_khong_goi_lai_exec_leave_trong_timer_xac_minh():
    """Cấm retry click mù: mỗi lần `exec_leave` phát ba `dispatchCanvasClick`,
    mà ở sảnh thì góc trên bên trái là nút Back văng ra sảnh chính."""
    khoi = _khoi_252()
    i = khoi.index("G.__leave_verify_timer = setTimeout(")
    than = khoi[i:i + 900]
    assert "exec_leave" not in than


def test_timer_xac_minh_duoc_don_du_ba_cua():
    code = _code(EXT)
    for cua, dai in (("if (p.cmd === 203)", 1400),
                     ('action === "STOP_HUNT"', 1500),
                     ('action === "RESET_STATE"', 1500)):
        assert "__leave_verify_timer" in _khoi(code, cua, dai), f"quên dọn ở {cua}"


# ---------- D: cưỡng chế vai trò ----------

def test_xac_minh_vai_tro_sau_khi_gan():
    """Ba khối gán vai trò đều bọc try/except nuốt lỗi và không đọc lại. Từ khi
    extension bỏ đoán theo tên, gán hụt một trang là trang đó ngồi lì im lặng."""
    code = _code(MATCHING)
    assert "window.__AUTOTOOL_MATCH_ROLE || null" in code
    assert code.index("window.__AUTOTOOL_ROLE = 'dump'") < \
        code.index("window.__AUTOTOOL_MATCH_ROLE || null"), "phải đọc lại SAU khi gán"
    i = code.index("window.__AUTOTOOL_MATCH_ROLE || null")
    assert 'dong_luot_chay(pages, "không đặt được vai trò")' in code[i:i + 900]


def test_moi_duong_thoat_van_dong_luot_chay():
    code = _code(MATCHING)
    # 4 đường ra: vai trò, không gom được bàn, không bắt đầu được ván, hết ván.
    # Đường "không vào được sảnh" đã bỏ — nay lặp lại thay vì thoát.
    assert code.count("await dong_luot_chay(pages") >= 4

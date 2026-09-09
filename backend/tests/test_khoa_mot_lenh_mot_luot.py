"""Một lượt chỉ được gửi ĐÚNG MỘT lệnh (cmd 253 hoặc 254).

Hai đường cùng dẫn tới `handleAutoTurn`: khung cmd 250 báo "tôi đi trước" và
khung cmd 251 báo chuyển lượt. Server phát lại 251 sau khi kết nối lại cũng vào
đúng đường đó. Nếu nước đã hẹn giờ chạy sau khi lượt đã đổi thì lệnh rơi vào
lượt của người khác.

Công cụ Sunwin chặn bằng khoảng cách thời gian cố định (250ms). Ở đây khoá theo
SỐ THỨ TỰ LƯỢT: hai người bỏ lượt liên tiếp thật sự chỉ cách nhau vài chục
mili-giây, một bộ đếm thời gian sẽ nuốt mất nước hợp lệ.
"""
import re
from pathlib import Path

EXT = Path(__file__).parents[1] / "extension" / "content_main.js"


def _code():
    """Chỉ lấy dòng CODE. Chú thích mô tả lỗi cũ chứa đúng chuỗi đang cấm."""
    return "\n".join(d for d in EXT.read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith("//"))


def _than_setTimeout() -> str:
    """Thân callback hẹn giờ trong `handleAutoTurn`."""
    code = _code()
    i = code.index("function handleAutoTurn()")
    j = code.index("G.__auto_turn_timer = setTimeout(", i)
    return code[j:code.index("}, delay);", j)]


def _phai_thoat_ngay(than: str, dieu_kien: str) -> None:
    """Sau `dieu_kien` phải là `return;`, và phải tới TRƯỚC khi tính nước đi.

    Không dò cặp ngoặc vì `}` còn nằm trong chuỗi mẫu `${seq}` của log.
    """
    sau = than[than.index(dieu_kien):]
    assert "return;" in sau, f"{dieu_kien}: phải thoát hẳn, không chỉ ghi log"
    assert sau.index("return;") < sau.index("findBestPlay"),         f"{dieu_kien}: thoát muộn hơn lúc quyết định nước đi"


# ---------- bộ đếm lượt ----------

def test_moi_cho_vao_luot_deu_tang_bo_dem():
    """Gọi thẳng `handleAutoTurn` thì bộ đếm không tăng -> khoá vô hiệu.

    Trừ đúng một chỗ: lời gọi bên trong chính `moiLuotCuaToi`.
    """
    code = _code()
    assert "function moiLuotCuaToi()" in code
    i = code.index("function moiLuotCuaToi()")
    ngoai = code[:i] + code[code.index("function handleAutoTurn()"):]
    goi = re.findall(r"^\s*(moiLuotCuaToi|handleAutoTurn)\(\);", ngoai, re.M)
    assert goi, "không tìm thấy chỗ gọi vào lượt"
    assert "handleAutoTurn" not in goi, (
        f"còn chỗ gọi thẳng handleAutoTurn, bộ đếm lượt sẽ không tăng: {goi}")


def test_bo_dem_tang_truoc_khi_hen_gio():
    than = _code().split("function moiLuotCuaToi()", 1)[1][:220]
    assert "G.__turn_seq = (G.__turn_seq || 0) + 1;" in than
    assert than.index("G.__turn_seq") < than.index("handleAutoTurn()"), \
        "phải tăng bộ đếm TRƯỚC khi hẹn giờ, không thì callback chốt số cũ"


# ---------- chốt số lượt lúc hẹn, kiểm lúc bắn ----------

def test_chot_so_luot_luc_hen_gio():
    code = _code()
    i = code.index("function handleAutoTurn()")
    truoc = code[i:code.index("G.__auto_turn_timer = setTimeout(", i)]
    assert "const seq = G.__turn_seq || 0;" in truoc, \
        "phải chốt số lượt NGOÀI callback, đọc trong callback là đọc giá trị mới"


def test_luot_da_doi_thi_khong_ban():
    than = _than_setTimeout()
    assert "(G.__turn_seq || 0) !== seq" in than
    _phai_thoat_ngay(than, "(G.__turn_seq || 0) !== seq")


def test_da_gui_cho_luot_nay_thi_khong_gui_lan_hai():
    than = _than_setTimeout()
    assert "G.__turn_da_gui === seq" in than
    _phai_thoat_ngay(than, "G.__turn_da_gui === seq")


def test_hai_lan_kiem_deu_dung_truoc_khi_quyet_dinh():
    """Kiểm sau khi đã gọi `findBestPlay` thì vẫn tốn một vòng tính, nhưng tệ
    hơn là dễ bị chèn thêm lệnh gửi vào giữa."""
    than = _than_setTimeout()
    assert than.index("G.__turn_seq || 0) !== seq") < than.index("findBestPlay")
    assert than.index("G.__turn_da_gui === seq") < than.index("findBestPlay")


# ---------- đánh dấu trước khi gửi ----------

def test_danh_dau_truoc_moi_lenh_gui_di():
    """Đánh dấu SAU khi gửi thì giữa hai câu lệnh vẫn còn khe cho lần gửi thứ
    hai (exec_* có `setTimeout` gửi lại bên trong)."""
    than = _than_setTimeout()
    for lenh in ("G.__autotool_exec_play(play);", "G.__autotool_exec_pass();"):
        assert lenh in than
        truoc = than[:than.index(lenh)]
        assert truoc.rstrip().endswith("G.__turn_da_gui = seq;"), \
            f"thiếu đánh dấu ngay trước {lenh}"


def test_ca_danh_va_bo_luot_deu_bi_khoa():
    than = _than_setTimeout()
    assert than.count("G.__turn_da_gui = seq;") == 2, \
        "bỏ lượt cũng là một lệnh gửi đi, phải khoá như đánh bài"


# ---------- không quay lại bộ đếm thời gian ----------

def test_khong_dung_khoang_cach_thoi_gian_co_dinh():
    """Chống hồi quy sang cách của Sunwin: `Date.now() - lanGuiCuoi < 250`
    nuốt mất nước bỏ lượt hợp lệ của hai người liên tiếp."""
    code = _code()
    assert not re.search(r"Date\.now\(\)\s*-\s*\w*[Ll]ast\w*\s*<", code)
    assert not re.search(r"Date\.now\(\)\s*-\s*\w*[Gg]ui\w*\s*<", code)

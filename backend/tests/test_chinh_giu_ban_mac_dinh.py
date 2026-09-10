"""Sau khi xả: nick phụ out, Account CHÍNH ở lại giữ bàn — theo MẶC ĐỊNH.

Lỗi thật (10/09/2026): ván xả chạy đúng, phụ out đúng, rồi log ghi
    "auto_leave_after bật -> đưa Account chính về sảnh."
và cả hai profile cùng về sảnh, bàn bỏ trống. Không ai bật gì cả: ô
"Tự Out sau khi xả" trên giao diện TÍCH SẴN, `autoplay.js` và `context.py`
đều mặc định True khi thiếu. Nguyên tắc của luồng gom bàn là phải có một
profile ở lại phòng cho khách ngoài, nên mặc định phải là TẮT ở cả ba lớp.
"""
import re
from pathlib import Path

HIT = Path(__file__).parents[2]
INDEX = HIT / "app" / "renderer" / "index.html"
AUTOPLAY = HIT / "app" / "renderer" / "js" / "autoplay.js"
CONTEXT = HIT / "backend" / "controllers" / "auto_flow_controller" / "context.py"
MATCHING = HIT / "backend" / "controllers" / "auto_flow_controller" / "matching.py"


def _code(p: Path) -> str:
    return "\n".join(d for d in p.read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith(("#", "//")))


def test_backend_mac_dinh_khong_out_chinh():
    code = _code(CONTEXT)
    assert 'body.get("auto_leave_after", False)' in code
    assert 'body.get("auto_leave_after", True)' not in code


def test_o_tren_giao_dien_khong_tich_san():
    html = INDEX.read_text(encoding="utf-8")
    the = re.search(r'<input[^>]*id="gcAutoLeaveAfter"[^>]*>', html)
    assert the, "mất ô gcAutoLeaveAfter"
    assert "checked" not in the.group(0), "ô 'Account chính cũng out' vẫn tích sẵn"


def test_nhan_o_noi_ro_la_account_chinh():
    """"Tự Out sau khi xả" đọc như tuỳ chọn chung, trong khi phụ luôn out; ô này
    chỉ quyết Account chính. Nhãn phải nói đúng thứ nó điều khiển."""
    html = INDEX.read_text(encoding="utf-8")
    i = html.index('id="gcAutoLeaveAfter"')
    assert "Account chính" in html[i:i + 200]


def test_giao_dien_thieu_o_thi_cung_khong_ngam_out():
    code = _code(AUTOPLAY)
    dong = next(d for d in code.splitlines() if "const autoLeaveAfter" in d)
    assert dong.rstrip().endswith(": false;"), dong


def test_chinh_chi_out_khi_bat_tuy_chon():
    """Controller: lệnh rời cho Account chính sau ván phải nằm dưới `if auto_leave_after:`."""
    code = _code(MATCHING)
    i = code.index("Ván xả bài hoàn tất")
    khoi = code[i:i + 4000]
    j = khoi.index("if auto_leave_after:")
    assert "_do_leave_room(first_page" in khoi[j:j + 400]
    # và trước cái if đó không có lệnh rời nào cho Account chính
    assert "_do_leave_room(first_page" not in khoi[:j]

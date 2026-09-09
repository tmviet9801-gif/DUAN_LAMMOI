"""Vai trò ANCHOR/SUB chỉ được đọc từ giá trị controller đặt — không đoán theo tên.

"Ai rời bàn trước sau khi xả" ở dự án này KHÔNG phải bầu chọn phân tán như công
cụ Sunwin (máy nào giữ lượt lúc mặt bàn trống thì tự nhận). Bên mình có trọng
tài tập trung: một tiến trình Python đặt `__AUTOTOOL_MATCH_ROLE` trước ván.

Lỗ hổng thật nằm ở ĐƯỜNG DỰ PHÒNG cũ, đoán theo hình dạng tên profile:
  - `includes("1")` là chính, `includes("2")` là phụ
  - tên `Account 12` thoả CẢ HAI  -> vừa chính vừa phụ
  - tên không có chữ số           -> KHÔNG AI là phụ -> không ai rời bàn
Đúng hai triệu chứng mà cách của Sunwin cũng mắc.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

BE = Path(__file__).parents[1]
MODULE = BE / "extension" / "vai_tro_ban.js"
EXT = BE / "extension" / "content_main.js"
MANIFEST = BE / "extension" / "manifest.json"
CONTEXT = BE / "controllers" / "auto_flow_controller" / "context.py"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="cần node để chạy vai_tro_ban.js")


def run_js(body: str):
    script = f"const M = require({json.dumps(str(MODULE))});\n{body}"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                         timeout=60, encoding="utf-8")
    assert out.returncode == 0, f"node lỗi:\n{out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


def _code(p: Path) -> str:
    """Chỉ lấy dòng CODE.

    Phải bỏ CẢ khối `/** ... */` chứ không chỉ dòng `//`: chú thích mô tả lỗi cũ
    chứa đúng chuỗi đang cấm, và chính test này đã vấp lần đầu vì thế.
    """
    src = p.read_text(encoding="utf-8")
    if p.suffix != ".py":
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    mo = "#" if p.suffix == ".py" else "//"
    return "\n".join(d for d in src.splitlines()
                     if not d.strip().startswith(mo))


def _than(ten_ham: str, den: str) -> str:
    code = _code(EXT)
    i = code.index(ten_ham)
    return code[i:code.index(den, i + len(ten_ham))]


# ---------- module thuần ----------

def test_lavaiphu_chi_nhan_dung_chuoi_sub():
    res = run_js("""
      const vao = ["sub", " SUB ", "Sub", "anchor", "", "dump", "winner", "sub2",
                   "Account 2", "nicktestxxabai2"];
      const ra = vao.map((v) => M.laVaiPhu(v));
      ra.push(M.laVaiPhu(null), M.laVaiPhu(undefined), M.laVaiPhu(0),
              M.laVaiPhu(2), M.laVaiPhu({}), M.laVaiPhu(["sub"]));
      console.log(JSON.stringify(ra));
    """)
    assert res == [True, True, True] + [False] * 13, res


def test_lavaichinh_vai_tro_thang_co_khoi_xuong():
    """Python đã nói `sub` thì cờ `__is_hunt_initiator` KHÔNG được lật ngược."""
    res = run_js("""
      console.log(JSON.stringify([
        M.laVaiChinh("anchor", false),
        M.laVaiChinh("sub", true),
        M.laVaiChinh(null, true),
        M.laVaiChinh(null, false),
        M.laVaiChinh("", 0),
        M.laVaiChinh("Account 12", true),
        M.laVaiChinh("Account 12", false),
      ]));
    """)
    assert res == [True, False, True, False, False, True, False]


def test_khong_vai_tro_nao_thoa_ca_hai():
    """Lỗi cũ: `Account 12` chứa cả "1" lẫn "2" nên vừa là chính vừa là phụ."""
    res = run_js("""
      const vao = ["anchor", "sub", "", null, "Account 12", "Account 1", "Account 2"];
      const ca_hai = vao.filter((v) => M.laVaiPhu(v) && M.laVaiChinh(v, true));
      console.log(JSON.stringify(ca_hai));
    """)
    assert res == [], f"còn giá trị thoả cả hai vai: {res}"


def test_module_la_thuan():
    """Không đụng môi trường trình duyệt -> nạp và kiểm thử được bằng node."""
    code = _code(MODULE)
    for cam in ("document", "localStorage", "Date.now", "cc.", "fetch("):
        assert cam not in code, f"module không được đụng `{cam}`"
    # `window` chỉ được phép qua tham số root, không truy cập trực tiếp
    assert not re.search(r"\bwindow\s*\.", code)
    res = run_js('console.log(JSON.stringify([M.laVaiPhu("sub"), M.laVaiPhu("sub")]))')
    assert res == [True, True]


# ---------- nối vào content_main.js ----------

def test_isSubMatchProfile_khong_con_doan_theo_ten():
    than = _than("function isSubMatchProfile()", "function isAnchorMatchProfile()")
    for cam in ("getProfileName", 'includes("2")', 'includes("sub")',
                'includes("phu")', 'includes("xabai2")', 'includes("dump")',
                "getMyRole"):
        assert cam not in than, f"còn đoán theo tên: `{cam}`"
    assert "M.laVaiPhu(G.__AUTOTOOL_MATCH_ROLE)" in than


def test_isAnchorMatchProfile_khong_con_doan_theo_ten():
    than = _than("function isAnchorMatchProfile()", "function findBestPlay")
    assert 'includes("1")' not in than, "còn đoán theo tên"
    assert "getProfileName" not in than
    assert "__is_hunt_initiator" in than, "mất đường dự phòng hợp lệ do Python đặt"


def test_du_phong_khi_thieu_module_cung_luat():
    """Thiếu file thì rơi về luật MỚI, không được rơi về đoán tên."""
    for ten, den in (("function isSubMatchProfile()", "function isAnchorMatchProfile()"),
                     ("function isAnchorMatchProfile()", "function findBestPlay")):
        than = _than(ten, den)
        assert '=== "sub"' in than, f"{ten}: dự phòng phải cùng luật"
        assert "getProfileName" not in than


def test_vai_tro_ban_nap_truoc_content_main():
    """Khoá THỨ TỰ, không khoá cả danh sách — bẫy đã vấp ở test_card_logic.py."""
    js = json.loads(MANIFEST.read_text(encoding="utf-8"))["content_scripts"][0]["js"]
    assert "vai_tro_ban.js" in js and "content_main.js" in js
    assert js.index("vai_tro_ban.js") < js.index("content_main.js"), js

    src = _code(CONTEXT)
    m = re.search(r"for fname in \(([^)]*)\)", src)
    assert m, "không tìm thấy tuple nạp script trong context.py"
    thu_tu = re.findall(r'"([^"]+\.js)"', m.group(1))
    assert "vai_tro_ban.js" in thu_tu, f"quên đăng ký bên Python: {thu_tu}"
    assert thu_tu.index("vai_tro_ban.js") < thu_tu.index("content_main.js"), thu_tu


def test_giu_nguyen_dong_dieu_kien_nhanh_phu():
    """`test_gom_ban_fixes.py` khoá nguyên văn dòng này; đổi là vỡ test đó."""
    src = EXT.read_text(encoding="utf-8")
    assert "if (isAutoEngaged() && isSubMatchProfile()) {" in src


def test_cong_kich_hoat_van_dung_truoc_trong_nhanh_phu():
    """Bỏ `isAutoEngaged()` là tái tạo đúng lỗi mà `dong_luot_chay` chặn:
    lượt chạy đã tắt, người dùng chơi tay, nick vẫn tự rời bàn."""
    code = _code(EXT)
    i = code.index("if (p.cmd === 252)")
    # cmd 252 là khối `if (p.cmd === ...)` CUỐI CÙNG, không có khối sau để cắt.
    khoi = code[i:i + 4000]
    j = khoi.index("isSubMatchProfile()")
    truoc = khoi[:j]
    assert "isAutoEngaged()" in truoc
    assert truoc.rindex("isAutoEngaged()") > truoc.rindex("if ("), \
        "isAutoEngaged() phải nằm trên CÙNG điều kiện với isSubMatchProfile()"

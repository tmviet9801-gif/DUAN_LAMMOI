"""Xả bài của nick PHỤ với ĐÚNG hai tay bài đã chia trong log ngày 10/09/2026.

    Account 01 (chính): [12,16,24,27,32,37,39,46,50,51,0,4,5]
        = 4♠ 5♠ 7♠ 7♥ 9♠ 10♣ 10♥ Q♦ K♦ K♥ A♠ 2♠ 2♣
    Account 02 (phụ):   [8,15,18,21,29,30,31,34,35,36,41,1,2]
        = 3♠ 4♥ 5♦ 6♣ 8♣ 8♦ 8♥ 9♦ 9♥ 10♠ J♣ A♣ A♦

Người dùng thấy phụ "chưa đến số lá để bỏ nhưng vẫn bỏ". Phần logic chọn
nước (card_logic.js) với hai tay này phải RA BÀI — nếu nó ra bài thì lý do
phụ bỏ nằm ở cổng kích hoạt, không phải ở luật chọn nước.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

CARD_LOGIC = Path(__file__).parents[1] / "extension" / "card_logic.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="cần node để chạy card_logic.js")

CHINH = [12, 16, 24, 27, 32, 37, 39, 46, 50, 51, 0, 4, 5]
PHU = [8, 15, 18, 21, 29, 30, 31, 34, 35, 36, 41, 1, 2]
# 4 lá thấp nhất của phụ = phần giữ để mồi: 3♠ 4♥ 5♦ 6♣
PHAN_GIU = {8, 15, 18, 21}


def run_js(body: str):
    script = f"const C = require({json.dumps(str(CARD_LOGIC))});\n{body}"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                         timeout=300, encoding="utf-8")
    assert out.returncode == 0, f"node lỗi:\n{out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


def bac(c):
    """Bậc theo luật Tiến Lên: 3..K = 3..13, A = 14, Heo = 15."""
    r = c // 4
    return r + 1 if r >= 2 else (14 if r == 0 else 15)


def test_chinh_dan_4_bich_phu_phai_de_khong_bo():
    """Nước đầu tiên trong log: chính ra 4♠ (id 12). Phụ còn 13 lá, dư xa phần giữ."""
    res = run_js(f"console.log(JSON.stringify(C.chooseDumpBeat({PHU}, [12], undefined, {CHINH})))")
    assert res, "phụ có 9 lá đè được 4♠ ngoài phần giữ mà lại bỏ"
    assert len(res) == 1
    assert res[0] not in PHAN_GIU, "không được xé phần giữ để mồi"
    assert res[0] in PHU


def test_chinh_ra_doi_7_phu_de_bang_doi():
    ban = [24, 27]   # 7♠ 7♥
    res = run_js(f"console.log(JSON.stringify(C.chooseDumpBeat({PHU}, {ban}, undefined, {CHINH})))")
    assert res and len(res) == 2, "phụ có đôi 8 / đôi 9 / đôi A mà lại bỏ"
    assert bac(res[0]) == bac(res[1]), "phải là một đôi thật"
    assert bac(res[0]) > bac(24)


def test_phu_uu_tien_la_ma_chinh_con_de_lai_duoc():
    """Giữ nhịp tiếp sức: chính còn 2♠ 2♣ thì phụ xả A được (chính đè lại bằng Heo)."""
    res = run_js(f"console.log(JSON.stringify(C.chooseDumpBeat({PHU}, [12], undefined, {CHINH})))")
    ok = run_js(f"console.log(JSON.stringify(C.canPartnerBeat({res}, {CHINH})))")
    assert ok is True


def test_chi_con_phan_giu_moi_bo():
    """Đúng nghĩa 'đến số lá để bỏ': chỉ khi còn đúng 4 lá thấp mồi mới thôi đè."""
    res = run_js(f"console.log(JSON.stringify(C.chooseDumpBeat({sorted(PHAN_GIU)}, [12], undefined, {CHINH})))")
    assert res is None


def test_luot_tu_do_phu_van_ra_bai():
    res = run_js(f"console.log(JSON.stringify(C.chooseDumpDischarge({PHU}, undefined, {CHINH})))")
    assert res, "lượt tự do mà phụ không ra bài"
    assert all(c not in PHAN_GIU for c in res)

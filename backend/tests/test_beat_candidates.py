"""Sinh ứng viên ĐÈ: phải ĐỦ, không thừa, và xếp tăng dần.

Lỗi gốc: `findCombinations` trong content_main.js dựng sảnh bằng `valMap[v][0]`
— lá chất THẤP NHẤT của mỗi bậc. Lá chốt sảnh vì thế luôn là chất thấp nhất,
nên có nước đè hợp lệ mà nó báo không đè được.

Kiểm bằng VÉT CẠN làm oracle độc lập, đúng cách đã dùng cho phân rã tối ưu.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

CARD_LOGIC = Path(__file__).parents[1] / "extension" / "card_logic.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="cần node để chạy card_logic.js")


def run_js(body: str):
    script = f"const C = require({json.dumps(str(CARD_LOGIC))});\n{body}"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                         timeout=300, encoding="utf-8")
    assert out.returncode == 0, f"node lỗi:\n{out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


# id = rankIdx*4 + suit; rankIdx 0->A(14), 1->Heo(15), 2..12 -> 3..K
def card(val: int, suit: int) -> int:
    idx = val - 1 if 3 <= val <= 13 else (0 if val == 14 else 1)
    return idx * 4 + suit


BICH, CHUON, RO, CO = 0, 1, 2, 3


# ---------- ca tái hiện được ----------

def test_sanh_doi_chat_o_la_dinh_moi_de_duoc():
    """Bàn ra 3♠ 4♠ 5♦; tay có 3♣ 4♣ 5♣ 5♥.

    Dựng theo chất thấp nhất -> [3♣ 4♣ 5♣], chốt 5♣ < 5♦ -> báo PASS.
    Nhưng [3♣ 4♣ 5♥] đè được thật.
    """
    ban = [card(3, BICH), card(4, BICH), card(5, RO)]
    tay = [card(3, CHUON), card(4, CHUON), card(5, CHUON), card(5, CO)]
    res = run_js(f"console.log(JSON.stringify(C.beatCandidates({tay}, {ban})))")
    assert res, "bỏ sót nước đè hợp lệ"
    assert res[0] == [card(3, CHUON), card(4, CHUON), card(5, CO)]


def test_khong_sinh_nuoc_khong_de_duoc():
    ban = [card(10, CO)]
    tay = [card(3, BICH), card(4, BICH), card(5, BICH)]
    res = run_js(f"console.log(JSON.stringify(C.beatCandidates({tay}, {ban})))")
    assert res == []


def test_xep_tang_dan_theo_la_cao_nhat():
    """Ngược chiều với công cụ Sunwin (nó xếp giảm dần, luôn đè bằng nước to
    nhất). Đè bằng nước nhỏ nhất giữ lại quân mạnh để còn giành quyền dẫn."""
    ban = [card(4, BICH)]
    tay = [card(9, CO), card(5, BICH), card(7, RO)]
    res = run_js(f"console.log(JSON.stringify(C.beatCandidates({tay}, {ban})))")
    assert [r[0] for r in res] == [card(5, BICH), card(7, RO), card(9, CO)]


def test_tu_quy_chat_heo_don():
    heo = card(15, BICH)
    tay = [card(6, s) for s in (BICH, CHUON, RO, CO)]
    res = run_js(f"console.log(JSON.stringify(C.beatCandidates({tay}, {[heo]})))")
    assert any(len(g) == 4 for g in res), "thiếu nước tứ quý chặt Heo đơn"


def test_tu_quy_de_tu_quy():
    """Sun bỏ hẳn tứ quý; bên mình giữ — đây là chỗ KHÔNG chuyển sang Sun."""
    ban = [card(5, s) for s in (BICH, CHUON, RO, CO)]
    tay = [card(9, s) for s in (BICH, CHUON, RO, CO)]
    res = run_js(f"console.log(JSON.stringify(C.beatCandidates({tay}, {ban})))")
    assert res and len(res[0]) == 4


# ---------- vét cạn làm oracle ----------

VET_CAN = """
function bocBai(seed) {
  let s = seed >>> 0;
  const rnd = () => ((s = (1103515245 * s + 12345) >>> 0) / 4294967296);
  const b = Array.from({length: 52}, (_, i) => i);
  for (let i = 51; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; }
  return b;
}
// Oracle: MỌI tập con của tay bài cùng độ dài với bàn, lọc bằng canBeat.
function vetCan(tay, ban) {
  const n = ban.length, ra = [];
  const cur = [];
  (function di(bd) {
    if (cur.length === n) { if (C.canBeat(cur.slice(), ban)) ra.push(cur.slice()); return; }
    for (let i = bd; i < tay.length; i++) { cur.push(tay[i]); di(i + 1); cur.pop(); }
  })(0);
  // tứ quý chặt Heo đơn: độ dài khác nhau, xét riêng
  if (n === 1) {
    const cur4 = [];
    (function di4(bd) {
      if (cur4.length === 4) { if (C.canBeat(cur4.slice(), ban)) ra.push(cur4.slice()); return; }
      for (let i = bd; i < tay.length; i++) { cur4.push(tay[i]); di4(i + 1); cur4.pop(); }
    })(0);
  }
  return ra;
}
"""


def test_vet_can_khong_bo_sot_khong_sinh_thua():
    """Oracle độc lập: `beatCandidates` tìm được nước đè KHI VÀ CHỈ KHI vét cạn
    tìm được, và mọi nước nó sinh ra đều đè được thật."""
    res = run_js(VET_CAN + """
      let lech = 0, coSanh = 0, mau = null;
      for (let seed = 1; seed <= 4000; seed++) {
        const b = bocBai(seed);
        const tay = b.slice(0, 11);
        const conLai = b.slice(11);
        // bàn: thử vài dạng
        const dang = [1, 2, 3];
        for (const n of dang) {
          let ban = null;
          if (n === 1) ban = [conLai[0]];
          else {
            const theo = {};
            for (const c of conLai) { const v = C.getCardVal(c); (theo[v] = theo[v] || []).push(c); }
            const k = Object.keys(theo).find((v) => theo[v].length >= n);
            if (k) ban = theo[k].slice(0, n);
          }
          if (!ban) continue;
          const co = C.beatCandidates(tay, ban).length > 0;
          const vc = vetCan(tay, ban).length > 0;
          if (co !== vc) { lech++; if (!mau) mau = {tay, ban, co, vc}; }
        }
        // bàn là sảnh 3 lá lấy từ phần còn lại
        const s3 = (() => {
          const vals = [...new Set(conLai.map(C.getCardVal))].filter(v => v < 15).sort((a,b)=>a-b);
          for (let i = 0; i + 3 <= vals.length; i++) {
            if (vals[i+1] === vals[i]+1 && vals[i+2] === vals[i]+2) {
              return [vals[i], vals[i+1], vals[i+2]].map(v => conLai.find(c => C.getCardVal(c) === v));
            }
          }
          return null;
        })();
        if (s3) {
          coSanh++;
          const co = C.beatCandidates(tay, s3).length > 0;
          const vc = vetCan(tay, s3).length > 0;
          if (co !== vc) { lech++; if (!mau) mau = {tay, ban: s3, co, vc}; }
        }
      }
      console.log(JSON.stringify({lech, coSanh, mau}));
    """)
    assert res["lech"] == 0, f"lệch với vét cạn: {res['mau']}"
    assert res["coSanh"] > 100, "mẫu sảnh quá ít để kết luận"


def test_moi_ung_vien_deu_de_duoc_that():
    res = run_js(VET_CAN + """
      let sai = 0;
      for (let seed = 1; seed <= 3000; seed++) {
        const b = bocBai(seed);
        const tay = b.slice(0, 12), conLai = b.slice(12);
        const ban = [conLai[0]];
        for (const g of C.beatCandidates(tay, ban)) {
          if (!C.canBeat(g, ban)) sai++;
          if (!g.every((c) => tay.includes(c))) sai++;
        }
      }
      console.log(JSON.stringify({sai}));
    """)
    assert res["sai"] == 0


# ---------- chooseWinnerBeat ----------

def test_uu_tien_nuoc_khong_ai_chan_lai_duoc():
    """Đè xong mà bị đè tiếp là mất đúng thứ đang cần giành — quyền dẫn.

    Kiểm TÍNH CHẤT, không kiểm lá cụ thể: một con Heo đơn KHÔNG phải nước an
    toàn vì tứ quý vẫn chặt được nó — kỳ vọng ban đầu của tôi sai ở chỗ đó.
    """
    res = run_js("""
      function bocBai(seed) {
        let s = seed >>> 0;
        const rnd = () => ((s = (1103515245 * s + 12345) >>> 0) / 4294967296);
        const b = Array.from({length: 52}, (_, i) => i);
        for (let i = 51; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; }
        return b;
      }
      let saiChon = 0, coCoHoi = 0;
      for (let seed = 1; seed <= 3000; seed++) {
        const b = bocBai(seed);
        const tay = b.slice(0, 6);
        const ban = [b[6]];
        const daRa = b.slice(7, 42);            // ra nhiều -> tập ẩn hẹp
        const cands = C.beatCandidates(tay, ban);
        if (!cands.length) continue;
        const unseen = C.unseenCards(tay, daRa);
        const antoan = cands.filter((c) => !C.canAnyoneBeat(c, unseen));
        const chon = C.chooseWinnerBeat(tay, ban, daRa);
        if (antoan.length) {
          coCoHoi++;
          const khop = antoan.some((a) => JSON.stringify(a) === JSON.stringify(chon));
          if (!khop) saiChon++;
        }
      }
      console.log(JSON.stringify({saiChon, coCoHoi}));
    """)
    assert res["coCoHoi"] > 50, "không đủ mẫu có nước an toàn"
    assert res["saiChon"] == 0, "có nước không ai chặn được mà lại không chọn"


def test_khong_ai_chan_duoc_thi_lay_nuoc_nho_nhat():
    """Chống hồi quy sang chiều của Sun (luôn đè bằng nước to nhất)."""
    ban = [card(4, BICH)]
    tay = [card(5, BICH), card(9, BICH)]
    res = run_js(f"console.log(JSON.stringify(C.chooseWinnerBeat({tay}, {ban}, [])))")
    assert res == [card(5, BICH)]


def test_khong_de_duoc_thi_tra_null():
    res = run_js(
        f"console.log(JSON.stringify(C.chooseWinnerBeat([{card(3, BICH)}], "
        f"[{card(15, CO)}], [])))")
    assert res is None


# ---------- chooseDumpBeat vẫn giữ phần dự trữ ----------

def test_dump_khong_dung_vao_phan_giu():
    res = run_js("""
      let pham = 0;
      function bocBai(seed) {
        let s = seed >>> 0;
        const rnd = () => ((s = (1103515245 * s + 12345) >>> 0) / 4294967296);
        const b = Array.from({length: 52}, (_, i) => i);
        for (let i = 51; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; }
        return b;
      }
      for (let seed = 1; seed <= 3000; seed++) {
        const b = bocBai(seed);
        const tay = b.slice(0, 10), ban = [b[10]];
        const g = C.chooseDumpBeat(tay, ban, 4, null);
        if (!g) continue;
        const giu = C.sortCards(tay).slice(0, 4);
        if (g.some((c) => giu.includes(c))) pham++;
      }
      console.log(JSON.stringify({pham}));
    """)
    assert res["pham"] == 0, "đè bằng lá nằm trong phần giữ lại"


def test_dump_cung_duoc_vao_sanh_doi_chat():
    """Nick phụ dùng chung nguồn ứng viên nên cũng hết bỏ sót sảnh chất thấp.

    Bàn 3 bích - 4 bích - 5 rô. Tay phụ: bốn lá giữ + 3 chuồn 4 chuồn 5 chuồn
    5 cơ. Bản cũ lọc từ `dischargeCandidates` nên chỉ dựng được [3♣ 4♣ 5♣] và
    báo PASS.
    """
    giu = [card(3, BICH), card(4, RO), card(6, BICH), card(7, BICH)]
    tay = giu + [card(9, CHUON), card(10, CHUON), card(11, CHUON), card(11, CO)]
    ban = [card(9, BICH), card(10, BICH), card(11, RO)]
    res = run_js(f"console.log(JSON.stringify(C.chooseDumpBeat({tay}, {ban}, 4, null)))")
    assert res is not None, "vẫn bỏ sót sảnh đổi chất ở lá đỉnh"
    assert res == [card(9, CHUON), card(10, CHUON), card(11, CO)]


def test_dump_van_xep_nguoc_chieu_voi_nick_chinh():
    """`beatCandidates` xếp tăng dần cho nick chính; phụ phải đảo lại, không thì
    phụ đè bằng lá nhỏ nhất và ôm lá nguy hiểm tới cuối ván."""
    tay = [card(3, BICH), card(4, BICH), card(5, BICH), card(6, BICH),
           card(9, BICH), card(13, BICH)]
    res = run_js(f"console.log(JSON.stringify(C.chooseDumpBeat({tay}, [{card(8, CO)}], 4, null)))")
    assert res == [card(13, BICH)], f"phải tống lá cao trước, nhận được {res}"


# ---------- nối vào content_main.js ----------

CONTENT = Path(__file__).parents[1] / "extension" / "content_main.js"


def _bo_chu_thich(doan: str) -> str:
    """Bỏ dòng chú thích. Chú thích mô tả lỗi cũ chứa đúng chuỗi đang cấm —
    đã vấp đúng bẫy này vài lần."""
    return "\n".join(d for d in doan.splitlines() if not d.strip().startswith("//"))


def _cat(tu: str, den: str) -> str:
    """Cắt đoạn nguồn GỐC (còn chú thích, để định vị được mốc)."""
    raw = CONTENT.read_text(encoding="utf-8")
    i = raw.index(tu)
    return raw[i:raw.index(den, i)]


def _nhanh_de_dong_doi() -> str:
    """Nhánh ĐÈ BÀI ĐỒNG ĐỘI của nick chính (đã bỏ chú thích)."""
    return _bo_chu_thich(_cat("Account 1 (Chính): BẮT BUỘC ĐÈ BÀI ĐỒNG ĐỘI",
                              "// Đánh với khách lạ"))


def _nhanh_khach_la() -> str:
    return _bo_chu_thich(_cat("// Đánh với khách lạ", "\n  }"))


def test_nhanh_de_dong_doi_goi_choose_winner_beat():
    """Nguồn ứng viên phải là card_logic.js, không phải `findCombinations` tại
    chỗ — chính nó là nơi sinh ra lỗ hổng sảnh chất thấp."""
    nhanh = _nhanh_de_dong_doi()
    assert "api.chooseWinnerBeat(myCards, tableCards" in nhanh
    assert nhanh.index("chooseWinnerBeat") < nhanh.index("combs.singles"), \
        "đường dự phòng phải nằm SAU, không được chạy trước"


def test_van_con_duong_du_phong_khi_card_logic_chua_nap():
    """card_logic.js nạp qua manifest; nếu lỡ chưa sẵn sàng thì không được
    đứng im mà bỏ lượt oan."""
    nhanh = _nhanh_de_dong_doi()
    assert 'typeof api.chooseWinnerBeat === "function"' in nhanh
    assert "try {" in nhanh and "catch (e)" in nhanh
    assert "combs.quads[0]" in nhanh, "mất luật tứ quý chặt Heo ở đường dự phòng"


def test_khong_con_tu_dung_findCombinations_o_duong_chinh():
    """Chống hồi quy: quay lại `combs.straights` ở đường chính là mang lỗ hổng
    sảnh chất thấp trở lại."""
    nhanh = _nhanh_de_dong_doi()
    truoc = nhanh[:nhanh.index("chooseWinnerBeat")]
    assert "combs." not in truoc


def test_khong_dung_vao_nhanh_khach_la():
    """Người dùng yêu cầu rõ: CHƯA áp dụng cơ chế của Sunwin cho khách lạ.

    Sunwin từ chối đánh khi bàn có người ngoài; ở dự án này 'khách lạ' cũng là
    tài khoản của chính người dùng nên luật đó không mang sang.
    """
    nhanh = _nhanh_khach_la()
    assert "chooseWinnerBeat" not in nhanh
    assert "banToanDongDoi" not in nhanh
    assert "return cand;" in nhanh, "nhánh khách lạ phải giữ nguyên hành vi cũ"

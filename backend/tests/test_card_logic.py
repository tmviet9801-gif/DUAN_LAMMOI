"""Kiểm thử engine chọn nước (backend/extension/card_logic.js).

Engine hiện tại là bản CHUYỂN TỪ CÔNG CỤ SUNWIN, theo yêu cầu của người dùng
ngày 11/09/2026: "áp dụng lại toàn bộ logic xả bài" và "bỏ phối hợp" giữa hai
nick. Bản trước là engine phối hợp (nick phụ giữ 3-4 lá thấp làm mồi, đếm bài,
phân rã tối ưu số lượt); toàn bộ đã gỡ cùng hai file test riêng của nó
(`test_beat_candidates.py`, `test_phu_xa_bai_tay_that.py`).

Luật phải giữ đúng như Sunwin — mỗi điều dưới đây là một hàm test:
  - lượt tự do: SẢNH -> SÁM -> ĐÔI -> LÁ ĐƠN, trong mỗi loại lấy TO NHẤT;
  - "sảnh to nhất" là sảnh có LÁ ĐỈNH cao nhất, KHÔNG phải sảnh dài nhất;
  - lượt đè: cùng kiểu, đè bằng nước TO NHẤT; không có thì bỏ lượt;
  - KHÔNG có tứ quý / ba đôi thông / chặt Heo;
  - sảnh không chứa Heo, nhưng Át được đứng cuối (J-Q-K-A).

`card_logic.js` thuần tính toán nên nạp và chạy được bằng node — khác
content_main.js vốn là IIFE có patch WebSocket, không chạy ngoài trình duyệt.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXT = Path(__file__).parents[1] / "extension"
CARD_LOGIC = EXT / "card_logic.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="cần node để chạy card_logic.js")


def run_js(body: str):
    """Chạy đoạn JS có sẵn biến `C` = module card_logic, trả JSON đã in ra."""
    script = f"const C = require({json.dumps(str(CARD_LOGIC))});\n{body}"
    out = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=180,
        encoding="utf-8",
    )
    assert out.returncode == 0, f"node lỗi:\n{out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


# id lá = rank_idx*4 + suit; rank_idx 2..12 -> '3'..'K', 0 -> 'A', 1 -> '2'(Heo).
# Chất: 0 Bích < 1 Chuồn < 2 Rô < 3 Cơ.
def card(rank_idx: int, suit: int = 0) -> int:
    return rank_idx * 4 + suit


BA, BON, NAM, SAU, BAY, TAM, CHIN = 2, 3, 4, 5, 6, 7, 8
MUOI, J, Q, K, A, HEO = 9, 10, 11, 12, 0, 1


# ===================== 1. Nền: bậc, chất, sảnh =====================

def test_card_values_match_game_encoding():
    """Bậc phải khớp mã hoá của game: A=14, Heo=15, còn lại rank+1."""
    res = run_js("console.log(JSON.stringify([C.getCardVal(0), C.getCardVal(4),"
                 " C.getCardVal(8), C.getCardVal(48)]))")
    #             A♠  2♠(Heo)  3♠  K♠
    assert res == [14, 15, 3, 13]


def test_straight_never_contains_heo():
    """Sảnh không được chứa Heo — luật Tiến Lên."""
    res = run_js(
        "console.log(JSON.stringify({"
        "  ok: C.isStraight([8, 12, 16]),"          # 3,4,5
        "  hasHeo: C.isStraight([48, 4, 8]),"       # K,2,3 -> không phải sảnh
        "  tooShort: C.isStraight([8, 12])"
        "}))"
    )
    assert res["ok"] is True
    assert res["hasHeo"] is False
    assert res["tooShort"] is False


def test_at_duoc_dung_cuoi_sanh():
    """J-Q-K-A là sảnh hợp lệ; K-A-2 thì không vì có Heo."""
    jqka = [card(J), card(Q), card(K), card(A)]
    res = run_js(
        "console.log(JSON.stringify({"
        f" jqka: (C.phanLoai({jqka}) || {{}}).type,"
        f" ka2: C.phanLoai({[card(K), card(A), card(HEO)]})"
        "}))")
    assert res["jqka"] == "loc"
    assert res["ka2"] is None


# ===================== 2. Không có bom =====================

def test_khong_co_tu_quy_va_ba_doi_thong():
    """Sunwin không có bom: bốn lá cùng bậc KHÔNG phải kiểu bài hợp lệ."""
    tu_quy = [card(BAY, s) for s in range(4)]
    ba_doi = [card(BA, 0), card(BA, 1), card(BON, 0), card(BON, 1),
              card(NAM, 0), card(NAM, 1)]
    res = run_js("console.log(JSON.stringify({"
                 f" tuQuy: C.phanLoai({tu_quy}),"
                 f" baDoiThong: C.phanLoai({ba_doi})"
                 "}))")
    assert res["tuQuy"] is None
    assert res["baDoiThong"] is None


def test_tu_quy_khong_chat_duoc_heo_don():
    """Hệ quả của việc bỏ bom: Heo đơn chỉ bị chặn bởi Heo lớn hơn.

    Đây là mất mát so với engine cũ của HIT và là CHỦ Ý — bản Sunwin không có
    chặt. Ghi lại thành test để lần sau ai đó thấy 'thiếu' thì biết là cố tình.
    """
    tay = [card(BAY, s) for s in range(4)]          # tứ quý 7
    res = run_js(f"console.log(JSON.stringify(C.chooseFollow({tay}, [{card(HEO, 0)}])))")
    assert res is None

    tay_co_heo = [card(HEO, 3)]                      # Heo Cơ
    res2 = run_js(f"console.log(JSON.stringify(C.chooseFollow({tay_co_heo}, [{card(HEO, 0)}])))")
    assert res2 == [card(HEO, 3)]


# ===================== 3. Lượt tự do: thứ tự ưu tiên =====================

def test_dan_uu_tien_sanh_roi_sam_roi_doi_roi_don():
    """SẢNH -> SÁM -> ĐÔI -> LÁ ĐƠN.

    So sánh theo TẬP LÁ, không theo thứ tự: trong một bậc, engine xếp chất giảm
    dần (lấy đôi/sám mạnh nhất) nên sám trả về là [9♦, 9♣, 9♠].
    """
    sanh = [card(BA), card(BON), card(NAM)]
    sam = [card(CHIN, s) for s in range(3)]
    doi = [card(J, 0), card(J, 1)]
    don = [card(K, 0)]

    def dan(tay):
        return sorted(run_js(f"console.log(JSON.stringify(C.chooseLead({tay})))"))

    assert dan(sanh + sam + doi + don) == sorted(sanh)
    assert dan(sam + doi + don) == sorted(sam)
    assert dan(doi + don) == sorted(doi)
    assert dan(don) == sorted(don)
    assert run_js("console.log(JSON.stringify(C.chooseLead([])))") is None


def test_dan_la_don_thi_danh_la_TO_nhat():
    """Sunwin dẫn bằng nước to nhất, không phải nhỏ nhất."""
    tay = [card(BA, 0), card(MUOI, 2), card(SAU, 1)]
    assert run_js(f"console.log(JSON.stringify(C.chooseLead({tay})))") == [card(MUOI, 2)]


def test_sanh_to_nhat_la_sanh_co_la_dinh_cao_nhat():
    """KHÔNG phải sảnh dài nhất.

    Điểm = trọng số kiểu × 1.000.000 + bậc đỉnh × 100 + chất + số lá; số lá chỉ
    cộng vài đơn vị nên không lật ngược được bậc. Tay có 3-4-5-6-7-8 (đỉnh 8) và
    10-J-Q (đỉnh Q) thì chọn 10-J-Q. Giữ nguyên như Sunwin.
    """
    dai = [card(BA), card(BON), card(NAM), card(SAU), card(BAY), card(TAM)]
    ngan_nhung_cao = [card(MUOI, 2), card(J, 1), card(Q, 0)]
    res = run_js(f"console.log(JSON.stringify(C.chooseLead({dai + ngan_nhung_cao})))")
    assert res == ngan_nhung_cao


def test_doi_lay_hai_chat_cao_nhat_cua_bac():
    """Bậc có 3 lá mà cần đánh đôi thì lấy 2 chất CAO nhất — đôi mạnh nhất."""
    tay = [card(CHIN, 0), card(CHIN, 1), card(CHIN, 3)]
    ban = [card(TAM, 0), card(TAM, 1)]
    res = run_js(f"console.log(JSON.stringify(C.chooseFollow({tay}, {ban})))")
    assert sorted(res) == sorted([card(CHIN, 3), card(CHIN, 1)])


# ===================== 4. Lượt đè =====================

def test_de_bang_nuoc_TO_nhat_cung_kieu():
    tay = [card(NAM, 0), card(MUOI, 1), card(A, 3)]
    res = run_js(f"console.log(JSON.stringify(C.chooseFollow({tay}, [{card(BON, 0)}])))")
    assert res == [card(A, 3)]


def test_khong_de_duoc_thi_bo_luot():
    tay = [card(BA, 0), card(BON, 0)]
    assert run_js(f"console.log(JSON.stringify(C.chooseFollow({tay}, [{card(K, 0)}])))") is None


def test_sanh_chi_de_duoc_sanh_cung_do_dai():
    tay = [card(SAU), card(BAY), card(TAM), card(CHIN)]     # sảnh 4 lá
    ban = [card(BA), card(BON), card(NAM)]                  # sảnh 3 lá
    res = run_js(f"console.log(JSON.stringify(C.chooseFollow({tay}, {ban})))")
    assert res is not None and len(res) == 3, "phải đè bằng sảnh 3 lá, không phải 4"


def test_khac_kieu_thi_khong_de():
    """`beats` chỉ đúng khi CÙNG kiểu — đôi không đè lá đơn và ngược lại."""
    doi = [card(A, 0), card(A, 1)]
    res = run_js(
        "console.log(JSON.stringify({"
        f" doiDeDon: C.beats(C.phanLoai({doi}), C.phanLoai([{card(BA, 0)}])),"
        f" donDeDoi: C.beats(C.phanLoai([{card(HEO, 3)}]), C.phanLoai({doi}))"
        "}))")
    assert res["doiDeDon"] is False
    assert res["donDeDoi"] is False


def test_duoc_xe_doi_de_danh_la_don():
    """Bàn ra lá đơn thì tách đôi ra đánh một lá — đúng như Sunwin.

    Engine không giữ tổ hợp: mọi lá trên tay đều là ứng viên lá đơn.
    """
    doi = [card(A, 0), card(A, 1)]
    res = run_js(f"console.log(JSON.stringify(C.chooseFollow({doi}, [{card(BA, 0)}])))")
    assert res is not None and len(res) == 1 and res[0] in doi


def test_ban_khong_hop_le_thi_bo_luot():
    """Bàn ra thứ engine không phân loại được (ví dụ tứ quý) -> bỏ lượt."""
    tay = [card(A, s) for s in range(4)]
    tu_quy_tren_ban = [card(BAY, s) for s in range(4)]
    res = run_js(f"console.log(JSON.stringify(C.chooseFollow({tay}, {tu_quy_tren_ban})))")
    assert res is None


def test_chooseBestPlay_la_cua_duy_nhat():
    """Có bài trên bàn thì đè, không thì dẫn."""
    tay = [card(BA, 0), card(A, 3)]
    dan = run_js(f"console.log(JSON.stringify(C.chooseBestPlay({tay}, null)))")
    de = run_js(f"console.log(JSON.stringify(C.chooseBestPlay({tay}, [{card(NAM, 0)}])))")
    assert dan == [card(A, 3)]
    assert de == [card(A, 3)]


# ===================== 5. Nước trả về luôn hợp lệ =====================

def test_nuoc_tra_ve_luon_nam_trong_bai_va_dung_kieu():
    """Vét 400 tay ngẫu nhiên: nước chọn phải là tập con của bài và hợp kiểu."""
    res = run_js("""
      function rnd(seed) { let x = seed; return () => (x = (x * 1103515245 + 12345) % 2147483648) / 2147483648; }
      const r = rnd(20260911);
      const loi = [];
      for (let lan = 0; lan < 400; lan++) {
        const bo = [];
        for (let i = 0; i < 52; i++) bo.push(i);
        for (let i = bo.length - 1; i > 0; i--) {
          const j = Math.floor(r() * (i + 1));
          [bo[i], bo[j]] = [bo[j], bo[i]];
        }
        const tay = bo.slice(0, 13);
        const ban = lan % 2 === 0 ? null : bo.slice(13, 13 + (1 + (lan % 3)));
        const nuoc = C.chooseBestPlay(tay, ban);
        if (!nuoc) continue;
        if (!nuoc.every((c) => tay.includes(c))) { loi.push(['ngoai bai', tay, ban, nuoc]); continue; }
        if (new Set(nuoc).size !== nuoc.length) { loi.push(['trung la', tay, ban, nuoc]); continue; }
        const t = C.phanLoai(nuoc);
        if (!t) { loi.push(['khong hop kieu', tay, ban, nuoc]); continue; }
        if (ban) {
          const b = C.phanLoai(ban);
          if (b && !C.beats(t, b)) loi.push(['khong de duoc', tay, ban, nuoc]);
        }
      }
      console.log(JSON.stringify(loi.slice(0, 5)));
    """)
    assert res == [], f"nước sai: {res}"


# ===================== 6. Nối vào extension =====================

def _code_js(p: Path) -> str:
    """Chỉ lấy dòng CODE — chú thích có nhắc tên bị cấm là chuyện bình thường."""
    dong = []
    for d in p.read_text(encoding="utf-8").splitlines():
        s = d.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        dong.append(d)
    return "\n".join(dong)


def test_module_thuan_khong_dung_dom():
    code = _code_js(CARD_LOGIC)
    for cam in ("document", "localStorage", "WebSocket", "cc.", "fetch(", "window."):
        assert cam not in code, f"module không được đụng `{cam}`"


def test_wired_into_extension_and_manifest():
    """card_logic.js phải được nạp TRƯỚC content_main.js và được dùng thật."""
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    js_files = manifest["content_scripts"][0]["js"]
    # Khoá THỨ TỰ, không khoá cả danh sách: thêm một module thuần khác
    # (partner_id.js) là chuyện bình thường và không được làm test này đỏ.
    assert "card_logic.js" in js_files and "content_main.js" in js_files
    assert js_files.index("card_logic.js") < js_files.index("content_main.js"), js_files
    assert manifest["content_scripts"][0]["world"] == "MAIN"

    content = (EXT / "content_main.js").read_text(encoding="utf-8")
    assert "api.chooseBestPlay(myCards, tableCards)" in content, \
        "content_main.js chưa uỷ quyền chọn nước cho card_logic.js"

    # Controller cũng tự inject script vào trang -> phải nạp cả hai, ĐÚNG THỨ TỰ.
    pkg = Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
    controller = "\n".join(f.read_text(encoding="utf-8") for f in sorted(pkg.glob("*.py")))
    thu_tu = controller.split("for fname in (", 1)[1].split(")", 1)[0]
    assert thu_tu.index("card_logic.js") < thu_tu.index("content_main.js"), thu_tu


def test_khong_con_dau_vet_engine_phoi_hop():
    """Bỏ phối hợp là bỏ hẳn, không để hàm chết lại trong extension."""
    code = _code_js(CARD_LOGIC) + "\n" + _code_js(EXT / "content_main.js")
    for ten in ("chooseDumpBeat", "chooseDumpDischarge", "canPartnerBeat",
                "chooseWinnerBeat", "planMinTurns", "analyzeControl",
                "__partner_cards", "__AUTOTOOL_DUMP_RESERVE", "__cards_played"):
        assert ten not in code, f"còn sót `{ten}`"


def test_thieu_card_logic_thi_khong_doan_bua():
    """Không nạp được module thì trả null chứ không tự chế nước đi."""
    content = (EXT / "content_main.js").read_text(encoding="utf-8")
    i = content.index("function findBestPlay(myCards, tableCards)")
    than = content[i:i + 900]
    assert "return null;" in than
    assert "Thiếu card_logic.js" in than

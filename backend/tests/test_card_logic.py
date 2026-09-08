"""Kiểm thử phân rã bài tối ưu (backend/extension/card_logic.js).

Logic đánh bài chạy trong trình duyệt nên viết bằng JS. `card_logic.js` được
tách riêng, thuần tính toán (không đụng DOM/WebSocket), nên nạp được bằng node
và kiểm thử trực tiếp — khác với content_main.js vốn là IIFE có patch
WebSocket, không chạy ngoài trình duyệt.
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
    """Chạy đoạn JS có sẵn biến `C` = module card_logic, trả JSON đã in ra."""
    script = f"const C = require({json.dumps(str(CARD_LOGIC))});\n{body}"
    out = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=180,
        encoding="utf-8",
    )
    assert out.returncode == 0, f"node lỗi:\n{out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


# id lá = rank*4 + suit; rank 2..12 -> '3'..'K', rank 0 -> 'A', rank 1 -> '2'(Heo)
def card(rank_idx: int, suit: int = 0) -> int:
    return rank_idx * 4 + suit


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


@pytest.mark.parametrize("hand,expected,mota", [
    ([8, 12, 16, 20, 24, 48, 49], 2, "sảnh 3-4-5-6-7 + đôi K"),
    ([8, 21, 37], 3, "ba lá rời rạc không ghép được"),
    ([24, 25, 26, 27], 1, "tứ quý 7"),
    ([36, 37, 4], 2, "đôi 10 + Heo (Heo không vào sảnh)"),
    ([8], 1, "một lá"),
])
def test_min_turns_known_hands(hand, expected, mota):
    res = run_js(f"console.log(JSON.stringify(C.planMinTurns({hand}).turns))")
    assert res == expected, f"{mota}: kỳ vọng {expected} lượt, nhận {res}"


def test_partition_is_complete_and_valid():
    """Phân hoạch phải phủ đúng toàn bộ bài, không trùng, mọi nhóm hợp lệ."""
    res = run_js("""
      function isValidMeld(cards){
        if(cards.length===1) return true;
        const vals=cards.map(C.getCardVal);
        if(vals.every(v=>v===vals[0])) return cards.length<=4;
        return C.isStraight(cards);
      }
      let bad=[];
      for(let it=0; it<300; it++){
        const deck=[...Array(52).keys()];
        for(let i=51;i>0;i--){const j=(Math.random()*(i+1))|0;[deck[i],deck[j]]=[deck[j],deck[i]];}
        const hand=deck.slice(0,13);
        const p=C.planMinTurns(hand);
        const flat=p.melds.flat();
        if(flat.length!==13) bad.push(['thieu la',hand]);
        else if(new Set(flat).size!==13) bad.push(['trung la',hand]);
        else if(p.melds.length!==p.turns) bad.push(['turns lech',hand]);
        else for(const m of p.melds) if(!isValidMeld(m)) bad.push(['to hop sai',m]);
      }
      console.log(JSON.stringify(bad.slice(0,3)));
    """)
    assert res == [], f"phân hoạch sai: {res}"


def test_dp_matches_brute_force():
    """DP phải TỐI ƯU — đối chiếu vét cạn thật trên bài nhỏ.

    Vét cạn liệt kê MỌI tập con hợp lệ (không dùng heuristic nào của DP), nên
    đây là kiểm chứng độc lập. Chính phép này từng bắt được hai lỗi thật:
    sinh sảnh bỏ sót bước kiểm tra liên tiếp đầu tiên ({3,7,8} thành "sảnh"),
    và sơ đồ sảnh-cùng-tầng làm mất nghiệm [7 8 9 10]+[9 10 J].
    """
    res = run_js("""
      function isValidMeld(cards){
        if(cards.length===1) return true;
        const vals=cards.map(C.getCardVal);
        if(vals.every(v=>v===vals[0])) return cards.length<=4;
        return C.isStraight(cards);
      }
      function brute(cards){
        const n=cards.length, full=(1<<n)-1, memo=new Map(), valid=[];
        for(let m=1;m<=full;m++){
          const g=[]; for(let i=0;i<n;i++) if(m&(1<<i)) g.push(cards[i]);
          if(isValidMeld(g)) valid.push(m);
        }
        function f(S){
          if(S===0) return 0;
          if(memo.has(S)) return memo.get(S);
          const low=S&-S; let best=Infinity;
          for(const m of valid){ if((m&low)===0||(m&S)!==m) continue;
            const r=f(S^m); if(r+1<best) best=r+1; }
          memo.set(S,best); return best;
        }
        return f(full);
      }
      let bad=[];
      for(let it=0; it<250; it++){
        const size=3+((Math.random()*8)|0);
        const deck=[...Array(52).keys()];
        for(let i=51;i>0;i--){const j=(Math.random()*(i+1))|0;[deck[i],deck[j]]=[deck[j],deck[i]];}
        const hand=deck.slice(0,size);
        const dp=C.planMinTurns(hand).turns, bf=brute(hand);
        if(dp!==bf) bad.push({dp:dp, brute:bf, hand:hand});
      }
      console.log(JSON.stringify(bad.slice(0,3)));
    """)
    assert res == [], f"DP không tối ưu: {res}"


def test_regression_layered_straights():
    """Hai sảnh chồng nhau dùng tầng khác nhau ở từng bậc.

    Bài: 4 5 7 8 9 9 10 10 J -> tối ưu 4 lượt = [7 8 9 10] + [9 10 J] + 4 + 5.
    Bản DP đầu chỉ sinh sảnh "cùng tầng" nên bỏ sót và trả 5 lượt.
    """
    hand = [43, 37, 36, 28, 32, 12, 34, 26, 17]
    res = run_js(f"console.log(JSON.stringify(C.planMinTurns({hand}).turns))")
    assert res == 4


def test_regression_non_consecutive_not_a_straight():
    """{4, 8, 9} không phải sảnh — không được ghép thành một lượt.

    Vòng sinh sảnh từng bắt đầu ở e=s+2 nên bỏ qua bước kiểm tra s -> s+1,
    biến các bậc rời rạc thành "sảnh" và cho ra số lượt THẤP HƠN cả tối ưu.
    """
    hand = [card(3), card(7), card(8)]   # 4, 8, 9
    res = run_js(f"console.log(JSON.stringify(C.planMinTurns({hand}).turns))")
    assert res == 3, "ba lá rời rạc phải là 3 lượt"


def test_never_worse_than_greedy_strategy():
    """Không bao giờ tệ hơn chiến lược tham lam cũ (sảnh dài nhất trước)."""
    res = run_js("""
      function findCombinations(cards){
        const sortedC=C.sortCards(cards); const valMap={};
        for(const c of sortedC){const v=C.getCardVal(c); (valMap[v]=valMap[v]||[]).push(c);}
        const straights=[]; const nonTwo=Object.keys(valMap).map(Number).filter(v=>v<15).sort((a,b)=>a-b);
        for(let len=nonTwo.length;len>=3;len--)
          for(let s=0;s<=nonTwo.length-len;s++){
            const sub=nonTwo.slice(s,s+len); let ok=true;
            for(let i=1;i<sub.length;i++) if(sub[i]!==sub[i-1]+1){ok=false;break;}
            if(ok) straights.push(sub.map(v=>valMap[v][0]));
          }
        return {straights,
          quads:Object.values(valMap).filter(cs=>cs.length>=4).map(cs=>cs.slice(0,4)),
          triples:Object.values(valMap).filter(cs=>cs.length>=3).map(cs=>cs.slice(0,3)),
          pairs:Object.values(valMap).filter(cs=>cs.length>=2).map(cs=>cs.slice(0,2))};
      }
      function greedyTurns(cards){
        let rest=cards.slice(),t=0;
        while(rest.length){
          const cb=findCombinations(rest); let play;
          if(cb.straights.length)play=cb.straights[0];
          else if(cb.quads.length)play=cb.quads[0];
          else if(cb.triples.length)play=cb.triples[0];
          else if(cb.pairs.length)play=cb.pairs[0];
          else play=[C.sortCards(rest)[0]];
          const s=new Set(play); rest=rest.filter(c=>!s.has(c)); t++;
        }
        return t;
      }
      let worse=[];
      for(let it=0; it<400; it++){
        const deck=[...Array(52).keys()];
        for(let i=51;i>0;i--){const j=(Math.random()*(i+1))|0;[deck[i],deck[j]]=[deck[j],deck[i]];}
        const hand=deck.slice(0,13);
        const d=C.planMinTurns(hand).turns, g=greedyTurns(hand);
        if(d>g) worse.push({dp:d, greedy:g, hand:hand});
      }
      console.log(JSON.stringify(worse.slice(0,3)));
    """)
    assert res == [], f"DP tệ hơn tham lam ở: {res}"


def test_wired_into_extension_and_manifest():
    """card_logic.js phải được nạp TRƯỚC content_main.js và được dùng thật."""
    ext = Path(__file__).parents[1] / "extension"
    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
    js_files = manifest["content_scripts"][0]["js"]
    assert js_files == ["card_logic.js", "content_main.js"], js_files
    assert manifest["content_scripts"][0]["world"] == "MAIN"

    content = (ext / "content_main.js").read_text(encoding="utf-8")
    assert "planMinTurns" in content, "nhánh xả bài chưa gọi tới phân rã tối ưu"

    # Controller cũng tự inject script vào trang -> phải nạp cả hai, đúng thứ tự
    matching = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
                / "matching.py").read_text(encoding="utf-8")
    assert '("card_logic.js", "content_main.js")' in matching


# ---------- Đảo chiều ưu tiên cho Account phụ ----------

def test_dump_discharges_dangerous_cards_first():
    """Phụ phải tống Heo / lá cao đi TRƯỚC, không giữ tới cuối ván.

    Cuối ván ai còn Heo / 3 bích thì bị phạt. Đánh hết lá cao từ sớm là cách
    chắc chắn nhất để phần còn lại tất yếu là lá thấp, không bị phạt.
    """
    # 3♠ 4♣ 5♠ 6♦ | 2♠ 2♣ (Heo) | K♠ K♣
    hand = [8, 13, 16, 22, 4, 5, 48, 49]
    res = run_js(f"""
      let cur = {hand};
      const out = [];
      for (let i = 0; i < 8; i++) {{
        const play = C.chooseDumpDischarge(cur, 4);
        if (!play) break;
        out.push(play.map(C.getCardVal));
        const s = new Set(play);
        cur = cur.filter(c => !s.has(c));
      }}
      console.log(JSON.stringify({{plays: out, con_lai: C.sortCards(cur).map(C.getCardVal)}}));
    """)
    # Heo (15) phải ra lượt đầu, K (13) lượt sau
    assert res["plays"][0] == [15, 15], f"phải xả Heo trước, nhận {res['plays'][0]}"
    assert res["plays"][1] == [13, 13], f"kế tiếp phải là đôi K, nhận {res['plays'][1]}"
    # Còn lại đúng 4 lá thấp nhất làm mồi
    assert res["con_lai"] == [3, 4, 5, 6]


def test_dump_keeps_reserve_untouched():
    """Phần giữ lại không bao giờ bị xé — tổ hợp chỉ tìm ngoài phần đó."""
    res = run_js("""
      let bad = [];
      for (let it = 0; it < 300; it++) {
        const deck=[...Array(52).keys()];
        for(let i=51;i>0;i--){const j=(Math.random()*(i+1))|0;[deck[i],deck[j]]=[deck[j],deck[i]];}
        const hand = deck.slice(0, 13);
        const keep = 4;
        const reserve = new Set(C.sortCards(hand).slice(0, keep));
        const play = C.chooseDumpDischarge(hand, keep);
        if (play) for (const c of play) if (reserve.has(c)) bad.push({hand:hand, play:play});
      }
      console.log(JSON.stringify(bad.slice(0, 3)));
    """)
    assert res == [], f"đã xé vào phần giữ lại: {res}"


def test_dump_returns_null_when_only_reserve_left():
    """Còn <= số lá giữ lại -> trả null để bên ngoài chuyển sang chế độ mồi."""
    res = run_js("console.log(JSON.stringify(["
                 " C.chooseDumpDischarge([8, 12, 16, 20], 4) === null,"
                 " C.chooseDumpDischarge([8, 12], 4) === null,"
                 " C.chooseDumpDischarge([], 4) === null]))")
    assert res == [True, True, True]


def test_dump_priority_is_opposite_of_anchor():
    """Phụ chọn nhóm chứa lá CAO nhất; chính chọn nhóm THẤP nhất."""
    res = run_js("""
      const hand = [8, 12, 16, 20, 24, 48, 49, 4];   // 3 4 5 6 7 K K 2(Heo)
      const dump = C.chooseDumpDischarge(hand, 4);
      const anchor = C.planMinTurns(hand).melds[0];
      console.log(JSON.stringify({
        dump: dump.map(C.getCardVal),
        anchorLow: Math.max.apply(null, anchor.map(C.getCardVal))
      }));
    """)
    assert max(res["dump"]) >= 13, "phụ phải nhắm lá cao"
    assert res["anchorLow"] <= 7, "chính phải bắt đầu từ nhóm thấp"


def test_dump_discharge_wired_into_extension():
    ext = Path(__file__).parents[1] / "extension"
    content = (ext / "content_main.js").read_text(encoding="utf-8")
    assert "chooseDumpDischarge" in content, "nhánh DUMP chưa gọi tới hàm xả nguy hiểm"
    assert "__AUTOTOOL_DUMP_RESERVE" in content, "chưa cho cấu hình số lá giữ lại"


def test_dump_de_la_cao_khi_con_nhieu_hon_phan_giu():
    """Account chính đánh, phụ CÒN NHIỀU HƠN phần giữ -> phải đè bằng lá CAO.

    Trước đây phụ chỉ đè đúng một lần mỗi ván ("giảm thua trắng") và bằng tổ
    hợp NHỎ NHẤT, nên khi còn nhiều lá nó vẫn PASS — lá nguy hiểm bị giữ tới
    cuối ván rồi bị phạt.
    """
    # B: 3♠ 4♣ 5♠ 6♦ | 9♠ | K♣ | 2♠(Heo)
    B = [8, 13, 16, 22, 32, 49, 4]
    res = run_js(f"""
      const B = {B};
      console.log(JSON.stringify({{
        deKhi7:  (C.chooseDumpBeat(B, [24], 4) || []).map(C.getCardVal),
        deKhi10: (C.chooseDumpBeat(B, [36], 4) || []).map(C.getCardVal),
        gapHeo:  C.chooseDumpBeat(B, [5], 4),
        vePhanGiu: C.chooseDumpBeat([8, 13, 16, 22], [24], 4)
      }}));
    """)
    assert res["deKhi7"] == [15], "phải đè bằng Heo — lá nguy hiểm nhất"
    assert res["deKhi10"] == [15]
    assert res["gapHeo"] is None, "không đè được Heo đơn bằng lá lẻ -> PASS"
    assert res["vePhanGiu"] is None, "về đúng phần giữ thì nhường lượt cho chính"


def test_dump_beat_khong_dung_bai_da_giu():
    """Nước đè cũng không được xé vào phần giữ lại."""
    res = run_js("""
      let bad = [];
      for (let it = 0; it < 300; it++) {
        const deck=[...Array(52).keys()];
        for(let i=51;i>0;i--){const j=(Math.random()*(i+1))|0;[deck[i],deck[j]]=[deck[j],deck[i]];}
        const hand = deck.slice(0, 11);
        const table = [deck[20]];
        const keep = 4;
        const reserve = new Set(C.sortCards(hand).slice(0, keep));
        const beat = C.chooseDumpBeat(hand, table, keep);
        if (beat) {
          for (const c of beat) if (reserve.has(c)) bad.push({hand:hand, beat:beat});
          if (!C.canBeat(beat, table)) bad.push({loi:'khong de duoc', beat:beat, table:table});
        }
      }
      console.log(JSON.stringify(bad.slice(0, 3)));
    """)
    assert res == [], f"sai: {res}"


def test_dump_beat_wired_into_extension():
    ext = Path(__file__).parents[1] / "extension"
    src = (ext / "content_main.js").read_text(encoding="utf-8")
    assert "chooseDumpBeat" in src, "nhánh đè của phụ chưa gọi chooseDumpBeat"
    # Phải nằm TRƯỚC quy tắc "giảm thua trắng" cũ
    assert src.index("chooseDumpBeat") < src.index("Giảm thua trắng")


# ---------- Đếm bài ----------

def test_unseen_cards_arithmetic():
    """52 lá trừ (bài mình ∪ lá đã ra) = tập còn ẩn; không đếm trùng."""
    res = run_js("""
      const u = C.unseenCards([0, 1, 2], [2, 3, 4, 4]);   // 2 và 4 lặp -> đếm 1
      console.log(JSON.stringify({n: u.length, coTrung: u.some(c => [0,1,2,3,4].includes(c))}));
    """)
    assert res["n"] == 52 - 5
    assert res["coTrung"] is False


def test_can_anyone_beat_single_pair_quad_straight():
    """Kiểm tra theo cấu trúc trên tập ẩn — từng loại tổ hợp."""
    res = run_js("""
      const all = [...Array(52).keys()];
      const lowOnly = all.filter(c => C.getCardVal(c) <= 10);
      console.log(JSON.stringify({
        // K♠(48): còn A/Heo ẩn -> bị chặn; ẩn toàn lá thấp -> an toàn
        kBiChan:     C.canAnyoneBeat([48], all.filter(c => c !== 48)),
        kAnToan:     C.canAnyoneBeat([48], lowOnly),
        // Heo đơn 2♠(4): còn tứ quý 7 ẩn -> bị chặt; chỉ ba lá 7 -> an toàn
        heoBiTuQuy:  C.canAnyoneBeat([4], [24, 25, 26, 27]),
        heoAnToan:   C.canAnyoneBeat([4], [24, 25, 26]),
        // Đôi K: còn đôi A ẩn -> bị chặn; chỉ 1 lá A -> an toàn
        doiKBiChan:  C.canAnyoneBeat([48, 49], [0, 1]),
        doiKAnToan:  C.canAnyoneBeat([48, 49], [0]),
        // Sảnh 3-4-5: còn sảnh 4-5-6 ẩn -> bị chặn; thiếu lá 6 -> an toàn
        sanhBiChan:  C.canAnyoneBeat([8, 12, 16], [13, 17, 21]),
        sanhAnToan:  C.canAnyoneBeat([8, 12, 16], [13, 17]),
      }));
    """)
    assert res == {
        "kBiChan": True, "kAnToan": False,
        "heoBiTuQuy": True, "heoAnToan": False,
        "doiKBiChan": True, "doiKAnToan": False,
        "sanhBiChan": True, "sanhAnToan": False,
    }, res


def test_can_anyone_beat_matches_brute_force():
    """Đối chiếu vét cạn: liệt kê MỌI tổ hợp trong tập ẩn rồi thử canBeat.

    Tập ẩn giới hạn <= 18 lá để enumerateMelds (bitmask 32-bit) còn dùng được.
    """
    res = run_js("""
      let bad = [];
      for (let it = 0; it < 250; it++) {
        const deck=[...Array(52).keys()];
        for(let i=51;i>0;i--){const j=(Math.random()*(i+1))|0;[deck[i],deck[j]]=[deck[j],deck[i]];}
        const mine = deck.slice(0, 8);
        const unseen = deck.slice(8, 8 + 18);
        const plan = C.planMinTurns(mine);
        const su = C.sortCards(unseen);
        const melds = C.enumerateMelds(su);
        for (const m of plan.melds) {
          const fast = C.canAnyoneBeat(m, unseen);
          let brute = false;
          for (const e of melds) {
            const g = []; for (let i = 0; i < su.length; i++) if (e.mask & (1 << i)) g.push(su[i]);
            if (C.canBeat(g, m)) { brute = true; break; }
          }
          if (fast !== brute) bad.push({meld: m, fast: fast, brute: brute, unseen: unseen});
        }
      }
      console.log(JSON.stringify(bad.slice(0, 2)));
    """)
    assert res == [], f"canAnyoneBeat lệch vét cạn: {res}"


def test_analyze_control_detects_sure_win():
    """Mọi nhóm đều bất khả chặn -> allUnbeatable, đi hết bài là chắc chắn."""
    res = run_js("""
      // Mình: K♠ K♣ (48,49). Đã ra: hết A, hết Heo, K♦ K♥ -> không gì chặn được đôi K
      const played = [0,1,2,3, 4,5,6,7, 50,51];
      const a = C.analyzeControl([48, 49], played);
      const b = C.analyzeControl([48, 49], []);        // chưa ai đánh
      console.log(JSON.stringify({
        a_all: a.allUnbeatable, a_sure: a.sureCount, a_unseen: a.unseen,
        b_all: b.allUnbeatable, b_sure: b.sureCount
      }));
    """)
    assert res["a_all"] is True and res["a_sure"] == 1
    assert res["a_unseen"] == 52 - 2 - 10
    assert res["b_all"] is False and res["b_sure"] == 0


def test_card_counting_wired_into_extension():
    ext = Path(__file__).parents[1] / "extension"
    src = (ext / "content_main.js").read_text(encoding="utf-8")
    # Gom lá đã ra từ fP.dCs (công khai, kèm ai đánh) và reset khi chia bài mới
    assert "G.__cards_played.push(c)" in src
    assert src.count("G.__cards_played = [];") >= 2, "phải reset khi khởi tạo VÀ khi chia bài mới"
    # Account chính dùng kết quả đếm bài
    assert "analyzeControl(myCards, G.__cards_played" in src
    assert "CHẮC THẮNG" in src


# ---------- Giữ nhịp tiếp sức (phụ mồi — chính đè) ----------

def test_dump_uu_tien_la_cao_ma_dong_doi_con_de_duoc():
    """Không biết bài đồng đội -> phụ tống Heo, chính không đè được, đứt nhịp.

    Biết bài đồng đội -> phụ phải chọn lá cao NHƯNG chính còn đè lại được.
    """
    # B: 3♠ 4♣ 5♠ 6♦ | K♣ | 2♠(Heo)      A: A♠ 8♠
    B = [8, 13, 16, 22, 49, 4]
    A = [0, 28]
    res = run_js(f"""
      const B = {B}, A = {A};
      console.log(JSON.stringify({{
        khongBietBaiA: C.chooseDumpDischarge(B, 4).map(C.getCardVal),
        bietBaiA:      C.chooseDumpDischarge(B, 4, A).map(C.getCardVal),
        deKhongBiet:   C.chooseDumpBeat(B, [26], 4).map(C.getCardVal),
        deBiet:        C.chooseDumpBeat(B, [26], 4, A).map(C.getCardVal),
      }}));
    """)
    assert res["khongBietBaiA"] == [15], "không biết bài A thì tống Heo"
    assert res["bietBaiA"] == [13], "biết bài A thì phải chừa Heo, tống K"
    assert res["deKhongBiet"] == [15]
    assert res["deBiet"] == [13]


def test_hall_check_phat_hien_chuoi_moi_khong_kha_thi():
    """Định lý Hall: mỗi lá mồi phải ghép được một lá RIÊNG của chính đè nó."""
    res = run_js("""
      const reserve = [8, 13, 16, 22];      // 3♠ 4♣ 5♠ 6♦
      console.log(JSON.stringify({
        thieuLa:  C.hallCheck(reserve, [0, 28]),          // A chỉ có 2 lá
        duLa:     C.hallCheck(reserve, [24, 28, 32, 36]), // 7 8 9 10 -> đủ
        toanThap: C.hallCheck(reserve, [9, 10, 11, 12]),  // toàn lá 4 -> đè được 3 nhưng không đè 4/5/6
      }));
    """)
    assert res["thieuLa"]["ok"] is False and res["thieuLa"]["matched"] == 2
    assert res["duLa"]["ok"] is True and res["duLa"]["matched"] == 4
    assert res["toanThap"]["ok"] is False


def test_hall_check_khop_vet_can():
    """Ghép cặp phải cho cùng kết quả với vét cạn mọi hoán vị (n nhỏ)."""
    res = run_js("""
      function bruteSDR(reserve, pool) {
        const used = new Array(pool.length).fill(false);
        function rec(i) {
          if (i === reserve.length) return true;
          for (let j = 0; j < pool.length; j++) {
            if (used[j] || !C.canBeat([pool[j]], [reserve[i]])) continue;
            used[j] = true;
            if (rec(i + 1)) return true;
            used[j] = false;
          }
          return false;
        }
        return rec(0);
      }
      let bad = [];
      for (let it = 0; it < 300; it++) {
        const deck=[...Array(52).keys()];
        for(let i=51;i>0;i--){const j=(Math.random()*(i+1))|0;[deck[i],deck[j]]=[deck[j],deck[i]];}
        const reserve = deck.slice(0, 4);
        const pool = deck.slice(4, 9);
        const fast = C.hallCheck(reserve, pool).ok;
        const brute = bruteSDR(reserve, pool);
        if (fast !== brute) bad.push({reserve: reserve, pool: pool, fast: fast, brute: brute});
      }
      console.log(JSON.stringify(bad.slice(0, 2)));
    """)
    assert res == [], f"hallCheck lệch vét cạn: {res}"


def test_relay_wired_into_extension():
    ext = Path(__file__).parents[1] / "extension"
    src = (ext / "content_main.js").read_text(encoding="utf-8")
    # Cả hai nhánh của phụ phải truyền bài đồng đội
    assert "chooseDumpDischarge(myCards, reserve, G.__partner_cards)" in src
    assert "chooseDumpBeat(myCards, tableCards, reserveBeat, G.__partner_cards)" in src
    # Nhánh đè của chính phải ưu tiên nước không ai chặn lại được
    assert "canAnyoneBeat(c, unseen)" in src
    assert "không ai chặn lại được" in src

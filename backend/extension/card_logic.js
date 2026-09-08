/**
 * Logic bài THUẦN TÍNH TOÁN cho Tiến Lên Đếm Lá — không đụng DOM/WebSocket.
 *
 * Tách riêng khỏi content_main.js để:
 *  - kiểm thử được bằng node (content_main.js là IIFE có patch WebSocket/DOM,
 *    không nạp được ngoài trình duyệt);
 *  - dùng chung một nguồn sự thật cho phần phân rã bài.
 *
 * Mã lá bài: id 0..51, rank = floor(id/4), suit = id%4 (0 Bích, 1 Chuồn, 2 Rô,
 * 3 Cơ). Giá trị: rank>=2 -> rank+1 (3..K=13), rank 0 -> 14 (A), rank 1 -> 15
 * (Heo). Sảnh cần >=3 lá liên tiếp và KHÔNG chứa Heo.
 */
(function (root) {
  "use strict";

  function getCardVal(c) {
    const r = Math.floor(c / 4);
    if (r >= 2) return r + 1;
    if (r === 0) return 14;
    if (r === 1) return 15;
    return 0;
  }

  function getCardSuit(c) {
    return c % 4;
  }

  function compareCards(c1, c2) {
    const v1 = getCardVal(c1), v2 = getCardVal(c2);
    if (v1 !== v2) return v1 - v2;
    return getCardSuit(c1) - getCardSuit(c2);
  }

  function sortCards(cards) {
    return (cards || []).slice().sort(compareCards);
  }

  function isStraight(cards) {
    if (!cards || cards.length < 3) return false;
    const sc = sortCards(cards);
    if (sc.some((c) => getCardVal(c) === 15)) return false;
    for (let i = 1; i < sc.length; i++) {
      if (getCardVal(sc[i]) !== getCardVal(sc[i - 1]) + 1) return false;
    }
    return true;
  }

  const MAX_CARDS_FOR_DP = 20;

  /**
   * Liệt kê tổ hợp hợp lệ trong tay bài, trả về bitmask theo chỉ số của mảng
   * `cards` đã truyền vào (không phải theo id lá).
   *
   * Tập tổ hợp phải ĐÓNG với phần dư, nếu không DP sẽ bỏ sót nghiệm:
   *  - Trong một bậc: sinh đủ mọi tổ hợp chập 2/3/4. Mỗi bậc tối đa 4 lá nên
   *    nhiều nhất 6+4+1 = 11 tổ hợp — rẻ.
   *  - Sảnh: sinh THEO TẦNG. Với một khoảng bậc liên tiếp, gọi m là số lá ít
   *    nhất của một bậc trong khoảng; sinh m sảnh rời nhau, sảnh tầng j lấy lá
   *    thứ j của từng bậc. Nhờ vậy hai sảnh chồng nhau (vd 8-9-10 đôi) đều có
   *    mặt trong tập tổ hợp.
   *
   * (Bản đầu chỉ lấy lá THẤP NHẤT mỗi bậc cho sảnh -> phần dư là các lá thứ
   * hai, không còn tổ hợp nào phủ, khiến DP trả kết quả TỆ HƠN tham lam.)
   */
  function enumerateMelds(cards) {
    const n = cards.length;
    const melds = [];
    const push = (idxs, kind) => {
      let mask = 0;
      for (const i of idxs) mask |= (1 << i);
      let high = idxs[0];
      for (const i of idxs) if (compareCards(cards[i], cards[high]) > 0) high = i;
      melds.push({ mask: mask, kind: kind, size: idxs.length, high: cards[high] });
    };

    // Gom chỉ số theo giá trị (mảng đã sắp nên mỗi nhóm cũng tăng dần)
    const byVal = new Map();
    for (let i = 0; i < n; i++) {
      const v = getCardVal(cards[i]);
      if (!byVal.has(v)) byVal.set(v, []);
      byVal.get(v).push(i);
    }

    // Lá lẻ: luôn hợp lệ -> bảo đảm mọi tập con đều phủ được
    for (let i = 0; i < n; i++) push([i], "single");

    // Đôi / ba / tứ quý: đủ mọi tổ hợp trong một bậc (tối đa 4 lá -> rất rẻ)
    for (const idxs of byVal.values()) {
      const k = idxs.length;
      for (let a = 0; a < k; a++) {
        for (let b = a + 1; b < k; b++) {
          push([idxs[a], idxs[b]], "pair");
          for (let c = b + 1; c < k; c++) {
            push([idxs[a], idxs[b], idxs[c]], "triple");
            for (let d = c + 1; d < k; d++) push([idxs[a], idxs[b], idxs[c], idxs[d]], "quad");
          }
        }
      }
    }

    // Sảnh theo TẦNG: mọi khoảng bậc liên tiếp độ dài >=3, không chứa Heo.
    const vals = Array.from(byVal.keys()).filter((v) => v < 15).sort((x, y) => x - y);
    for (let s = 0; s < vals.length; s++) {
      // e chạy từ s+1 để kiểm tra tính liên tiếp của TỪNG bước một; bắt đầu từ
      // s+2 sẽ bỏ qua bước s->s+1 và biến {3,7,8} thành "sảnh".
      for (let e = s + 1; e < vals.length; e++) {
        if (vals[e] !== vals[e - 1] + 1) break;  // hết đoạn liên tiếp
        if (e - s + 1 < 3) continue;             // sảnh cần >= 3 lá
        let layers = Infinity;
        for (let t = s; t <= e; t++) layers = Math.min(layers, byVal.get(vals[t]).length);
        for (let j = 0; j < layers; j++) {
          const idxs = [];
          for (let t = s; t <= e; t++) idxs.push(byVal.get(vals[t])[j]);
          push(idxs, "straight");
        }
      }
    }

    // Xét tổ hợp LỚN trước, cùng cỡ thì lá cao nhỏ hơn trước. Chỉ ảnh hưởng
    // cách phá hoà, không ảnh hưởng số lượt tối thiểu.
    melds.sort((p, q) => (q.size - p.size) || compareCards(p.high, q.high));
    return melds;
  }

  /**
   * PHÂN RÃ TỐI ƯU: chia tay bài thành SỐ TỔ HỢP ÍT NHẤT.
   *
   * Đây là bài toán phủ chính xác (exact cover), giải bằng quy hoạch động trên
   * bitmask:
   *     f(S) = 1 + min{ f(S \ M) : M là tổ hợp hợp lệ, M ⊆ S, M chứa lá thấp
   *                     nhất của S }
   * Ràng buộc "M phải chứa lá thấp nhất của S" khử trùng lặp hoán vị mà vẫn
   * giữ tính tối ưu: trong mọi phân hoạch, lá thấp nhất phải nằm ở đúng một
   * nhóm nào đó.
   *
   * Vì lá lẻ luôn là tổ hợp hợp lệ nên f(S) luôn có nghiệm.
   * Độ phức tạp: O(2^n * |melds|); n=13 -> 8192 trạng thái, chạy vài ms.
   *
   * @returns {{turns:number, melds:number[][]}} số lượt tối thiểu và danh sách
   *          tổ hợp (mỗi tổ hợp là mảng id lá).
   */
  // Giá trị 3..15 -> chỉ số bậc 0..12 (bậc 12 là Heo, không vào sảnh)
  const RANK_COUNT = 13;
  const HEO_RANK = 12;

  function planMinTurns(cards) {
    const hand = sortCards(cards || []);
    const n = hand.length;
    if (n === 0) return { turns: 0, melds: [] };
    if (n > MAX_CARDS_FOR_DP) {
      return { turns: n, melds: hand.map((c) => [c]) };
    }

    // Đếm theo BẬC, và giữ danh sách lá của từng bậc (đã tăng dần)
    const cnt = new Array(RANK_COUNT).fill(0);
    const byRank = new Array(RANK_COUNT).fill(null).map(() => []);
    for (const c of hand) {
      const r = getCardVal(c) - 3;
      cnt[r]++;
      byRank[r].push(c);
    }

    // Mẫu tiêu thụ: {kind:'set', r, k} lấy k lá cùng bậc r;
    //               {kind:'run', s, e} lấy 1 lá mỗi bậc từ s đến e.
    const patterns = [];
    for (let r = 0; r < RANK_COUNT; r++) {
      for (let k = 1; k <= Math.min(4, cnt[r]); k++) patterns.push({ kind: "set", r: r, k: k });
    }
    for (let s = 0; s < HEO_RANK; s++) {
      for (let e = s + 2; e < HEO_RANK; e++) patterns.push({ kind: "run", s: s, e: e });
    }

    const encode = (v) => {
      let key = 0;
      for (let r = 0; r < RANK_COUNT; r++) key = key * 5 + v[r];
      return key;
    };

    const memo = new Map();   // key -> {turns, pattern}

    function solve(v) {
      let lowest = -1;
      for (let r = 0; r < RANK_COUNT; r++) if (v[r] > 0) { lowest = r; break; }
      if (lowest < 0) return { turns: 0, pattern: null };

      const key = encode(v);
      const hit = memo.get(key);
      if (hit) return hit;
      memo.set(key, { turns: Infinity, pattern: null });   // chặn đệ quy vòng

      let best = { turns: Infinity, pattern: null };
      for (const p of patterns) {
        // BẮT BUỘC phủ bậc thấp nhất -> khử trùng lặp hoán vị, vẫn đầy đủ vì
        // trong mọi phân hoạch, bậc thấp nhất phải nằm ở đúng một nhóm.
        if (p.kind === "set") {
          if (p.r !== lowest || v[p.r] < p.k) continue;
          v[p.r] -= p.k;
          const sub = solve(v);
          v[p.r] += p.k;
          if (sub.turns + 1 < best.turns) best = { turns: sub.turns + 1, pattern: p };
        } else {
          if (p.s !== lowest) continue;           // sảnh phải bắt đầu từ bậc thấp nhất
          let ok = true;
          for (let r = p.s; r <= p.e; r++) if (v[r] < 1) { ok = false; break; }
          if (!ok) continue;
          for (let r = p.s; r <= p.e; r++) v[r]--;
          const sub = solve(v);
          for (let r = p.s; r <= p.e; r++) v[r]++;
          if (sub.turns + 1 < best.turns) best = { turns: sub.turns + 1, pattern: p };
        }
      }
      memo.set(key, best);
      return best;
    }

    // Truy vết: gán lá THẤP NHẤT còn lại của mỗi bậc cho từng nhóm.
    const state = cnt.slice();
    const res = solve(state);
    const pool = byRank.map((a) => a.slice());
    const out = [];
    let cur = state;
    while (true) {
      const step = solve(cur);
      if (!step.pattern) break;
      const p = step.pattern;
      const group = [];
      if (p.kind === "set") {
        for (let i = 0; i < p.k; i++) group.push(pool[p.r].shift());
        cur[p.r] -= p.k;
      } else {
        for (let r = p.s; r <= p.e; r++) group.push(pool[r].shift());
        for (let r = p.s; r <= p.e; r++) cur[r]--;
      }
      out.push(group);
    }

    // Lượt nhỏ trước: giữ lá cao lại để còn giành quyền dẫn.
    out.sort((a, b) => compareCards(sortCards(a)[a.length - 1], sortCards(b)[b.length - 1]));
    return { turns: res.turns, melds: out };
  }

  const api = {
    getCardVal: getCardVal,
    getCardSuit: getCardSuit,
    compareCards: compareCards,
    sortCards: sortCards,
    isStraight: isStraight,
    enumerateMelds: enumerateMelds,
    planMinTurns: planMinTurns,
  };

  root.AutoToolCards = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);

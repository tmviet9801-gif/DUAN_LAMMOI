/**
 * Logic chọn nước bài — CHUYỂN NGUYÊN TỪ CÔNG CỤ SUNWIN (control/extension_auto).
 *
 * Người dùng yêu cầu (11/09/2026): "áp dụng lại TOÀN BỘ logic xả bài" của
 * Sunwin, và "bỏ phối hợp" giữa hai nick. Bản trước của file này là một engine
 * phối hợp: nick phụ giữ 3-4 lá thấp làm mồi, chọn nước mà nick chính còn đè
 * lại được, có đếm bài và phân rã tối ưu số lượt. Toàn bộ phần đó đã bỏ.
 *
 * LUẬT CỦA SUNWIN, đúng thứ tự:
 *   - Lượt tự do: SẢNH -> SÁM -> ĐÔI -> LÁ ĐƠN; trong mỗi loại lấy điểm cao
 *     nhất, tức nước TO NHẤT.
 *   - Lượt đè: chỉ xét đúng KIỂU đang có trên bàn, duyệt từ to xuống và đánh
 *     cái ĐẦU TIÊN đè được -> luôn đè bằng nước to nhất. Không đè được thì bỏ.
 *   - KHÔNG có tứ quý, KHÔNG có ba đôi thông, KHÔNG chặt Heo. Bốn lá cùng bậc
 *     không phải một kiểu bài hợp lệ (`phanLoai` trả null), nên Heo đơn chỉ
 *     bị chặn bởi Heo lớn hơn. Đây là mất mát so với bản cũ của HIT và là chủ
 *     ý — bản Sunwin không có bom.
 *   - Sảnh KHÔNG được chứa Heo; Át được phép đứng cuối sảnh (…J Q K A).
 *
 * ĐIỂM (`diem`) quyết mọi thứ tự: trọng số kiểu × 1.000.000 + bậc lá đỉnh × 100
 * + chất lá đỉnh + số lá. Số lá chỉ cộng vài đơn vị nên KHÔNG lật ngược được
 * bậc: sảnh 10-J-Q (đỉnh Q) xếp trên sảnh 3-4-5-6-7 (đỉnh 7). Nghĩa là "sảnh
 * có lá đỉnh cao nhất", không phải "sảnh dài nhất". Giữ nguyên như Sunwin.
 *
 * KHÔNG chuyển sang: khoảng cách cứng 250ms giữa hai lệnh của Sunwin. Ở đây
 * đã khoá theo SỐ THỨ TỰ LƯỢT (content_main.js) — hai người bỏ lượt liên tiếp
 * thật sự chỉ cách nhau vài chục mili-giây nên bộ đếm thời gian sẽ nuốt mất
 * nước hợp lệ. Xem backend/tests/test_khoa_mot_lenh_mot_luot.py.
 *
 * Mã lá bài của HIT: id 0..51, bậc = floor(id/4), chất = id%4 (0 Bích, 1
 * Chuồn, 2 Rô, 3 Cơ — thấp đến cao). Giá trị: bậc>=2 -> bậc+1 (3..K=13),
 * bậc 0 -> 14 (A), bậc 1 -> 15 (Heo). Thang này trùng thang của Sunwin
 * (Heo 15, Át 14) nên phần so sánh chuyển thẳng được.
 *
 * Thuần tính toán — không đụng DOM/WebSocket, nên kiểm thử được bằng node.
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
    if (sc.some((c) => getCardVal(c) === 15)) return false;   // sảnh không chứa Heo
    for (let i = 1; i < sc.length; i++) {
      if (getCardVal(sc[i]) !== getCardVal(sc[i - 1]) + 1) return false;
    }
    return true;
  }

  // ===================== NHÓM & ĐIỂM =====================

  const TRONG_SO = { loc: 4, trips: 3, pair: 2, single: 1 };

  /** Lá đỉnh của một nhóm — lá lớn nhất theo bậc rồi chất. */
  function laDinh(cards) {
    let top = cards[0];
    for (let i = 1; i < cards.length; i++) {
      if (compareCards(cards[i], top) > 0) top = cards[i];
    }
    return top;
  }

  /** Điểm xếp hạng của một nhóm. Xem chú thích đầu file. */
  function diem(type, cards) {
    const top = laDinh(cards);
    return (TRONG_SO[type] || 0) * 1000000
      + getCardVal(top) * 100 + getCardSuit(top) + cards.length;
  }

  /** Gom bài theo bậc; mỗi bậc xếp chất GIẢM DẦN.
   *
   * Xếp giảm dần để `slice(0, n)` lấy được đôi/sám mạnh nhất của bậc đó, và
   * để sảnh lấy lá chất cao nhất ở mỗi bậc — lá đỉnh càng cao càng dễ đè.
   * (Bản cũ của HIT lấy chất THẤP nhất nên bỏ sót nước đè hợp lệ.)
   */
  function gomTheoBac(cards) {
    const theo = {};
    for (const c of cards || []) {
      const v = getCardVal(c);
      (theo[v] = theo[v] || []).push(c);
    }
    for (const v of Object.keys(theo)) {
      theo[v].sort((a, b) => getCardSuit(b) - getCardSuit(a));
    }
    return theo;
  }

  // Thứ tự bậc dùng cho sảnh: 3..K rồi A. Heo (15) không nằm trong danh sách
  // nên không bao giờ vào sảnh.
  const BAC_SANH = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14];

  /** Mọi sảnh (>=3 lá) rút được từ bài, xếp điểm GIẢM DẦN. */
  function cacSanh(hand) {
    const theo = gomTheoBac(hand);
    const co = BAC_SANH.filter((v) => theo[v] && theo[v].length);
    const ra = [];
    for (let i = 0; i < co.length; i++) {
      // Gom một dải bậc liên tiếp
      const dai = [co[i]];
      while (i + 1 < co.length
             && BAC_SANH.indexOf(co[i + 1]) === BAC_SANH.indexOf(co[i]) + 1) {
        i++;
        dai.push(co[i]);
      }
      if (dai.length < 3) continue;
      for (let len = dai.length; len >= 3; len--) {
        for (let s = 0; s + len <= dai.length; s++) {
          const cards = dai.slice(s, s + len).map((v) => theo[v][0]);
          ra.push({ type: "loc", cards: cards, score: diem("loc", cards) });
        }
      }
    }
    return ra.sort((a, b) => b.score - a.score);
  }

  /** Mọi nhóm `n` lá cùng bậc (đôi/sám), xếp điểm GIẢM DẦN. */
  function cacBoCungBac(hand, n, type) {
    const theo = gomTheoBac(hand);
    const ra = [];
    for (const v of Object.keys(theo)) {
      if (theo[v].length >= n) {
        const cards = theo[v].slice(0, n);
        ra.push({ type: type, cards: cards, score: diem(type, cards) });
      }
    }
    return ra.sort((a, b) => b.score - a.score);
  }

  /** Mọi lá đơn, xếp GIẢM DẦN. */
  function cacLaDon(hand) {
    return sortCards(hand).reverse().map((c) => ({
      type: "single", cards: [c], score: diem("single", [c]),
    }));
  }

  // ===================== PHÂN LOẠI & SO SÁNH =====================

  function cungBac(cards) {
    if (!cards.length) return false;
    const v = getCardVal(cards[0]);
    for (let i = 1; i < cards.length; i++) if (getCardVal(cards[i]) !== v) return false;
    return true;
  }

  /** Kiểu bài của một nhóm lá, hoặc null nếu không hợp lệ.
   *
   * Không nhận tứ quý và ba đôi thông — Sunwin không có bom, xem đầu file.
   */
  function phanLoai(cards) {
    if (!cards || !cards.length) return null;
    const n = cards.length;
    if (n === 1) return { type: "single", cards: cards, hi: cards[0], len: 1 };
    if (n === 2 && cungBac(cards)) {
      return { type: "pair", cards: cards, hi: laDinh(cards), len: 2 };
    }
    if (n === 3 && cungBac(cards)) {
      return { type: "trips", cards: cards, hi: laDinh(cards), len: 3 };
    }
    if (isStraight(cards)) {
      return { type: "loc", cards: cards, hi: laDinh(cards), len: n };
    }
    return null;
  }

  /** `a` có đè được `b` không: cùng kiểu, sảnh phải cùng độ dài, lá đỉnh lớn hơn. */
  function beats(a, b) {
    if (!a || !b || a.type !== b.type) return false;
    if (a.type === "loc" && a.cards.length !== b.cards.length) return false;
    return compareCards(a.hi, b.hi) > 0;
  }

  // ===================== HAI NƯỚC ĐI =====================

  /** Lượt tự do: sảnh -> sám -> đôi -> lá đơn, mỗi loại lấy TO NHẤT. */
  function chooseLead(hand) {
    if (!hand || !hand.length) return null;
    const sanh = cacSanh(hand);
    if (sanh.length) return sanh[0].cards;
    const sam = cacBoCungBac(hand, 3, "trips");
    if (sam.length) return sam[0].cards;
    const doi = cacBoCungBac(hand, 2, "pair");
    if (doi.length) return doi[0].cards;
    const don = cacLaDon(hand);
    return don.length ? don[0].cards : null;
  }

  /** Lượt đè: cùng kiểu với bàn, đánh nước TO NHẤT đè được; không có thì null. */
  function chooseFollow(hand, tableCards) {
    if (!hand || !hand.length) return null;
    const ban = phanLoai(tableCards);
    if (!ban) return null;

    let ung = [];
    if (ban.type === "loc") {
      ung = cacSanh(hand).filter((x) => x.cards.length === ban.cards.length);
    } else if (ban.type === "trips") {
      ung = cacBoCungBac(hand, 3, "trips");
    } else if (ban.type === "pair") {
      ung = cacBoCungBac(hand, 2, "pair");
    } else {
      ung = cacLaDon(hand);
    }

    for (const x of ung) {
      const t = phanLoai(x.cards);
      if (t && beats(t, ban)) return x.cards;
    }
    return null;
  }

  /** Cửa duy nhất cho content_main.js: có bài trên bàn thì đè, không thì dẫn. */
  function chooseBestPlay(hand, tableCards) {
    if (tableCards && tableCards.length) return chooseFollow(hand, tableCards);
    return chooseLead(hand);
  }

  const api = {
    getCardVal: getCardVal,
    getCardSuit: getCardSuit,
    compareCards: compareCards,
    sortCards: sortCards,
    isStraight: isStraight,
    phanLoai: phanLoai,
    beats: beats,
    diem: diem,
    cacSanh: cacSanh,
    cacBoCungBac: cacBoCungBac,
    cacLaDon: cacLaDon,
    chooseLead: chooseLead,
    chooseFollow: chooseFollow,
    chooseBestPlay: chooseBestPlay,
  };

  root.AutoToolCards = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);

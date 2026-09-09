// content_main.js — AutoTool V3 (Main World Context)
// Intercept WebSocket game Cocos/Wasm, ghi nhận room/cards và thực thi lệnh trực tiếp 2 chiều.
(function () {
  const G = globalThis;
  if (G.__ws_main_hooked) return;
  G.__ws_main_hooked = true;
  G.__ws_hooked = true;
  G.__ws_capture = [];
  G.__ws_instances = [];
  G.__last_room_info = null;
  G.__room_players = [];
  G.__room_state = 0;
  G.__my_cards = [];
  G.__last_table_cards = null;
  G.__last_table_player = null;
  G.__game_in_progress = false;
  G.__partner_cards_count = 13;
  // MẶC ĐỊNH TẮT. Chỉ controller được bật (theo tuỳ chọn 'Tự động xả bài').
  // Trước đây mặc định true: tab vừa nạp đã ở trạng thái sẵn sàng tự đánh,
  // chỉ còn cổng isAutoEngaged() chặn — mất một lớp phòng vệ không cần thiết.
  G.__AUTOTOOL_AUTO_DISCARD = false;
  // RỖNG cho tới khi controller đồng bộ danh sách thật xuống (SYNC_PARTNERS).
  // Trước đây đây là danh sách cứng trộn lẫn tên đăng nhập, tên in-game và tên
  // profile ("profile1", "account01"). Vì so khớp hồi đó dùng chuỗi con, một
  // người chơi thật tên `myprofile123` cũng khớp `profile1` -> bị coi là đồng
  // đội -> tool cố tình đánh nhẹ cho họ ăn. Danh sách thật nay lấy từ
  // `character_name` trong database (Check Live đọc về).
  G.__autotool_partners = [];

  // ---- MODULE PHÂN TÍCH & GIẢI MÃ 52 LÁ BÀI TIẾN LÊN (0..51) ----
  function getCardVal(c) {
    const r = Math.floor(c / 4);
    if (r >= 2) return r + 1; // 2->3, 3->4, ..., 12->13 (K)
    if (r === 0) return 14;   // A
    if (r === 1) return 15;   // 2 (Heo)
    return 0;
  }

  function getCardSuit(c) {
    return c % 4; // 0: Bích, 1: Chuồn, 2: Rô, 3: Cơ
  }

  function sortCards(cards) {
    return (cards || []).slice().sort((a, b) => {
      const va = getCardVal(a), vb = getCardVal(b);
      if (va !== vb) return va - vb;
      return getCardSuit(a) - getCardSuit(b);
    });
  }

  function compareCards(c1, c2) {
    const v1 = getCardVal(c1), v2 = getCardVal(c2);
    if (v1 !== v2) return v1 - v2;
    return getCardSuit(c1) - getCardSuit(c2);
  }

  function parseCard(c) {
    if (typeof c !== "number" || c < 0 || c > 51) return null;
    const rawRank = Math.floor(c / 4);
    const suitIndex = c % 4;
    const rankNames = {
      2: "3", 3: "4", 4: "5", 5: "6", 6: "7", 7: "8", 8: "9", 9: "10",
      10: "J", 11: "Q", 12: "K", 0: "A", 1: "2"
    };
    const suitIcons = ["♠", "♣", "♦", "♥"];
    const suitNames = ["Bích", "Chuồn", "Rô", "Cơ"];
    const isRed = (suitIndex === 2 || suitIndex === 3);
    const rank = rankNames[rawRank] || "?";
    const icon = suitIcons[suitIndex] || "";
    return {
      id: c,
      rank: rank,
      suit: suitNames[suitIndex],
      icon: icon,
      isRed: isRed,
      name: rank + icon,
    };
  }

  function isStraight(cards) {
    if (!cards || cards.length < 3) return false;
    const sc = sortCards(cards);
    if (sc.some((c) => getCardVal(c) === 15)) return false; // Không tính Heo
    for (let i = 1; i < sc.length; i++) {
      if (getCardVal(sc[i]) !== getCardVal(sc[i - 1]) + 1) return false;
    }
    return true;
  }

  function canBeat(cand, table) {
    if (!cand || !table || !cand.length || !table.length) return false;
    const scCand = sortCards(cand);
    const scTab = sortCards(table);

    // 1 vs 1 (Rác đè Rác)
    if (cand.length === 1 && table.length === 1) {
      return compareCards(cand[0], table[0]) > 0;
    }
    // Tứ quý chặt Heo đơn
    if (cand.length === 4 && table.length === 1) {
      const isQuad = (getCardVal(cand[0]) === getCardVal(cand[1]) && 
                      getCardVal(cand[1]) === getCardVal(cand[2]) && 
                      getCardVal(cand[2]) === getCardVal(cand[3]));
      const isTwo = (getCardVal(table[0]) === 15);
      if (isQuad && isTwo) return true;
    }
    // Đôi đè Đôi
    if (cand.length === 2 && table.length === 2) {
      const isP1 = getCardVal(cand[0]) === getCardVal(cand[1]);
      const isP2 = getCardVal(table[0]) === getCardVal(table[1]);
      if (isP1 && isP2) {
        return compareCards(scCand[1], scTab[1]) > 0;
      }
    }
    // Ba đè Ba
    if (cand.length === 3 && table.length === 3) {
      const isT1 = (getCardVal(cand[0]) === getCardVal(cand[1]) && getCardVal(cand[1]) === getCardVal(cand[2]));
      const isT2 = (getCardVal(table[0]) === getCardVal(table[1]) && getCardVal(table[1]) === getCardVal(table[2]));
      if (isT1 && isT2) {
        return compareCards(scCand[2], scTab[2]) > 0;
      }
    }
    // Sảnh đè Sảnh (cùng số lá)
    if (cand.length === table.length && cand.length >= 3) {
      if (isStraight(cand) && isStraight(table)) {
        return compareCards(scCand[scCand.length - 1], scTab[scTab.length - 1]) > 0;
      }
    }
    return false;
  }

  function findCombinations(cards) {
    const sortedC = sortCards(cards);
    const valMap = {};
    for (const c of sortedC) {
      const v = getCardVal(c);
      if (!valMap[v]) valMap[v] = [];
      valMap[v].push(c);
    }

    const straights = [];
    const nonTwoVals = Object.keys(valMap).map(Number).filter((v) => v < 15).sort((a, b) => a - b);
    for (let len = nonTwoVals.length; len >= 3; len--) {
      for (let start = 0; start <= nonTwoVals.length - len; start++) {
        const sub = nonTwoVals.slice(start, start + len);
        let valid = true;
        for (let i = 1; i < sub.length; i++) {
          if (sub[i] !== sub[i - 1] + 1) { valid = false; break; }
        }
        if (valid) {
          straights.push(sub.map((v) => valMap[v][0]));
        }
      }
    }

    const quads = Object.values(valMap).filter((cs) => cs.length >= 4).map((cs) => cs.slice(0, 4));
    const triples = Object.values(valMap).filter((cs) => cs.length >= 3).map((cs) => cs.slice(0, 3));
    const pairs = Object.values(valMap).filter((cs) => cs.length >= 2).map((cs) => cs.slice(0, 2));
    const singles = sortedC.map((c) => [c]);

    return { straights, quads, triples, pairs, singles };
  }

  // Account phụ không được bẻ một tổ hợp chỉ để đánh nhanh một lá.  Khi có
  // lá lẻ thật sự thì mồi lá lẻ nhỏ nhất; nếu không có (ví dụ chỉ còn đôi 10)
  // thì đánh nguyên tổ hợp nhỏ nhất để chắc chắn có một lượt đánh hợp lệ.
  function chooseDumpOpening(myCards, combs) {
    const sorted = sortCards(myCards);
    const rankCounts = new Map();
    for (const card of sorted) {
      const rank = getCardVal(card);
      rankCounts.set(rank, Number(rankCounts.get(rank) || 0) + 1);
    }

    // Một lá nằm trong sảnh cũng được xem là lá cần giữ, không coi là rác.
    const looseSingle = getLooseSingles(sorted, combs, rankCounts)[0];
    if (looseSingle !== undefined) return [looseSingle];

    const lowestGroup = (groups) => groups.slice().sort((left, right) => {
      const leftSorted = sortCards(left);
      const rightSorted = sortCards(right);
      const leftHigh = leftSorted[leftSorted.length - 1];
      const rightHigh = rightSorted[rightSorted.length - 1];
      return compareCards(leftHigh, rightHigh);
    })[0];

    // Không lấy pair được suy ra từ bộ ba/tứ quý, vì như vậy lại xé tổ hợp.
    const exactGroups = (groups, exactSize) => groups.filter((group) =>
      rankCounts.get(getCardVal(group[0])) === exactSize
    );
    // Đôi trước là tình huống quan trọng: đôi 10 phải đánh thành đôi 10,
    // không tách thành một lá 10 khiến Account phụ thối bài.
    if (exactGroups(combs.pairs, 2).length) return lowestGroup(exactGroups(combs.pairs, 2));
    if (exactGroups(combs.triples, 3).length) return lowestGroup(exactGroups(combs.triples, 3));
    if (combs.straights.length) return lowestGroup(combs.straights);
    // Giữ tứ quý tới cuối để không tự tạo một lượt chặt/phạt không cần thiết.
    if (combs.quads.length) return lowestGroup(combs.quads);
    return [sorted[0]];
  }

  function getLooseSingles(cards, combs, knownRankCounts) {
    const sorted = sortCards(cards);
    const rankCounts = knownRankCounts || new Map();
    if (!knownRankCounts) {
      for (const card of sorted) {
        const rank = getCardVal(card);
        rankCounts.set(rank, Number(rankCounts.get(rank) || 0) + 1);
      }
    }
    const protectedCards = new Set();
    for (const group of [...combs.straights, ...combs.quads, ...combs.triples, ...combs.pairs]) {
      for (const card of group) protectedCards.add(card);
    }
    return sorted.filter((card) =>
      rankCounts.get(getCardVal(card)) === 1 && !protectedCards.has(card)
    );
  }

  // Chỉ Account chính mới mở chuỗi lá lẻ khi đọc được bài của Account phụ và
  // chứng minh được đường chuyển lượt: Anchor thấp < Phụ < Anchor cao hơn.
  // Nếu thiếu bất kỳ mắt xích nào, trả null để dùng lại chiến lược tổ hợp.
  function chooseVerifiedSingleRelay(myCards, partnerCards) {
    if (!Array.isArray(partnerCards) || partnerCards.length === 0) return null;
    const myCombs = findCombinations(myCards);
    const partnerCombs = findCombinations(partnerCards);
    const myLoose = getLooseSingles(myCards, myCombs);
    const partnerLoose = getLooseSingles(partnerCards, partnerCombs);

    for (const lead of myLoose) {
      const partnerReply = partnerLoose.find((card) => canBeat([card], [lead]));
      if (partnerReply === undefined) continue;
      const anchorCover = myLoose.find((card) => card !== lead && canBeat([card], [partnerReply]));
      if (anchorCover !== undefined) {
        console.log(`[AutoTool V3] [RELAY] Xác minh chuỗi lá lẻ ${lead} < ${partnerReply} < ${anchorCover}.`);
        return [lead];
      }
    }
    return null;
  }

  function getMyRole() {
    if (G.__AUTOTOOL_ROLE) return G.__AUTOTOOL_ROLE;
    const pName = ((G.__my_dn || "") + " " + (getProfileName() || "")).toLowerCase();
    if (pName.includes("2") || pName.includes("sub") || pName.includes("phu") || pName.includes("xabai2") || pName.includes("dump")) {
      return "dump";
    }
    return "winner";
  }

  /** CỔNG KÍCH HOẠT DUY NHẤT cho MỌI hành động tự động.
   *
   * Nguyên tắc: khi người dùng CHƯA bấm "GOM BÀN & XẢ", hoặc ĐÃ bấm Dừng, thì
   * tool phải im hoàn toàn — profile hoạt động y như người thật thao tác tay.
   * Không tự rời bàn, không tự đánh bài, không tự Sẵn sàng/Bắt đầu.
   *
   * Trước đây không có cổng này: các nhánh tự động nằm rải rác trong handler
   * cmd 202, mỗi nhánh tự canh một cờ khác nhau. Hậu quả thực tế:
   *  - Nhánh "Sai mức cược" chỉ canh `__target_hunt_bet > 0`. Mà cờ đó do một
   *    lượt gom bàn trước đó đặt và KHÔNG được xoá khi Dừng -> người dùng mở
   *    account chơi tay, vào bàn khác mức cược là bị tự out.
   *  - `__AUTOTOOL_AUTO_DISCARD` cũng không được xoá khi Dừng -> vẫn tự đánh.
   *
   * `__AUTOTOOL_ENGAGED` do controller bật ở đầu mỗi lượt chạy và tắt khi Dừng.
   * Hai cờ còn lại giữ để tương thích ngược với controller bản cũ.
   */
  function isAutoEngaged() {
    try {
      if (localStorage.getItem("AUTOTOOL_STOPPED") === "1") return false;
    } catch (_) {}
    return !!(G.__AUTOTOOL_ENGAGED || G.__AUTOTOOL_ARMED || G.__AUTOTOOL_AUTO_HUNT);
  }

  /** Xoá sạch cấu hình của một lượt gom bàn. Phải gọi khi Dừng/DISARM/đăng xuất,
   * nếu không state cũ sẽ điều khiển hành vi ở những lần chơi tay sau đó. */
  function clearRunConfig() {
    G.__AUTOTOOL_ENGAGED = false;
    G.__AUTOTOOL_AUTO_DISCARD = false;
    G.__auto_start_guest_ss = false;
    G.__target_hunt_bet = 0;
    G.__target_hunt_mu = 0;
    G.__AUTOTOOL_MATCH_ROLE = null;
    G.__AUTOTOOL_ROLE = null;
    G.__AUTOTOOL_PARTNER_PROFILES = [];
    G.__autotool_partners = [];
    G.__AUTOTOOL_SUB_JOIN_TICKET = null;
    G.__active_room_invite = null;
  }

  // Vai trò ghép bàn do backend ấn định cho từng lượt chạy.  Không suy đoán
  // bằng tên profile khi controller đã biết chính xác account nào là anchor:
  // tên nick có chữ/số "1" hoặc "2" rất dễ làm đảo chiều điều phối.
  /** Đang chờ đồng đội vào bàn -> TUYỆT ĐỐI không được bắt đầu ván với người lạ.
   *
   * Thay cho `huntModeActive`, vốn đã CHẾT: nó đọc `__AUTOTOOL_AUTO_HUNT`, mà
   * luồng gom bàn hiện tại đặt cờ đó = false trên MỌI trang (controller tự
   * điều phối join). Nên điều kiện `!huntModeActive` luôn đúng, và lớp gác mà
   * chú thích tuyên bố là "không bao giờ bắt đầu với khách lạ" thực tế không
   * gác gì cả.
   *
   * Điều kiện SỐNG: có đồng đội trong danh sách đã xác minh, mà chưa ai trong
   * số họ ngồi xuống bàn này.
   */
  function dangChoDongDoi() {
    try {
      const ds = G.__autotool_partners || [];
      if (!ds.length) return false;
      if (G.__is_matched_locked) return false;
      const ngoi = (G.__room_players || []).some(isPartner);
      return !ngoi;
    } catch (e) {
      return true;   // không chắc thì coi như đang chờ — hỏng an toàn
    }
  }

  function isSubMatchProfile() {
    if (G.__AUTOTOOL_MATCH_ROLE === "anchor") return false;
    if (G.__AUTOTOOL_MATCH_ROLE === "sub") return true;
    const pName = (getProfileName() || "").toLowerCase();
    return pName.includes("2") || pName.includes("sub") || pName.includes("phu") ||
      pName.includes("xabai2") || pName.includes("dump") || getMyRole() === "dump";
  }

  function isAnchorMatchProfile() {
    if (G.__AUTOTOOL_MATCH_ROLE === "anchor") return true;
    if (G.__AUTOTOOL_MATCH_ROLE === "sub") return false;
    return (getProfileName() || "").toLowerCase().includes("1") || !!G.__is_hunt_initiator;
  }

  function findBestPlay(myCards, tableCards, role, isPartnerTurn) {
    if (!myCards || !myCards.length) return null;
    const combs = findCombinations(myCards);

    // 1. LƯỢT TỰ DO (Free Turn / Mở ván hoặc đối phương vừa Bỏ lượt) -> BẮT BUỘC ĐÁNH BÀI RA
    if (!tableCards || tableCards.length === 0) {
      if (role === "dump") {
        // ĐẢO CHIỀU ƯU TIÊN so với Account chính: phụ tống lá NGUY HIỂM
        // (Heo / lá cao) đi TỪ SỚM để cuối ván không còn gì bị phạt, chỉ giữ
        // lại vài lá thấp nhất làm mồi cho chính đè và giành quyền dẫn.
        // Chính thì ngược lại — chọn nhỏ nhất, giữ lá cao để còn đè được.
        const reserve = Number.isFinite(G.__AUTOTOOL_DUMP_RESERVE)
          ? G.__AUTOTOOL_DUMP_RESERVE : undefined;
        const cardsApi = (typeof AutoToolCards !== "undefined") ? AutoToolCards : (G.AutoToolCards || null);
        if (cardsApi && typeof cardsApi.chooseDumpDischarge === "function") {
          try {
            // Truyền bài đồng đội: ưu tiên lá cao mà CHÍNH CÒN ĐÈ ĐƯỢC,
            // giữ nhịp tiếp sức. Không có ràng buộc này thì phụ hay tống
            // ngay Heo — mà Heo đơn chỉ tứ quý mới chặt, chính mất quyền dẫn.
            const discharge = cardsApi.chooseDumpDischarge(myCards, reserve, G.__partner_cards);
            if (discharge && discharge.length) {
              console.log(`[AutoTool V3] [Role: DUMP] Xả lá nguy hiểm trước: [${discharge.join(", ")}] (giữ lại ${reserve === undefined ? cardsApi.DEFAULT_RESERVE : reserve} lá thấp để mồi).`);
              return discharge;
            }
          } catch (e) {
            console.warn("[AutoTool V3] chooseDumpDischarge lỗi, dùng lại chiến lược cũ:", e);
          }
        }
        // Chỉ còn phần giữ lại -> chuyển sang chế độ MỒI lá thấp cho chính đè.
        const opening = chooseDumpOpening(myCards, combs);
        console.log(`[AutoTool V3] [Role: DUMP] Mồi lá thấp cho Account chính: [${opening.join(", ")}].`);
        return opening;
      } else {
        const relayLead = chooseVerifiedSingleRelay(myCards, G.__partner_cards);
        if (relayLead) return relayLead;

        // Account 1 (Chính): XẢ SẠCH BÀI VỀ NHẤT -> mục tiêu là ÍT LƯỢT NHẤT.
        // Dùng phân rã tối ưu (quy hoạch động trên đa tập bậc, card_logic.js)
        // thay cho chuỗi tham lam "sảnh dài nhất -> tứ quý -> ba -> đôi".
        // Tham lam có thể xé nhầm: lấy sảnh dài nhất đôi khi phá mất một sảnh
        // thứ hai hoặc một đôi, làm tăng tổng số lượt.
        // Đánh nhóm THẤP nhất trước để giữ lá cao mà giành lại quyền dẫn.
        const planner = (typeof AutoToolCards !== "undefined") ? AutoToolCards
          : (G.AutoToolCards || null);

        // ĐẾM BÀI: mọi lá đã ra bàn đều công khai. 52 lá trừ (bài mình + lá đã
        // ra) = tập còn ẩn. Nếu MỌI nhóm trong phân rã đều không ai chặn được
        // nữa thì cứ đánh lần lượt là đi hết bài — chắc thắng, không may rủi.
        if (planner && typeof planner.analyzeControl === "function") {
          try {
            const ctrl = planner.analyzeControl(myCards, G.__cards_played || []);
            if (ctrl && ctrl.melds && ctrl.melds.length) {
              if (ctrl.allUnbeatable) {
                console.log(`[AutoTool V3] [Role: WINNER] ✅ CHẮC THẮNG: cả ${ctrl.melds.length} nhóm đều không ai chặn được (còn ẩn ${ctrl.unseen} lá) -> chạy hết bài.`);
                return ctrl.melds[0].cards;
              }
              console.log(`[AutoTool V3] [Role: WINNER] Phân rã ${ctrl.turns} lượt, ${ctrl.sureCount}/${ctrl.melds.length} nhóm chắc thắng (còn ẩn ${ctrl.unseen} lá).`);
              // Ưu tiên nhóm KHÔNG BỊ CHẶN: đánh ra là chắc chắn giữ được
              // quyền dẫn, không phải đánh cược mất lượt.
              const sure = ctrl.melds.find((m) => m.unbeatable);
              if (sure) return sure.cards;
              return ctrl.melds[0].cards;
            }
          } catch (e) {
            console.warn("[AutoTool V3] analyzeControl lỗi, lùi về phân rã thường:", e);
          }
        }
        if (planner && typeof planner.planMinTurns === "function") {
          try {
            const plan = planner.planMinTurns(myCards);
            if (plan && plan.melds && plan.melds.length) {
              console.log(`[AutoTool V3] [Role: WINNER] Phân rã tối ưu ${plan.turns} lượt, đánh [${plan.melds[0].join(", ")}].`);
              return plan.melds[0];
            }
          } catch (e) {
            console.warn("[AutoTool V3] planMinTurns lỗi, dùng lại chiến lược cũ:", e);
          }
        }
        // Dự phòng khi card_logic.js chưa nạp được
        if (combs.straights.length > 0) return combs.straights[0];
        if (combs.quads.length > 0) return combs.quads[0];
        if (combs.triples.length > 0) return combs.triples[0];
        if (combs.pairs.length > 0) return combs.pairs[0];
        return [sortCards(myCards)[0]];
      }
    }

    // 2. LƯỢT ĐÈ BÀI (Follow Turn)
    if (isPartnerTurn) {
      if (role === "dump") {
        // Account phụ được phép đè ĐÚNG MỘT lần trong ván nếu chưa hề đánh.
        // Nhờ vậy không bị "thua trắng", nhưng vẫn chỉ dùng tổ hợp nhỏ nhất
        // hợp lệ để Account chính đè lại và giữ nhịp xả bài. Không dùng tứ quý
        // / chặt để tránh đảo nhịp hoặc tăng mức phạt không cần thiết.
        // ƯU TIÊN 1: còn NHIỀU HƠN phần giữ -> đè bằng tổ hợp CAO NHẤT.
        // Mượn chính lượt của Account chính làm cơ hội xả lá nguy hiểm; chỉ khi
        // đã tụt về đúng 3-4 lá thấp mới thôi đè và chuyển sang mồi để Account
        // chính giành lại quyền dẫn rồi đi hết bài.
        {
          const reserveBeat = Number.isFinite(G.__AUTOTOOL_DUMP_RESERVE)
            ? G.__AUTOTOOL_DUMP_RESERVE : undefined;
          const api = (typeof AutoToolCards !== "undefined") ? AutoToolCards : (G.AutoToolCards || null);
          if (api && typeof api.chooseDumpBeat === "function") {
            try {
              const beat = api.chooseDumpBeat(myCards, tableCards, reserveBeat, G.__partner_cards);
              if (beat && beat.length) {
                console.log(`[AutoTool V3] [Role: DUMP] Đè lá cao để xả nguy hiểm: [${beat.join(", ")}] (còn ${myCards.length} lá).`);
                return beat;
              }
            } catch (e) {
              console.warn("[AutoTool V3] chooseDumpBeat lỗi, dùng lại chiến lược cũ:", e);
            }
          }
        }

        const hasPlayedThisRound = Number(G.__autotool_round_play_count || 0) > 0;
        if (!hasPlayedThisRound) {
          const tLen = tableCards.length;
          let cands = [];
          // Ở relay lá lẻ chỉ dùng lá không thuộc tổ hợp. Nếu không có lá phù
          // hợp thì bỏ lượt để giữ đôi/ba/sảnh, rồi dùng nhánh tổ hợp ở lượt
          // có cùng số lá.
          if (tLen === 1) cands = getLooseSingles(myCards, combs).map((card) => [card]);
          else if (tLen === 2) cands = combs.pairs;
          else if (tLen === 3) cands = combs.triples;
          else if (tLen >= 3 && isStraight(tableCards)) cands = combs.straights.filter((s) => s.length === tLen);
          for (const cand of cands) {
            if (canBeat(cand, tableCards)) {
              console.log(`[AutoTool V3] [Role: DUMP] Giảm thua trắng: đè 1 lần bằng [${cand.join(", ")}], sau đó nhường lại Account chính.`);
              return cand;
            }
          }
        }
        console.log("[AutoTool V3] [Role: DUMP] Đã đánh trong ván hoặc không có bài đè an toàn -> PASS nhường Account chính.");
        return null;
      } else {
        // Account 1 (Chính): BẮT BUỘC ĐÈ BÀI ĐỒNG ĐỘI ĐỂ GIÀNH LƯỢT ĐI TỰ DO!
        const tLen = tableCards.length;
        let cands = [];
        if (tLen === 1) {
          cands = combs.singles;
        } else if (tLen === 2) {
          cands = combs.pairs;
        } else if (tLen === 3) {
          cands = combs.triples;
        } else if (tLen >= 3 && isStraight(tableCards)) {
          cands = combs.straights.filter((s) => s.length === tLen);
        }

        const beatable = cands.filter((c) => canBeat(c, tableCards));

        // ĐẾM BÀI: trong số nước đè được, ưu tiên nước KHÔNG AI CHẶN LẠI ĐƯỢC.
        // Đè xong mà bị người khác đè tiếp thì mất quyền dẫn — đúng thứ đang
        // cần giành. Nhóm bất khả chặn bảo đảm giữ được lượt.
        if (beatable.length) {
          const api = (typeof AutoToolCards !== "undefined") ? AutoToolCards : (G.AutoToolCards || null);
          if (api && typeof api.canAnyoneBeat === "function") {
            try {
              const unseen = api.unseenCards(myCards, G.__cards_played || []);
              const safe = beatable.find((c) => !api.canAnyoneBeat(c, unseen));
              if (safe) {
                console.log(`[AutoTool V3] [Role: WINNER] Đè bằng [${safe.join(", ")}] — không ai chặn lại được, chắc giữ quyền dẫn.`);
                return safe;
              }
            } catch (e) {
              console.warn("[AutoTool V3] canAnyoneBeat lỗi ở nhánh đè:", e);
            }
          }
          console.log(`[AutoTool V3] [Role: WINNER] Đè bài đồng đội bằng [${beatable[0].join(", ")}] để giành lượt!`);
          return beatable[0];
        }

        // Tứ quý chặt Heo đơn nếu đồng đội lỡ đánh Heo
        if (tLen === 1 && getCardVal(tableCards[0]) === 15 && combs.quads.length > 0) {
          console.log("[AutoTool V3] [Role: WINNER] Dùng Tứ quý chặt Heo đơn đồng đội để giành lượt!");
          return combs.quads[0];
        }

        console.log("[AutoTool V3] [Role: WINNER] Không có bài đè được -> Bỏ lượt.");
        return null;
      }
    } else {
      // Đánh với khách lạ: Tìm nhóm nhỏ nhất đè được
      const tLen = tableCards.length;
      let cands = [];
      if (tLen === 1) cands = combs.singles;
      else if (tLen === 2) cands = combs.pairs;
      else if (tLen === 3) cands = combs.triples;
      else if (tLen >= 3 && isStraight(tableCards)) cands = combs.straights.filter((s) => s.length === tLen);

      for (const cand of cands) {
        if (canBeat(cand, tableCards)) return cand;
      }
      return null;
    }
  }

  // ===== #1 ADAPTIVE BACKOFF (TRÁNH RATE LIMIT THÔNG MINH) =====
  class AdaptiveBackoff {
    constructor(baseMs = 2200, maxMs = 8000) {
      this.baseMs = baseMs;
      this.maxMs = maxMs;
      this.factor = 1.5;
      this.current = this.baseMs;
      this.successCount = 0;
    }
    onSuccess() {
      this.successCount++;
      if (this.successCount >= 3) {
        this.current = Math.max(this.baseMs, Math.round(this.current * 0.8));
        this.successCount = 0;
      }
    }
    onFailure(isRateLimit = false) {
      this.current = Math.min(this.maxMs, Math.round(this.current * (isRateLimit ? 2.5 : this.factor)));
      this.successCount = 0;
    }
    next() {
      return Math.round(this.current + Math.random() * 500);
    }
  }
  G.__backoff = G.__backoff || new AdaptiveBackoff();

  // ===== #7 GAUSSIAN TIMING (MÔ PHỎNG THAO TÁC NGƯỜI THẬT) =====
  function humanDelay(minMs = 450, maxMs = 950) {
    const u1 = Math.random() || 1e-10;
    const u2 = Math.random();
    const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    const mean = (minMs + maxMs) / 2;
    const std = (maxMs - minMs) / 6; // 99.7% rơi vào khoảng [minMs, maxMs]
    return Math.max(minMs, Math.min(maxMs, Math.round(mean + z * std)));
  }


  // ===== CÁC HÀM TIỆN ÍCH ĐỊNH DANH & BẮT BÀN ĐỒNG BỘ TOÀN CỤC (TOP-LEVEL SCOPE) =====
  function cleanUid(s) {
    return String(s || "").replace(/\D/g, "");
  }

  function isMe(x) {
    if (!x) return false;

    // 1. Chỉ người chơi hiện tại mới nhận được mảng bài trên tay private từ server
    if (Array.isArray(x.cs) && x.cs.length > 0) return true;

    // 2. Khớp theo UID số định danh duy nhất
    const targetUid = cleanUid(x.uid);
    const myUid = cleanUid(G.__my_uid);
    if (myUid && targetUid && targetUid === myUid) return true;

    // 3. Khớp theo Display Name in-game (dn)
    const d1 = String(x.dn || "").trim().toLowerCase();
    if (G.__my_dn) {
      const d2 = String(G.__my_dn).trim().toLowerCase();
      if (d1 && d2 && d1 === d2) return true;
    }

    // 4. Khớp theo Username in-game (u)
    const u1 = String(x.u || "").trim().toLowerCase();
    if (G.__my_u) {
      const u2 = String(G.__my_u).trim().toLowerCase();
      if (u1 && u2 && u1 === u2) return true;
    }

    // 5. Khớp theo dữ liệu lưu trữ bền vững trong localStorage
    try {
      const savedDn = String(localStorage.getItem("AUTOTOOL_IN_GAME_DN") || "").trim().toLowerCase();
      if (savedDn && d1 && d1 === savedDn) return true;
      const savedU = String(localStorage.getItem("AUTOTOOL_IN_GAME_U") || "").trim().toLowerCase();
      if (savedU && u1 && u1 === savedU) return true;
    } catch (_) {}

    return false;
  }

  // Xác định đồng đội: uỷ quyền cho partner_id.js (thuần, kiểm thử bằng node).
  //
  // Bản trước đoán theo HÌNH DẠNG TÊN — cắt số đuôi, gộp ký tự lặp, so chuỗi
  // con hai chiều. Với tên in-game `nicktestxxabai1` (gốc `nicktestxabai`),
  // mọi người chơi tên `ai2`, `i3`, `nick9`, `bai3`, `test5`… đều thành "đồng
  // đội": 10/15 tên thử bị nhận nhầm. Mà nhận nhầm nghĩa là tool cố tình đánh
  // nhẹ / bỏ lượt cho một người lạ ăn.
  //
  // Nay chỉ khớp CHÍNH XÁC trên danh tính đã xác minh (dn / u / uid). Thiếu
  // danh tính thì trả false — mất phối hợp còn hơn nạp bài cho khách lạ.
  function isPartner(x) {
    if (!x || isMe(x)) return false;
    const P = G.AutoToolPartner;
    if (!P || typeof P.laDongDoi !== "function") {
      // partner_id.js chưa nạp -> KHÔNG đoán bừa.
      if (!G.__canh_bao_thieu_partner_id) {
        G.__canh_bao_thieu_partner_id = true;
        console.warn("[AutoTool V3] Thiếu partner_id.js — không xác định đồng đội, đánh như người thường.");
      }
      return false;
    }
    return P.laDongDoi(x, {
      partners: G.__autotool_partners || [],
      expected: {
        dn: G.__expected_anchor_dn,
        u: G.__expected_anchor_u,
        uid: G.__expected_anchor_uid,
        profile_name: G.__expected_anchor_profile,
      },
      invite: G.__active_room_invite,
    });
  }

  // Helper quét và kích hoạt Sẵn Sàng / Bắt Đầu: Cocos Native + Event + Canvas Pointer Click
  function execCocosReadyOrStart() {
    let executed = false;
    // 1. Quét scene Cocos Creator
    try {
      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene) {
          function walk(node, depth) {
            if (!node || depth > 50 || executed) return;
            const comps = (typeof node.getComponents === "function") ? node.getComponents(cc.Component) : (node._components || []);
            for (let i = 0; i < comps.length; i++) {
              const c = comps[i];
              if (!c) continue;
              if (typeof c.sendReady === "function") {
                try {
                  console.log("[AutoTool V3] >>> Cocos: Gọi native component.sendReady()! <<<");
                  c.sendReady();
                  executed = true;
                  if (c.btn_begin && c.btn_begin.node) {
                    c.btn_begin.node.active = false;
                  }
                  return;
                } catch (err) {
                  console.warn("[AutoTool V3] Lỗi c.sendReady():", err);
                }
              }
              if (c.btn_begin && c.btn_begin.node && c.btn_begin.node.active) {
                try {
                  console.log("[AutoTool V3] >>> Cocos: Kích hoạt clickEvents trên btn_begin! <<<");
                  if (typeof cc.Component !== "undefined" && cc.Component.EventHandler && c.btn_begin.clickEvents) {
                    cc.Component.EventHandler.emitEvents(c.btn_begin.clickEvents, c.btn_begin);
                    executed = true;
                    return;
                  }
                } catch (_) {}
                try {
                  if (typeof cc.Node !== "undefined" && cc.Node.EventType) {
                    c.btn_begin.node.emit(cc.Node.EventType.TOUCH_END);
                    executed = true;
                    return;
                  }
                } catch (_) {}
              }

              // 3. Quét nhãn text SẴN SÀNG hoặc BẮT ĐẦU trên mọi node / button đang active
              const labelStr = (c.string || c._string || (c.label && c.label.string) || "").toUpperCase();
              if (labelStr.includes("SẴN SÀNG") || labelStr.includes("BẮT ĐẦU") || labelStr.includes("SAN SANG") || labelStr.includes("BAT DAU")) {
                if (node.active) {
                  console.log(`[AutoTool V3] >>> Cocos: Phát hiện nhãn '${labelStr}' trên node '${node.name}' -> Kích hoạt click! <<<`);
                  let parent = node;
                  while (parent && !(parent.getComponent && parent.getComponent("cc.Button")) && parent.parent) parent = parent.parent;
                  const btnComp = parent && parent.getComponent ? (parent.getComponent("cc.Button") || (typeof cc.Button !== "undefined" && parent.getComponent(cc.Button))) : null;
                  if (btnComp && btnComp.clickEvents && typeof cc.Component !== "undefined" && cc.Component.EventHandler) {
                    try { cc.Component.EventHandler.emitEvents(btnComp.clickEvents, btnComp); } catch (_) {}
                  }
                  try { if (typeof cc.Node !== "undefined" && cc.Node.EventType) (parent || node).emit(cc.Node.EventType.TOUCH_END); } catch (_) {}
                  executed = true;
                  return;
                }
              }
            }
            const children = node.children || [];
            for (let j = 0; j < children.length; j++) {
              walk(children[j], depth + 1);
              if (executed) return;
            }
          }
          walk(scene, 0);
        }
      }
    } catch (e) {
      console.warn("[AutoTool V3] Lỗi Cocos walk:", e);
    }

    // 2. Click vật lý DOM / Pointer / Mouse trực tiếp lên <canvas> tại tọa độ nút [ SẴN SÀNG ] / [ BẮT ĐẦU ] (50% X, 52.5% Y)
    try {
      const canvas = document.querySelector("canvas");
      if (canvas) {
        const rect = canvas.getBoundingClientRect();
        const clickX = rect.left + rect.width * 0.500;
        const clickY = rect.top + rect.height * 0.525;
        const opts = {
          bubbles: true,
          cancelable: true,
          clientX: clickX,
          clientY: clickY,
          view: window
        };
        canvas.dispatchEvent(new PointerEvent("pointerdown", opts));
        canvas.dispatchEvent(new MouseEvent("mousedown", opts));
        canvas.dispatchEvent(new PointerEvent("pointerup", opts));
        canvas.dispatchEvent(new MouseEvent("mouseup", opts));
        canvas.dispatchEvent(new MouseEvent("click", opts));
        console.log(`[AutoTool V3] >>> Đã dispatch Canvas Click vào [ SẴN SÀNG ] tại (${Math.round(clickX)}, ${Math.round(clickY)})! <<<`);
      }
    } catch (err) {
      console.warn("[AutoTool V3] Lỗi Canvas click:", err);
    }

    return executed;
  }

  // ===== CÁC HÀM TIỆN ÍCH ĐIỀU HƯỚNG SẢNH COCOS NATIVE (0MS, TRỰC TIẾP ENGINE) =====
  /** Node có THỰC SỰ hiển thị không.

   * Cocos ẩn UI bằng cách tắt node CHA (vd TLMNScene.active=false), còn node
   * con vẫn giữ active=true/opacity=255. Chỉ xét `node.active` sẽ nhận nhầm:
   * khi đứng ở SẢNH chọn bàn, cây scene đã dựng sẵn HUD bàn chơi nên các label
   * "BẮT ĐẦU"/"SẴN SÀNG" vẫn "active" -> isInsideGameTable() báo đang trong
   * bàn -> isAlreadyInTLDLLobby() luôn False -> "Không đưa được profile vào
   * sảnh" và vòng gom bàn không bao giờ gửi được lệnh join.
   * `activeInHierarchy` của Cocos đã tính sẵn cả chuỗi cha. */
  function isNodeVisible(node) {
    if (!node) return false;
    const alive = (node.activeInHierarchy !== undefined) ? node.activeInHierarchy : node.active;
    if (!alive) return false;
    return node.opacity === undefined || node.opacity > 0;
  }

  function getCocosNodeText(node) {
    if (!node) return "";
    try {
      const comps = (typeof node.getComponents === "function") ? node.getComponents(cc.Component) : (node._components || []);
      for (let i = 0; i < comps.length; i++) {
        const c = comps[i];
        if (!c) continue;
        const str = c.string || c._string || (c.label && c.label.string) || (c.richText && c.richText.string);
        if (typeof str === "string" && str.trim()) return str.trim();
      }
    } catch (_) {}
    return "";
  }

  function clickCocosNode(node) {
    if (!node) return false;
    let clicked = false;
    try {
      let parent = node;
      while (parent && !(parent.getComponent && (parent.getComponent("cc.Button") || (typeof cc.Button !== "undefined" && parent.getComponent(cc.Button)))) && parent.parent) {
        parent = parent.parent;
      }
      const btnNode = parent || node;
      const btnComp = btnNode.getComponent ? (btnNode.getComponent("cc.Button") || (typeof cc.Button !== "undefined" && btnNode.getComponent(cc.Button))) : null;
      if (btnComp && btnComp.clickEvents && typeof cc.Component !== "undefined" && cc.Component.EventHandler) {
        cc.Component.EventHandler.emitEvents(btnComp.clickEvents, btnComp);
        clicked = true;
      }
      if (typeof cc.Node !== "undefined" && cc.Node.EventType) {
        btnNode.emit(cc.Node.EventType.TOUCH_END);
        clicked = true;
      }
    } catch (_) {}
    return clicked;
  }

  // Chọn đúng ô cược bằng node Cocos thay vì toạ độ tỉ lệ. Canvas game thay
  // đổi theo zoom/resolution; click xấp xỉ từng bấm nhầm $500 khi chọn $100.
  function joinCocosTableByBet(bet, mu) {
    const expected = String(Number(bet));
    let clicked = false;
    try {
      if (typeof cc === "undefined" || !cc.director) return false;
      const scene = cc.director.getScene();
      if (!scene) return false;
      function scan(node, depth) {
        if (!node || depth > 35 || clicked) return;
        const name = String(node.name || "").toLowerCase();
        const text = getCocosNodeText(node).replace(/[^0-9]/g, "");
        // Cần khớp CHÍNH XÁC giá trị nhãn/nút, không dùng includes("100")
        // vì $100 cũng là một phần của $1000/$10000.
        const nameNumbers = name.match(/\d+/g) || [];
        const exactBet = text === expected || nameNumbers.includes(expected);
        const isTable = name.includes("room") || name.includes("table") ||
          name.includes("bet") || name.includes("cuoc") || name.includes("ban");
        if (exactBet && isTable && node.active) {
          clicked = clickCocosNode(node);
          if (clicked) console.log(`[AutoTool V3] Cocos join đúng mức $${expected}: node='${node.name}', text='${getCocosNodeText(node)}'`);
          return;
        }
        for (const child of (node.children || [])) scan(child, depth + 1);
      }
      scan(scene, 0);
    } catch (e) {
      console.warn("[AutoTool V3] Lỗi joinCocosTableByBet:", e);
    }
    return clicked;
  }

  function dispatchCanvasClick(normX, normY) {
    try {
      const canvas = document.querySelector("canvas");
      if (!canvas) return false;
      const rect = canvas.getBoundingClientRect();
      const clickX = rect.left + rect.width * normX;
      const clickY = rect.top + rect.height * normY;
      const opts = {
        bubbles: true,
        cancelable: true,
        clientX: clickX,
        clientY: clickY,
        view: window
      };
      canvas.dispatchEvent(new PointerEvent("pointerdown", opts));
      canvas.dispatchEvent(new MouseEvent("mousedown", opts));
      canvas.dispatchEvent(new PointerEvent("pointerup", opts));
      canvas.dispatchEvent(new MouseEvent("mouseup", opts));
      canvas.dispatchEvent(new MouseEvent("click", opts));
      console.log(`[AutoTool V3] dispatchCanvasClick tại (${Math.round(clickX)}, ${Math.round(clickY)}) [${normX.toFixed(3)}, ${normY.toFixed(3)}]`);
      return true;
    } catch (err) {
      console.warn("[AutoTool V3] Lỗi dispatchCanvasClick:", err);
      return false;
    }
  }

  // Phát hiện màn hình đăng nhập của Hitclub Cocos (chính xác theo scene native, không quét text bừa bãi)
  function isOnLoginScreen() {
    try {
      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene && scene.name) {
          const sName = String(scene.name).toLowerCase();
          // Nếu đang ở Lobby hoặc Game thì chắc chắn 100% không phải màn hình login
          if (sName.includes("lobby") || sName.includes("game") || sName.includes("tlmn") || sName.includes("tldl")) {
            return false;
          }
          if (sName === "login" || sName.startsWith("login")) {
            return true;
          }
        }
      }
    } catch (_) {}
    return false;
  }

  // Phát hiện tài khoản BỊ ĐĂNG XUẤT -> DỪNG MỌI HÀNH ĐỘNG WS NGAY (giữ phiên, tránh
  // server game kick thêm). Trước đây hàm này bị mất (ReferenceError làm chết cả
  // content_main) nên bot vẫn bắn lệnh khi đã đăng xuất -> bị kick liên tục.
  function checkAndHandleLoggedOut() {
    if (!isOnLoginScreen()) {
      return false;
    }
    console.warn("[AutoTool V3] ⚠️ PHÁT HIỆN TÀI KHOẢN BỊ ĐĂNG XUẤT! DỪNG TOÀN BỘ HÀNH ĐỘNG ĐỂ GIỮ PHIÊN!");
    G.__AUTOTOOL_AUTO_HUNT = false;
    G.__AUTOTOOL_ARMED = false;
    clearRunConfig();
    G.__is_matched_locked = false;
    G.__game_in_progress = false;
    G.__is_hunt_initiator = false;
    G.__last_room_info = null;
    G.__room_players = [];
    G.__active_room_invite = null;
    const timers = ["__start_retry_timer", "__hunt_wait_timer", "__hunt_retry_timer", "__guest_ss_wait_timer", "__auto_turn_timer"];
    for (const t of timers) {
      if (G[t]) {
        if (t.includes("retry") || t === "__start_retry_timer") clearInterval(G[t]);
        else clearTimeout(G[t]);
        G[t] = null;
      }
    }
    try { localStorage.setItem("AUTOTOOL_STOPPED", "1"); } catch (_) {}
    window.postMessage({
      type: "AUTOTOOL_ACCOUNT_LOGGED_OUT",
      profile_name: getProfileName(),
      reason: "Phát hiện màn hình đăng nhập (bị đăng xuất)",
    }, "*");
    return true;
  }

  function dismissPopupsAndBanners() {
    let closedCount = 0;
    try {
      // Quét Cocos scene tìm và đóng popup/quảng cáo thực sự (có nút Close/X rõ ràng)
      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene) {
          function scanPopups(node, depth) {
            if (!node || depth > 30) return;
            const name = (node.name || "").toLowerCase();
            const text = getCocosNodeText(node).toUpperCase();

            // Nhận diện nút đóng popup / quảng cáo / x
            // QUAN TRỌNG: Loại trừ btn_back (nút thoát game) tránh click nhầm!
            const isCloseBtn = /^(btn_close|btnclose|btn_dong|btndong|btn_x|btnx|closebtn|button_close|btn_exit|btnexit|btn_cancel)$/i.test(name) ||
                               name.includes("close") || name.includes("dong") || name === "x" ||
                               text === "ĐÓNG" || text === "BỎ QUA" || text === "CLOSE" || text === "X";

            if (isCloseBtn && node.active && (node.opacity === undefined || node.opacity > 0)) {
              // Chặn tuyệt đối: không được click nút THOÁT hoặc BACK vì sẽ thoát game
              if (!name.includes("back") && !name.includes("leave") && !name.includes("thoat") &&
                  text !== "THOÁT" && text !== "THOÁT HẾT") {
                if (clickCocosNode(node)) {
                  closedCount++;
                  console.log(`[AutoTool V3] Đã đóng popup Cocos: name='${node.name}', text='${text}'`);
                }
              }
            }

            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
              scanPopups(children[i], depth + 1);
            }
          }
          scanPopups(scene, 0);
        }
      }

      // Chỉ đóng khi thực sự phát hiện node nút đóng của popup trong Cocos
      // TUYỆT ĐỐI KHÔNG click mù tọa độ (0.867, 0.218) nếu không có popup (tránh click nhầm vào Banner / Game Tài Xỉu)

      const domCloseBtns = document.querySelectorAll(".btn-close, .close, [aria-label='Close'], .popup-close, .modal-close");
      domCloseBtns.forEach((btn) => {
        try {
          btn.click();
          closedCount++;
        } catch (_) {}
      });
    } catch (e) {
      console.warn("[AutoTool V3] Lỗi dismissPopupsAndBanners:", e);
    }
    return closedCount;
  }

  function clickCocosTabGameBai() {
    let clicked = false;
    try {
      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene) {
          function scan(node, depth) {
            if (!node || depth > 30 || clicked) return;
            const name = (node.name || "").toLowerCase();
            const text = getCocosNodeText(node).toUpperCase();

            if ((text === "GAME BÀI" || name === "gamebai" || name === "game_bai" || name === "cardgame" || name === "tab_gamebai") && node.active) {
              clicked = clickCocosNode(node);
              if (clicked) {
                console.log(`[AutoTool V3] Đã click Cocos tab GAME BÀI: node='${node.name}', text='${text}'`);
                return;
              }
            }

            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
              scan(children[i], depth + 1);
              if (clicked) return;
            }
          }
          scan(scene, 0);
        }
      }
    } catch (e) {
      console.warn("[AutoTool V3] Lỗi clickCocosTabGameBai:", e);
    }
    return clicked;
  }

  function clickCocosGameTLDL() {
    let clicked = false;
    try {
      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene) {
          function scan(node, depth) {
            if (!node || depth > 30 || clicked) return;
            const name = (node.name || "").toLowerCase();
            const text = getCocosNodeText(node).toUpperCase();

            const isTLDL = text.includes("ĐẾM LÁ") || text.includes("TIẾN LÊN") ||
                           name.includes("demla") || name.includes("dem_la") ||
                           name.includes("simms") || name.includes("tldl");

            if (isTLDL && !text.includes("MIỀN NAM") && node.active) {
              clicked = clickCocosNode(node);
              if (clicked) {
                console.log(`[AutoTool V3] Đã click Cocos game TIẾN LÊN ĐẾM LÁ: node='${node.name}', text='${text}'`);
                return;
              }
            }

            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
              scan(children[i], depth + 1);
              if (clicked) return;
            }
          }
          scan(scene, 0);
        }
      }
    } catch (e) {
      console.warn("[AutoTool V3] Lỗi clickCocosGameTLDL:", e);
    }
    return clicked;
  }

  function clickCocosSoloTab(targetMu = 2) {
    let clicked = false;
    try {
      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene) {
          function scan(node, depth) {
            if (!node || depth > 30 || clicked) return;
            const name = (node.name || "").toLowerCase();
            const text = getCocosNodeText(node).toUpperCase();

            if (targetMu === 2) {
              if ((text === "SOLO" || text === "2 NGƯỜI" || name.includes("solo") || name.includes("mu2")) && node.active) {
                clicked = clickCocosNode(node);
                if (clicked) {
                  console.log(`[AutoTool V3] Đã click tab SOLO (2 người): node='${node.name}'`);
                  return;
                }
              }
            } else {
              if ((text === "4 NGƯỜI" || name.includes("4nguoi") || name.includes("mu4")) && node.active) {
                clicked = clickCocosNode(node);
                if (clicked) {
                  console.log(`[AutoTool V3] Đã click tab 4 NGƯỜI: node='${node.name}'`);
                  return;
                }
              }
            }

            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
              scan(children[i], depth + 1);
              if (clicked) return;
            }
          }
          scan(scene, 0);
        }
      }
    } catch (e) {
      console.warn("[AutoTool V3] Lỗi clickCocosSoloTab:", e);
    }
    if (!clicked) {
      const tabX = targetMu === 2 ? 0.500 : 0.690;
      dispatchCanvasClick(tabX, 0.175);
    }
    return clicked;
  }

  function isInsideGameTable() {
    try {
      // 1. Kiểm tra trạng thái ván và danh sách người chơi
      if (G.__game_in_progress) return true;
      if (Array.isArray(G.__room_players) && G.__room_players.length > 0) return true;
      if (G.__last_room_info && G.__last_room_info.rid > 0 && G.__last_room_info.rid !== 100) {
        if (G.__room_players && G.__room_players.length > 0) return true;
      }

      // 2. Quét Cocos scene tìm các dấu hiệu nhận diện bàn chơi HitClub
      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene) {
          let foundTable = false;
          function scanTable(node, depth) {
            if (!node || depth > 25 || foundTable) return;
            const text = getCocosNodeText(node).toUpperCase();
            const name = (node.name || "").toLowerCase();

            // Các nhãn và node đặc thù 100% chỉ có trong bàn chơi
            if (text.includes("CHỐNG VÂY") || text.includes("CHONG VAY") || text.includes("CHÓNG VÂY") ||
                text.includes("BÀN: THƯỜNG") || text.includes("BAN: THUONG") || text.includes("CƯỢC:") || text.includes("CUOC:") ||
                text === "BẮT ĐẦU" || text === "BAT DAU" || text === "SẴN SÀNG" || text === "SAN SANG" ||
                name === "btn_begin" || name === "btnbegin" ||
                name === "btn_ready" || name === "btnready" ||
                name === "table" || name === "table_view" || name === "gameplay") {
              if (isNodeVisible(node)) {
                foundTable = true;
                return;
              }
            }
            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
              scanTable(children[i], depth + 1);
              if (foundTable) return;
            }
          }
          scanTable(scene, 0);
          if (foundTable) return true;
        }
      }
    } catch (_) {}
    return false;
  }

  /** Có popup/quảng cáo đang che màn hình không.
   *
   * Người dùng gặp: nick phụ đứng ở sảnh chính với popup quảng cáo, nhưng bị
   * báo là "đã sẵn sàng ở sảnh chọn bàn" nên cả lượt chạy tiến hành mà thiếu
   * người. Popup che màn thì mọi thao tác click đều vô nghĩa -> phải coi là
   * CHƯA sẵn sàng.
   *
   * Dùng `isNodeVisible` (activeInHierarchy) chứ không phải `node.active`:
   * Cocos dựng sẵn UI rồi tắt bằng cách hạ cờ active của một node CHA, nên
   * kiểm `active` của chính node sẽ thấy "đang bật" ở những popup đã đóng.
   */
  function hasBlockingPopup() {
    try {
      if (typeof cc === "undefined" || !cc.director) return false;
      const scene = cc.director.getScene();
      if (!scene) return false;
      let thay = false;
      (function quet(node, depth) {
        if (!node || depth > 30 || thay) return;
        if (isNodeVisible(node)) {
          const name = (node.name || "").toLowerCase();
          const text = getCocosNodeText(node).toUpperCase();
          if (/^(popup|dialog|quangcao|banner|announce|notice)/.test(name)
              || name.includes("popup") || name.includes("dialog")
              || text === "BỎ QUA" || text === "CẢNH BÁO LỪA ĐẢO") {
            thay = true;
            return;
          }
        }
        const ch = node.children || [];
        for (let i = 0; i < ch.length; i++) quet(ch[i], depth + 1);
      })(scene, 0);
      return thay;
    } catch (e) {
      return false;
    }
  }

  function isAlreadyInTLDLLobby() {
    try {
      // Nếu đang ngồi trong bàn chơi -> Tuyệt đối không phải ở sảnh!
      if (isInsideGameTable()) return false;

      const simms = typeof G.__ws_get_simms === "function" ? G.__ws_get_simms() : null;
      const hasSimmsWs = !!(simms && simms.readyState === 1);

      let hasTLDLScene = false;
      // Đếm theo TẬP: sảnh chính hiện đủ bộ GAME BÀI + SLOTS + MINI GAME +
      // QUAY SỐ cùng lúc, trong khi màn chọn bàn có thể có MỘT nhãn lạc.
      // Đòi từ hai dấu hiệu trở lên để không nhận nhầm theo chiều ngược lại.
      const dauHieuSanhChinh = new Set();

      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene) {
          function scanLobby(node, depth) {
            if (!node || depth > 25) return;
            const name = (node.name || "").toLowerCase();
            const text = getCocosNodeText(node).toUpperCase();

            // Chỉ tính node ĐANG HIỂN THỊ THẬT: scene giữ sẵn cả UI sảnh chính
            // lẫn UI bàn chơi ở trạng thái tắt, nếu không lọc sẽ nhận nhầm màn.
            if (isNodeVisible(node)) {
              if (text === "GAME BÀI" || text === "SLOTS" || text === "MINI GAME" || text === "QUAY SỐ") {
                dauHieuSanhChinh.add(text);
              }

              if (name.includes("roomselect") || name.includes("room_select") ||
                  text === "SOLO" || text === "4 NGƯỜI" || text.includes("ĐẾM LÁ BÀN") ||
                  name === "btn_solo" || name === "btn_4nguoi") {
                hasTLDLScene = true;
              }
            }

            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
              scanLobby(children[i], depth + 1);
            }
          }
          scanLobby(scene, 0);
        }
      }

      const hasMainLobbyButtons = dauHieuSanhChinh.size >= 2;

      // Popup che màn -> chưa thao tác được -> CHƯA sẵn sàng.
      if (hasBlockingPopup()) return false;

      // ĐÃ BỎ đường "socket đang nối + thấy node giống sảnh chọn bàn -> true".
      // Socket nối KHÔNG đồng nghĩa đang ở sảnh chọn bàn: vẫn có thể đang ở
      // sảnh chính HitClub. Chính lobby.py đã ghi luật cấm điều này, nhưng
      // phía JS lại vi phạm — nên nick phụ đứng ở sảnh chính vẫn được báo là
      // sẵn sàng, và cả lượt gom bàn chạy tiếp trong khi thiếu người.
      const sanSang = hasTLDLScene && !hasMainLobbyButtons;
      if (!sanSang) {
        G.__autotool_ly_do_chua_o_sanh =
          !hasTLDLScene ? "khong thay man chon ban"
          : `dang o sanh chinh (${[...dauHieuSanhChinh].join(", ")})`;
      } else {
        G.__autotool_ly_do_chua_o_sanh = "";
      }
      // `hasSimmsWs` chỉ để chẩn đoán, KHÔNG dùng để kết luận.
      if (!sanSang && !hasSimmsWs) {
        console.debug("[AutoTool V3] chưa ở sảnh chọn bàn & socket chưa nối");
      }
      return sanSang;
    } catch (e) {
      console.warn("[AutoTool V3] Lỗi isAlreadyInTLDLLobby:", e);
      return false;
    }
  }

  async function autoEnterTLDLLobby(targetMu = 2) {
    console.log("[AutoTool V3] >>> BẮT ĐẦU QUY TRÌNH AUTO ENTER TLDL LOBBY <<<");
    if (isAlreadyInTLDLLobby()) {
      console.log("[AutoTool V3] Đã ở sẵn sảnh Tiến Lên Đếm Lá!");
      return { ok: true, already: true };
    }

    // 0. Kiểm tra nếu đang ở màn hình đăng nhập / đăng xuất
    if (typeof isOnLoginScreen === "function" && isOnLoginScreen()) {
      console.warn("[AutoTool V3] ⚠️ Đang ở màn hình đăng nhập! Không thể vào sảnh TLDL.");
      return { ok: false, error: "Tài khoản chưa đăng nhập / bị đăng xuất" };
    }

    // 1. Đóng Popup / Banner / Ads nếu có
    dismissPopupsAndBanners();
    await new Promise((r) => setTimeout(r, humanDelay(350, 550)));

    // 2. Click tab GAME BÀI (Ưu tiên Cocos Native an toàn 100%, chống nhầm sang Tài Xỉu)
    let clickedGb = clickCocosTabGameBai();
    if (!clickedGb) {
      // Chỉ click fallback nếu Cocos không tìm thấy node
      dispatchCanvasClick(0.427, 0.250);
      await new Promise((r) => setTimeout(r, 200));
      clickCocosTabGameBai();
    }
    await new Promise((r) => setTimeout(r, humanDelay(600, 900)));

    // 3. Đóng popup phát sinh (nếu có)
    dismissPopupsAndBanners();
    await new Promise((r) => setTimeout(r, humanDelay(250, 400)));

    // 4. Click game TIẾN LÊN ĐẾM LÁ (Ưu tiên Cocos Native)
    let clickedTldl = clickCocosGameTLDL();
    if (!clickedTldl) {
      dispatchCanvasClick(0.320, 0.400);
      await new Promise((r) => setTimeout(r, 200));
      clickCocosGameTLDL();
    }
    await new Promise((r) => setTimeout(r, humanDelay(1500, 2000)));

    // 5. Đóng popup nếu có
    dismissPopupsAndBanners();

    // 6. Click Solo Tab
    clickCocosSoloTab(targetMu);
    await new Promise((r) => setTimeout(r, humanDelay(300, 500)));

    const inLobby = isAlreadyInTLDLLobby();
    console.log(`[AutoTool V3] Hoàn thành quy trình autoEnterTLDLLobby -> Kết quả inLobby: ${inLobby}`);
    return { ok: inLobby, step: "done" };
  }

  G.__autotool_is_inside_table = isInsideGameTable;
  G.__autotool_is_in_tldl_lobby = isAlreadyInTLDLLobby;
  G.__autotool_has_popup = hasBlockingPopup;
  G.__autotool_auto_enter_tldl = autoEnterTLDLLobby;
  G.__autotool_join_table_by_bet = joinCocosTableByBet;
  G.__autotool_dismiss_popups = dismissPopupsAndBanners;
  G.__autotool_is_on_login_screen = isOnLoginScreen;
  G.__autotool_check_logged_out = checkAndHandleLoggedOut;

  // Hàm điều phối xác minh sẵn sàng & bắt đầu ván (Two-way Handshake & Retry Start Pulse)
  function triggerVerifiedMatchReadyAndStart(partnerName, sourceReason) {
    const seatedPlayers = G.__room_players || [];
    if (seatedPlayers.length < 2) {
      console.warn(`[AutoTool V3] ⚠️ TỪ CHỐI SẴN SÀNG: Bàn chỉ có ${seatedPlayers.length} người, không thể khớp khi ngồi một mình! [${sourceReason || ''}]`);
      return;
    }
    const partnerSeated = seatedPlayers.find(isPartner);
    if (!partnerSeated) {
      console.warn(`[AutoTool V3] ⚠️ TỪ CHỐI SẴN SÀNG: triggerVerifiedMatchReadyAndStart được gọi [${sourceReason || ''}] nhưng KHÔNG THẤY đồng đội ngồi trong bàn!`);
      return;
    }

    // Làm sạch tên đồng đội: tuyệt đối không dùng giá trị "None", "null", "undefined"
    let cleanPartner = "";
    if (partnerName && !["none", "null", "undefined", ""].includes(String(partnerName).trim().toLowerCase())) {
      cleanPartner = String(partnerName).trim();
    } else if (partnerSeated && (partnerSeated.dn || partnerSeated.u)) {
      cleanPartner = String(partnerSeated.dn || partnerSeated.u).trim();
    } else if (G.__last_room_info && G.__last_room_info.partner_name) {
      cleanPartner = String(G.__last_room_info.partner_name).trim();
    } else {
      cleanPartner = "Đồng đội";
    }

    console.log(`[AutoTool V3] 🟢 >>> XÁC MINH KHỚP BÀN THÀNH CÔNG: ${cleanPartner} [${sourceReason || 'OK'}]! <<<`);
    if (G.__backoff) G.__backoff.onSuccess();

    G.__is_matched_locked = true;
    G.__AUTOTOOL_AUTO_HUNT = false;
    if (G.__hunt_wait_timer) {
      clearTimeout(G.__hunt_wait_timer);
      G.__hunt_wait_timer = null;
    }
    if (G.__hunt_retry_timer) {
      clearTimeout(G.__hunt_retry_timer);
      G.__hunt_retry_timer = null;
    }
    if (G.__last_room_info) {
      G.__last_room_info.partner_found = true;
      G.__last_room_info.partner_name = cleanPartner;
    }

    window.postMessage({
      type: "AUTOTOOL_MATCH_SUCCESS",
      profile_name: getProfileName(),
      partner_name: cleanPartner,
      verified: true,
      rid: (G.__last_room_info && G.__last_room_info.rid) || 2,
    }, "*");

    const executeHandshakeAction = () => {
      // Account phụ chỉ Sẵn Sàng; chỉ chủ bàn mới được Bắt đầu. Trước đây cả
      // hai cùng gọi ready (có kèm cmd 5) khiến chủ bàn có thể không phát Start
      // đúng thời điểm và bị server out vì timeout.
      if (isAnchorMatchProfile()) {
        console.log("[AutoTool V3] Chủ bàn đã xác minh đồng đội -> gửi BẮT ĐẦU.");
        G.__autotool_exec_start();
      } else {
        console.log("[AutoTool V3] Account phụ đã xác minh chủ bàn -> gửi SẴN SÀNG.");
        G.__autotool_exec_ready();
      }
    };

    setTimeout(executeHandshakeAction, 150);

    setTimeout(() => {
      if (!G.__game_in_progress && (!G.__my_cards || G.__my_cards.length === 0)) {
        console.log("[AutoTool V3] Nhắc lại handshake theo đúng vai trò.");
        executeHandshakeAction();
      }
    }, 450);

    if (G.__start_retry_timer) {
      clearInterval(G.__start_retry_timer);
      G.__start_retry_timer = null;
    }
    let attempts = 0;
    G.__start_retry_timer = setInterval(() => {
      if (G.__game_in_progress || (G.__my_cards && G.__my_cards.length > 0) || !G.__is_matched_locked) {
        clearInterval(G.__start_retry_timer);
        G.__start_retry_timer = null;
        return;
      }
      attempts++;
      if (attempts > 6) {
        clearInterval(G.__start_retry_timer);
        G.__start_retry_timer = null;
        return;
      }
      console.log(`[AutoTool V3] [Retry Start #${attempts}] Gửi lại handshake đúng vai trò.`);
      executeHandshakeAction();
    }, 600);
  }

  G.__clean_uid = cleanUid;
  G.__is_me = isMe;
  G.__is_partner = isPartner;
  G.__exec_cocos_ready_or_start = execCocosReadyOrStart;
  G.__trigger_verified_match_ready_and_start = triggerVerifiedMatchReadyAndStart;

  function handleAutoTurn() {
    if (G.__auto_turn_timer) {
      clearTimeout(G.__auto_turn_timer);
      G.__auto_turn_timer = null;
    }
    // Chua kich hoat / da Dung -> khong tu danh bai. Truoc day chi canh
    // AUTO_DISCARD, ma co do khong duoc xoa khi Dung nen bot van danh tiep.
    if (!isAutoEngaged()) return;
    if (!G.__AUTOTOOL_AUTO_DISCARD) return;
    if (!G.__my_cards || !G.__my_cards.length) return;

    // Không bấm dồn ngay khi có frame cmd=251. Account phụ chậm hơn một nhịp
    // để state bàn/turn ổn định trước khi quyết định đè hoặc bỏ lượt.
    const roleForDelay = getMyRole();
    const delay = roleForDelay === "dump" ? humanDelay(1150, 1900) : humanDelay(850, 1450);
    G.__auto_turn_timer = setTimeout(() => {
      if (!G.__my_cards || !G.__my_cards.length) return;
      const role = getMyRole();
      const hasTableCards = Array.isArray(G.__last_table_cards) && G.__last_table_cards.length > 0;
      const isPartnerActor = (hasTableCards && G.__last_table_player) ? isPartner(G.__last_table_player) : false;

      console.log(`[AutoTool V3] Tới lượt của tôi! Role=${role}, Bài trên tay: ${G.__my_cards.length} lá, Bàn: ${JSON.stringify(G.__last_table_cards)}, isPartnerActor=${isPartnerActor}`);

      const play = findBestPlay(G.__my_cards, hasTableCards ? G.__last_table_cards : null, role, isPartnerActor);

      if (play && play.length > 0) {
        const cardLabels = play.map((c) => {
          const p = parseCard(c);
          return p ? p.name : c;
        }).join(" ");
        console.log(`[AutoTool V3] >>> TỰ ĐỘNG ĐÁNH BÀI: [${cardLabels}] (cmd 253) <<<`);
        G.__autotool_exec_play(play);
      } else {
        console.log("[AutoTool V3] >>> TỰ ĐỘNG BỎ LƯỢT / PASS (cmd 254) <<<");
        G.__autotool_exec_pass();
      }
    }, delay);
  }

  // Lấy định danh profile được inject từ Playwright hoặc localStorage của game
  function getProfileName() {
    if (G.__AUTOTOOL_PROFILE_NAME) return G.__AUTOTOOL_PROFILE_NAME;
    try {
      const localUser = localStorage.getItem("KEY_USER_NAME") || localStorage.getItem("AUTOTOOL_PROFILE_NAME");
      if (localUser) {
        G.__AUTOTOOL_PROFILE_NAME = localUser;
        return localUser;
      }
    } catch (_) {}
    return document.title || "";
  }

  // Thông báo nhận diện Profile lên isolated context
  setTimeout(() => {
    const pName = getProfileName();
    if (pName) {
      window.postMessage({ type: "AUTOTOOL_INIT_PROFILE", profile_name: pName }, "*");
    }
  }, 100);

  // Thông báo nhận diện Profile lên isolated context
  setTimeout(() => {
    const pName = getProfileName();
    if (pName) {
      window.postMessage({ type: "AUTOTOOL_INIT_PROFILE", profile_name: pName }, "*");
    }
  }, 100);

  const push = (dir, data) => {
    try {
      let text = "";
      if (typeof data === "string") text = data;
      else if (data instanceof Blob) text = "[Blob " + data.size + "b]";
      else if (data instanceof ArrayBuffer) text = new TextDecoder().decode(data);
      else if (data && data.data !== undefined) text = typeof data.data === "string" ? data.data : "[binary]";
      else text = "[?]";

      G.__ws_capture.push({ ts: Date.now(), dir, text: String(text).slice(0, 4000) });
      if (G.__ws_capture.length > 2000) G.__ws_capture.splice(0, 1000);

      // ADAPTIVE BACKOFF (#1): Phát hiện cảnh báo Rate-Limit từ game ("quá nhanh", "thao tác")
      if (dir === "recv" && typeof text === "string" && (text.includes("quá nhanh") || text.includes("thao tác"))) {
        console.warn("[AutoTool V3] [Adaptive Backoff #1] Phát hiện server cảnh báo Rate-Limit -> Tăng mạnh delay backoff!");
        if (G.__backoff) G.__backoff.onFailure(true);
      }

      // Bắt lệnh gửi từ client (send) để lưu trước rid người chơi chủ động bấm vào
      if (dir === "send") {
        if (text.includes('"rid":')) {
          const m = text.match(/"rid"\s*:\s*(\d+)/);
          if (m && m[1] && Number(m[1]) > 0 && Number(m[1]) !== 100) {
            G.__ws_pending_rid = Number(m[1]);
          }
        } else if (text.includes('[3,"Simms",')) {
          // Protocol bàn cố định: [3,"Simms",<rid>,""] . Trước đây chỉ
          // bắt biến thể cũ có số 1 ở vị trí thứ ba nên khi join rid=4 ($500)
          // không được ghi nhận, rồi cmd 202 bị suy diễn nhầm thành bàn $100.
          const m = text.match(/\[3,"Simms",\s*"?(\d+)"?/);
          if (m && m[1] && Number(m[1]) > 0) {
            G.__ws_pending_rid = Number(m[1]);
          }
        }
      }

      // Phân tích packet game
      if (text.startsWith("[") && text.includes('"cmd"')) {
        try {
          const arr = JSON.parse(text);
          let p = null;
          if (Array.isArray(arr)) {
            for (let i = 1; i < arr.length; i++) {
              if (arr[i] && typeof arr[i] === "object" && arr[i].cmd) {
                p = arr[i];
                break;
              }
            }
          }
          if (p) {
            // cmd 100: Thông tin User, Số dư & Trạng thái Sảnh
            if (p.cmd === 100) {
              if (p.uid || p.id) {
                G.__my_uid = p.uid || p.id;
                window.__my_uid = G.__my_uid;
              }
              if (p.dn || p.u) {
                const realDn = p.dn || "";
                const realU  = p.u  || "";
                G.__my_dn = realDn;
                G.__my_u  = realU;
                window.__my_dn = G.__my_dn;
                window.__my_u  = G.__my_u;
                window.__user_info = { uid: G.__my_uid, dn: G.__my_dn, u: G.__my_u };
                // TUYỆT ĐỐI KHÔNG ghi đè localStorage KEY_USER_NAME vì đây là key tên đăng nhập của game HitClub!
                // Ghi đè sai sẽ làm session token bị lệch và game tự động kick/đăng xuất!
                try {
                  localStorage.setItem("AUTOTOOL_IN_GAME_DN", realDn);
                  if (realU) localStorage.setItem("AUTOTOOL_IN_GAME_U", realU);
                } catch (_) {}
                // LUÔN LUÔN thông báo thông tin định danh in-game (dn, u, uid) lên Extension Hub để đồng bộ đối tác
                window.postMessage({
                  type: "AUTOTOOL_INIT_PROFILE",
                  profile_name: getProfileName(),
                  dn: realDn,
                  u: realU,
                  uid: G.__my_uid,
                  user_info: window.__user_info,
                }, "*");
                // ĐỒNG BỘ TÊN IN-GAME THỰC TẾ VỀ APP (Tránh lệch ký tự do người dùng nhập sai)
                // Ưu tiên: dn (display name) > u (username) — đây là tên chính xác 100% từ server game
                window.postMessage({
                  type: "AUTOTOOL_USERNAME_SYNC",
                  profile_name: getProfileName(),
                  real_dn: realDn || realU,        // Tên hiển thị in-game (nicktestxxabai1)
                  real_u: G.__my_u,         // Username in-game (có thể khác display name)
                  real_uid: G.__my_uid,     // UID số (định danh tuyệt đối)
                }, "*");
              }
              const gold = (p.As && p.As.gold !== undefined) ? p.As.gold : (p.gold !== undefined ? p.gold : (p.m !== undefined ? p.m : (p.g !== undefined ? p.g : null)));
              if (gold !== null && !isNaN(Number(gold))) {
                G.__my_balance = Number(gold);
                // LƯU SỐ DƯ CUỐI CÙNG VÀO localStorage -> backend đọc khi đóng Chrome
                // để ghi lại accounts.json, mở app lần sau hiển thị đúng số dư lần cuối.
                try { localStorage.setItem("AUTOTOOL_BALANCE", String(G.__my_balance)); } catch (_) {}
                window.postMessage({
                  type: "AUTOTOOL_BALANCE_UPDATE",
                  profile_name: getProfileName(),
                  balance: G.__my_balance,
                }, "*");
              }
              // Nếu đang ở sảnh (lr.rid === -1)
              if (p.lr && p.lr.rid === -1) {
                G.__last_room_info = null;
                G.__room_players = [];
                G.__ws_pending_rid = null;
                window.postMessage({
                  type: "AUTOTOOL_ROOM_LEFT",
                  profile_name: getProfileName(),
                }, "*");
              }
            }

            // (cleanUid, isMe, isPartner, triggerVerifiedMatchReadyAndStart đã được khai báo ở top-level scope)
            // cmd 200: Người chơi mới bước vào bàn (t: 1) hoặc rời bàn (t: 2)
            if (p.cmd === 200 && p.p) {
              const player = p.p;
              const actionType = p.t; // 1: Vào bàn, 2: Rời bàn

              if (actionType === 1) {
                const pPartner = isPartner(player);
                const pMe = isMe(player);

                if (!pMe) {
                  if (!G.__room_players) G.__room_players = [];
                  const existingIdx = G.__room_players.findIndex((x) => String(x.uid || x.dn) === String(player.uid || player.dn));
                  if (existingIdx >= 0) {
                    G.__room_players[existingIdx] = player;
                  } else {
                    G.__room_players.push(player);
                  }

                  if (pPartner) {
                    // ĐỒNG ĐỘI VỪA BƯỚC VÀO BÀN!
                    console.log(`[AutoTool V3] [cmd 200] ĐỒNG ĐỘI ${player.dn || player.u} VỪA BƯỚC VÀO BÀN!`);
                    triggerVerifiedMatchReadyAndStart(player.dn || player.u, "cmd:200 Join");
                  } else {
                    // KHÁCH LẠ VÀO BÀN -> HỦY LỆNH CHO ĐỒNG ĐỘI & TỰ ĐỘNG OUT BÀN NGAY
                    const strangerName = player.dn || player.u || "Khách";
                    console.warn(`[AutoTool V3] [cmd 200] PHÁT HIỆN KHÁCH LẠ ${strangerName} VÀO BÀN -> Hủy lệnh cho đồng đội & Out bàn ngay!`);
                    if (G.__backoff) G.__backoff.onFailure(false);
                    if (G.__hunt_wait_timer) {
                      clearTimeout(G.__hunt_wait_timer);
                      G.__hunt_wait_timer = null;
                    }
                    window.postMessage({
                      type: "AUTOTOOL_CANCEL_ROOM_INVITE",
                      profile_name: getProfileName(),
                      rid: (G.__last_room_info && G.__last_room_info.rid) || G.__ws_pending_rid || null,
                      reason: `Khách lạ vào bàn: ${strangerName}`,
                    }, "*");
                    window.postMessage({
                      type: "AUTOTOOL_AUTO_LEAVING",
                      profile_name: getProfileName(),
                      reason: `Thấy khách lạ: ${strangerName}`,
                    }, "*");
                    // Out an toàn (350 - 550ms) để server xử lý xong trạng thái
                    const leaveDelay = 350 + Math.floor(Math.random() * 200);
                    setTimeout(() => {
                      G.__autotool_exec_leave();
                    }, leaveDelay);
                  }
                }
              } else if (actionType === 2) {
                // Người rời bàn
                if (G.__room_players) {
                  G.__room_players = G.__room_players.filter((x) => String(x.uid || x.dn) !== String(player.uid || player.dn));
                }
                if (isPartner(player) && !G.__game_in_progress) {
                  console.log(`[AutoTool V3] [cmd 200] Đồng đội ${player.dn || player.u} đã rời bàn.`);
                  G.__is_matched_locked = false;
                  if (G.__start_retry_timer) {
                    clearInterval(G.__start_retry_timer);
                    G.__start_retry_timer = null;
                  }
                }
              }
            }

            // cmd 202: Danh sách người chơi trong phòng & thông tin bàn
            if (p.cmd === 202) {
              G.__room_players = p.ps || [];
              G.__room_state = p.gS;

              // Trích xuất chính xác 100% "Chính mình" (isMe -> có bài trên tay -> hoặc người duy nhất trong bàn 1 người)
              const me = (p.ps || []).find(isMe) ||
                         (p.ps || []).find((x) => Array.isArray(x.cs) && x.cs.length > 0) ||
                         ((p.ps || []).length === 1 ? p.ps[0] : null);
              if (me) {
                G.__my_uid = me.uid || G.__my_uid;
                G.__my_dn = me.dn || me.u || G.__my_dn;
                G.__my_sit = me.sit;
                if (me.dn || me.u) {
                  const realUser = me.dn || me.u;
                  G.__AUTOTOOL_PROFILE_NAME = realUser;
                  try {
                    localStorage.setItem("AUTOTOOL_IN_GAME_DN", realUser);
                    localStorage.setItem("AUTOTOOL_PROFILE_NAME", realUser);
                  } catch (_) {}
                }
              }

              const partner = (p.ps || []).find(isPartner);
              const strangers = (p.ps || []).filter((x) => !isMe(x) && !isPartner(x));

              // Cập nhật số dư & bài của tài khoản nếu có trong packet
              if (me) {
                const meGold = me.As && me.As.gold !== undefined ? me.As.gold : (me.m !== undefined ? me.m : null);
                if (meGold !== null && !isNaN(Number(meGold))) {
                  G.__my_balance = Number(meGold);
                  // Lưu số dư mới nhất vào localStorage để backend đọc khi đóng Chrome
                  try { localStorage.setItem("AUTOTOOL_BALANCE", String(G.__my_balance)); } catch (_) {}
                  window.postMessage({
                    type: "AUTOTOOL_BALANCE_UPDATE",
                    profile_name: getProfileName(),
                    balance: G.__my_balance,
                  }, "*");
                }
                if (Array.isArray(me.cs) && me.cs.length > 0) {
                  G.__my_cards = me.cs;
                  window.postMessage({
                    type: "AUTOTOOL_CARDS_DEALT",
                    profile_name: getProfileName(),
                    cards: G.__my_cards,
                    first_turn: p.aid !== undefined ? { sit: p.aid } : null,
                  }, "*");
                } else {
                  // Chưa chia bài -> đảm bảo bài là rỗng
                  G.__my_cards = [];
                }
              }
              if (partner && partner.rmC !== undefined) {
                G.__partner_cards_count = partner.rmC;
              }

              // Xác định mã bàn. RID 1..28 là các bàn cố định hợp lệ, không
              // được coi là "Chống Vây" rồi thay bằng RID mặc định $100.
              let rid = (p.ri && p.ri.rid) || p.rid || G.__ws_pending_rid || null;
              const isChongVay = !rid || Number(rid) === -1 || String(rid) === "100";
              const fixedRidByBet = {
                "100_2": 2, "100_4": 1, "500_2": 4, "500_4": 3,
                "1000_2": 6, "1000_4": 5, "2000_2": 8, "2000_4": 7,
                "5000_2": 10, "5000_4": 9, "10000_2": 12, "10000_4": 11,
                "20000_2": 14, "20000_4": 13, "50000_2": 16, "50000_4": 15,
                "100000_2": 18, "100000_4": 17, "200000_2": 20, "200000_4": 19,
                "500000_2": 22, "500000_4": 21, "1000000_2": 24, "1000000_4": 23,
                "2000000_2": 26, "2000000_4": 25, "5000000_2": 28, "5000000_4": 27,
              };
              const roomBet = Number(p.b || 0);
              const roomMu = Number(p.Mu || 2);
              const fallbackRid = fixedRidByBet[`${roomBet}_${roomMu}`] || (roomMu === 2 ? 2 : 1);
              const targetRid = rid && !isNaN(Number(rid)) && Number(rid) > 0
                ? Number(rid)
                : fallbackRid;

              const totalPlayers = (p.ps || []).length;
              const isAloneEmpty = (!partner && strangers.length === 0 && totalPlayers === 1 && !!me);
              const hasStrangerOrFull = (strangers.length > 0 || (totalPlayers > 1 && !partner));

              G.__last_room_info = {
                rid: targetRid,
                raw_rid: isChongVay ? null : Number(rid),
                rn: p.rn || (p.Mu === 2 ? "Bàn Solo $100" : "Bàn $100"),
                b: p.b || 100,
                Mu: p.Mu || 2,
                is_chong_vay: isChongVay,
                partner_found: !!partner,
                partner_name: partner ? (partner.dn || partner.u) : null,
                has_stranger: strangers.length > 0,
                player_count: totalPlayers,
                is_verified_empty: isAloneEmpty,
              };
              G.__ws_last_room_id = targetRid;

              // Bắn thông tin vào bàn lên isolated content.js
              window.postMessage({
                type: "AUTOTOOL_ROOM_INFO",
                profile_name: getProfileName(),
                room_info: G.__last_room_info,
                players: G.__room_players,
                partner: partner,
                strangers: strangers,
                guests: strangers,
                state: G.__room_state,
              }, "*");

              // Phân định vai trò: Anchor (Chủ bàn) hay Sub (Phụ / Khách vào theo lệnh)
              const isSubProfile = isSubMatchProfile();

              // Chốt cuối ở extension: không phát lời mời/không đứng lại sai
              // mức cược dù một engine cũ hoặc frame trễ đã đưa vào nhầm RID.
              // CHỈ áp khi đang chạy gom bàn. Chơi tay thì người dùng có
              // quyền ngồi bất kỳ bàn nào, không được tự out.
              const expectedBet = isAutoEngaged() ? Number(G.__target_hunt_bet || 0) : 0;
              const actualBet = Number(p.b || (G.__last_room_info && G.__last_room_info.b) || 0);
              if (expectedBet > 0 && actualBet > 0 && expectedBet !== actualBet) {
                console.warn(`[AutoTool V3] Sai mức cược: bàn $${actualBet}, cấu hình $${expectedBet} -> rời bàn, không mời đồng đội.`);
                if (!isSubProfile) {
                  window.postMessage({
                    type: "AUTOTOOL_CANCEL_ROOM_INVITE",
                    profile_name: getProfileName(),
                    rid: targetRid,
                    reason: `Sai mức cược $${actualBet}, yêu cầu $${expectedBet}`,
                  }, "*");
                }
                setTimeout(() => G.__autotool_exec_leave(), 150);
                return;
              }

              // --- LOGIC TỰ ĐỘNG SĂN BÀN & ĐIỀU PHỐI VÀO BÀN TRỐNG CHUẨN XÁC ---
              // Chưa bấm "GOM BÀN & XẢ" (hoặc đã bấm Dừng) -> KHÔNG tự động gì
              // hết: không out khi gặp khách lạ, không Sẵn sàng/Bắt đầu, không
              // mời đồng đội. Chỉ đọc trạng thái để hiển thị.
              if (!isAutoEngaged()) {
                // vẫn cập nhật HUD/state ở trên, chỉ dừng phần hành động
              } else if (partner) {
                // 1. ĐÃ KHỚP ĐỒNG ĐỘI THÀNH CÔNG TRONG BÀN!
                triggerVerifiedMatchReadyAndStart(partner.dn || partner.u, "cmd:202 RoomPlayers");
              } else if (hasStrangerOrFull) {
                // 2. BÀN CÓ KHÁCH LẠ HOẶC BÀN FULL
                const guestSS = strangers.some((x) => x && (x.aRd === true || x.aRd === "true" || x.ss === true || x.ready === true));

                // ĐANG CHỜ ĐỒNG ĐỘI -> LUÔN OUT, không bao giờ bắt đầu với khách lạ.
                // Guard cũ đọc __AUTOTOOL_AUTO_HUNT, mà luồng gom bàn đặt cờ đó
                // = false trên mọi trang, nên nó không gác gì cả.
                if (!dangChoDongDoi() && G.__auto_start_guest_ss && !isSubProfile) {
                  // Chế độ bắt đầu với khách SS: CHỈ áp dụng khi KHÔNG trong hunt mode
                  if (guestSS) {
                    console.log("[AutoTool V3] ⚡ PHÁT HIỆN KHÁCH LẠ ĐÃ SẴN SÀNG (SS) & BẬT 'Bắt đầu nếu khách SS'! KÍCH HOẠT BẮT ĐẦU NGAY!");
                    G.__is_matched_locked = true;
                    G.__autotool_exec_start();
                    window.postMessage({
                      type: "AUTOTOOL_GUEST_SS_STARTED",
                      profile_name: getProfileName(),
                      strangers: strangers,
                    }, "*");
                    return;
                  }
                  // Nếu khách chưa bấm SS: Chờ tối đa 3 giây xem khách có bấm SS không
                  if (!G.__guest_ss_wait_timer) {
                    console.log("[AutoTool V3] Bàn có khách lạ chưa SS, chờ tối đa 3s xem khách có SẴN SÀNG (SS) không...");
                    G.__guest_ss_wait_timer = setTimeout(() => {
                      G.__guest_ss_wait_timer = null;
                      if (!G.__game_in_progress && !G.__is_matched_locked) {
                        console.log("[AutoTool V3] Quá 3s khách không SS -> Rời bàn về sảnh!");
                        G.__autotool_exec_leave();
                      }
                    }, 3000);
                  }
                  return;
                }

                // Không bật bắt đầu với khách hoặc là SubProfile -> Thoát bàn ngay!
                const guestNames = strangers.map((g) => g.dn || g.u || "Khách").join(", ") || "Bàn đầy người";
                console.warn(`[AutoTool V3] Phát hiện bàn có người lạ / Full: ${guestNames} -> HỦY LỆNH & Out bàn ngay!`);
                if (G.__backoff) G.__backoff.onFailure(false);

                if (G.__hunt_wait_timer) {
                  clearTimeout(G.__hunt_wait_timer);
                  G.__hunt_wait_timer = null;
                }

                // Nếu là Anchor: Phát ngay tín hiệu CANCEL lên Hub để hủy lệnh cho B!
                if (!isSubProfile) {
                  window.postMessage({
                    type: "AUTOTOOL_CANCEL_ROOM_INVITE",
                    profile_name: getProfileName(),
                    rid: targetRid,
                    reason: `Thấy khách lạ/Bàn full: ${guestNames}`,
                  }, "*");
                }

                window.postMessage({
                  type: "AUTOTOOL_AUTO_LEAVING",
                  profile_name: getProfileName(),
                  reason: `Thấy khách lạ/Bàn full: ${guestNames}`,
                }, "*");

                // Out an toàn (350 - 550ms) để server kịp xử lý trạng thái rời ghế
                const leaveDelay = 350 + Math.floor(Math.random() * 200);
                setTimeout(() => {
                  G.__autotool_exec_leave();
                }, leaveDelay);

              } else if (isAloneEmpty) {
                  // 3. BÀN 100% TRỐNG (CHỈ CÓ 1 MÌNH)!
                  if (isSubProfile) {
                    // Profile phụ không được tự ý ngồi giữ bàn trống một mình khi không có chủ bàn A
                    // NGOẠI LỆ: nếu đang theo LỜI MỜI (JOIN_ROOM) của chủ bàn thì CHỜ chủ bàn vào,
                    // không tự out 100ms (tránh "2 acc gặp nhau nhưng chưa kịp xác minh đã out mất").
                    const waitingInvite = !!(G.__active_room_invite && (Date.now() - G.__active_room_invite.ts) < 20000);
                    if (waitingInvite) {
                      console.warn("[AutoTool V3] Nick phụ vào bàn trống theo lời mời chủ bàn -> CHỜ chủ bàn vào, không tự out!");
                    } else {
                    console.warn("[AutoTool V3] Nick phụ vào bàn trống nhưng KHÔNG CÓ chủ bàn -> Out về sảnh chờ lệnh!");
                    window.postMessage({
                      type: "AUTOTOOL_AUTO_LEAVING",
                      profile_name: getProfileName(),
                      reason: "Nick phụ không thấy chủ bàn trong bàn trống",
                    }, "*");
                    setTimeout(() => {
                      G.__autotool_exec_leave();
                    }, 100);
                    }
                  } else {
                    if (!G.__AUTOTOOL_AUTO_HUNT) {
                      // Đã bấm Dừng (hoặc chưa bật Săn bàn): ngồi im KHÔNG tự mời đồng đội
                      // -> chặn zombie "gom bàn lặp lại" sau khi Dừng.
                      console.log(`[AutoTool V3] Ngồi 1 mình bàn #${targetRid} nhưng SĂN BÀN đang TẮT -> KHÔNG mời đồng đội (đứng im chờ lệnh).`);
                    } else {
                    // Profile A (Chính / Anchor): ĐÂY LÀ BÀN TRỐNG ĐÃ XÁC MINH 100% -> PHÁT LỆNH GỌI ĐỒNG ĐỘI VÀO NGAY!
                    console.log(`[AutoTool V3] 🎯 >>> BÀN #${targetRid} 100% TRỐNG (Đang ngồi 1 mình)! GỌI ĐỒNG ĐỘI VÀO TỨC THÌ! <<<`);
                    window.postMessage({
                      type: "AUTOTOOL_ANCHOR_ROOM_VERIFIED_EMPTY",
                      profile_name: getProfileName(),
                      room_info: G.__last_room_info,
                      rid: targetRid,
                      b: p.b || 100,
                      Mu: p.Mu || 2,
                    }, "*");

                    if (!G.__is_matched_locked) {
                      if (G.__hunt_wait_timer) clearTimeout(G.__hunt_wait_timer);
                      console.log("[AutoTool V3] Đang giữ bàn trống, chờ đồng đội vào trong 5.0 giây...");
                      G.__hunt_wait_timer = setTimeout(() => {
                        if (G.__is_matched_locked) return;
                        if (!G.__last_room_info || !G.__last_room_info.partner_found) {
                          console.log("[AutoTool V3] Quá 5.0s chưa thấy đồng đội vào -> Tự động out để ghép lại!");
                          window.postMessage({
                            type: "AUTOTOOL_CANCEL_ROOM_INVITE",
                            profile_name: getProfileName(),
                            rid: targetRid,
                            reason: "Quá thời gian chờ đồng đội",
                          }, "*");
                          window.postMessage({
                            type: "AUTOTOOL_AUTO_LEAVING",
                            profile_name: getProfileName(),
                            reason: "Hết thời gian chờ đồng đội",
                          }, "*");
                          G.__autotool_exec_leave();
                        }
                      }, 5000);
                    }
                    } // Đóng guard "KHÔNG săn bàn -> đứng im, không mời đồng đội"
                  }
                }
              }

            // cmd 203: Rời phòng -> Về lại sảnh
            if (p.cmd === 203) {
              G.__room_players = [];
              G.__last_room_info = null;
              G.__ws_last_room_id = null;
              G.__ws_pending_rid = null;
              G.__is_matched_locked = false;
              // Dọn sạch Expected Anchor nếu không có lời mời bàn gần đây (< 5s)
              if (!G.__active_room_invite || (Date.now() - G.__active_room_invite.ts) > 5000) {
                G.__expected_anchor_dn  = null;
                G.__expected_anchor_u   = null;
                G.__expected_anchor_uid = null;
                G.__expected_anchor_profile = null;
                G.__active_room_invite = null;
              }
              if (G.__start_retry_timer) {
                clearInterval(G.__start_retry_timer);
                G.__start_retry_timer = null;
              }
              if (G.__hunt_wait_timer) {
                clearTimeout(G.__hunt_wait_timer);
                G.__hunt_wait_timer = null;
              }
              window.postMessage({
                type: "AUTOTOOL_ROOM_LEFT",
                profile_name: getProfileName(),
              }, "*");

              // Nếu đang bật Auto Hunt và là Account 1 (Anchor): Tự động tìm lại lượt mới với ADAPTIVE BACKOFF (#1)
              // TRỪ KHI TÀI KHOẢN ĐÃ BỊ ĐĂNG XUẤT -> KHÔNG gửi thêm bất kỳ lệnh WS nào (giữ phiên đăng nhập)
              if (G.__AUTOTOOL_AUTO_HUNT && !(typeof checkAndHandleLoggedOut === "function" && checkAndHandleLoggedOut())) {
                if (isAnchorMatchProfile()) {
                  if (G.__hunt_retry_timer) clearTimeout(G.__hunt_retry_timer);

                  // ADAPTIVE BACKOFF (#1): Tự động co giãn thời gian chờ thông minh (2.2s - 8s) chống Rate-Limit "Bạn thao tác quá nhanh"
                  const jitterDelay = G.__backoff ? G.__backoff.next() : (3200 + Math.floor(Math.random() * 1000));
                  console.log(`[AutoTool V3] [Adaptive Backoff #1] Tự động thử lại lượt ghép mới sau ${jitterDelay}ms (Base: ${G.__backoff ? G.__backoff.current : 2200}ms)...`);

                  G.__hunt_retry_timer = setTimeout(() => {
                    window.postMessage({
                      type: "AUTOTOOL_HUNT_RETRYING",
                      profile_name: getProfileName(),
                      delay_ms: jitterDelay,
                    }, "*");
                    G.__autotool_exec_join(null, G.__target_hunt_bet || 100, G.__target_hunt_mu || 2);
                  }, jitterDelay);
                }
              }
            }

            // cmd 308: Join phòng thành công (KHÔNG lấy cmd 305 sảnh)
            if (p.cmd === 308) {
              const rid = (p.ri && p.ri.rid) || p.rid || G.__ws_pending_rid;
              if (rid && Number(rid) > 0 && Number(rid) !== 100) {
                G.__ws_pending_rid = Number(rid);
                if (G.__last_room_info) {
                  G.__last_room_info.rid = Number(rid);
                  G.__last_room_info.is_verified_empty = false;
                } else {
                  G.__last_room_info = {
                    rid: Number(rid),
                    b: p.b || 100,
                    Mu: p.Mu || 2,
                    rn: `Bàn #${rid}`,
                    is_verified_empty: false,
                  };
                }
                // TUYỆT ĐỐI KHÔNG gửi AUTOTOOL_ROOM_INFO tại cmd 308 vì chưa biết danh sách người chơi!
                // Phải đợi cmd 202 để check bàn trống 100% trước khi gửi lệnh mời B!
              }
            }

            // cmd 364 / 363: Người chơi trong phòng Sẵn Sàng (Ready)
            if (p.cmd === 364 || p.cmd === 363) {
              const rUid = p.uid || (p.fu && p.fu.uid);
              const isOther = rUid ? !isMe({ uid: rUid }) : true;
              if (isOther && (p.aRd === true || p.aRd === "true" || p.aRd === 1)) {
                console.log("[AutoTool V3] ⚡ Nhận gói tin SẴN SÀNG từ đối phương (cmd " + p.cmd + ")!");
                // Nhánh này TỪNG không có lớp gác nào: không isAutoEngaged,
                // không kiểm vai trò, không kiểm đang chờ đồng đội. Bất kỳ ai
                // bấm Sẵn Sàng là ván TIỀN THẬT chạy — kể cả khi người dùng
                // không hề bật tool (cờ guest_ss còn sót từ lượt chạy trước),
                // và kể cả khi nick phụ đang chờ ở sảnh để vào cùng bàn.
                if (!isAutoEngaged()) {
                  console.log("[AutoTool V3] Chưa kích hoạt tool -> bỏ qua, không tự Bắt đầu.");
                } else if (isSubMatchProfile()) {
                  console.log("[AutoTool V3] Nick phụ không được tự Bắt đầu.");
                } else if (dangChoDongDoi()) {
                  console.log("[AutoTool V3] Đang chờ đồng đội -> KHÔNG bắt đầu với người lạ.");
                } else if (G.__auto_start_guest_ss && !G.__game_in_progress) {
                  console.log("[AutoTool V3] ⚡ 'Bắt đầu nếu khách SS' đang bật -> KÍCH HOẠT BẮT ĐẦU NGAY!");
                  G.__is_matched_locked = true;
                  if (G.__guest_ss_wait_timer) {
                    clearTimeout(G.__guest_ss_wait_timer);
                    G.__guest_ss_wait_timer = null;
                  }
                  G.__autotool_exec_start();
                }
              }
            }

            // cmd 250: Chia bài & Bắt đầu ván (Cards dealt)
            if (p.cmd === 250) {
              // DỪNG NGAY LẬP TỨC VÒNG LẶP RETRY BẮT ĐẦU VÁN
              if (G.__start_retry_timer) {
                clearInterval(G.__start_retry_timer);
                G.__start_retry_timer = null;
              }
              const cards = p.cs || [];
              if (Array.isArray(cards) && cards.length > 0) {
                G.__my_cards = cards;
                G.__autotool_round_play_count = 0;
                // ĐẾM BÀI: bắt đầu ván mới -> xoá danh sách lá đã ra bàn.
                G.__cards_played = [];
                G.__game_in_progress = true;
                G.__last_table_cards = null;
                G.__last_table_player = null;
                console.log(`[AutoTool V3] 🃏 ĐÃ NHẬN BÀI CHIA (${cards.length} lá): [${cards.join(", ")}]`);
                window.postMessage({
                  type: "AUTOTOOL_CARDS_DEALT",
                  profile_name: getProfileName(),
                  cards: cards,
                  first_turn: p.tP,
                }, "*");
                // Nếu mình là người được chỉ định đi trước
                if (p.tP && isMe(p.tP)) {
                  console.log("[AutoTool V3] >>> TÔI ĐƯỢC CHỈ ĐỊNH ĐI TRƯỚC! Chuẩn bị đánh bài... <<<");
                  handleAutoTurn();
                }
              }
            }

            // cmd 251: Cập nhật hành động Đánh bài / Bỏ lượt & Chuyển lượt
            if (p.cmd === 251) {
              const fp = p.fP || {};
              const tp = p.tP || {};

              if (fp.pS === 1 && Array.isArray(fp.dCs) && fp.dCs.length > 0) {
                // Có người vừa đánh bài
                // ĐẾM BÀI: mọi lá đánh ra bàn đều công khai (ai ngồi bàn cũng
                // thấy). Gom lại để suy ra tập lá CÒN ẨN.
                if (!Array.isArray(G.__cards_played)) G.__cards_played = [];
                for (const c of fp.dCs) {
                  if (G.__cards_played.indexOf(c) < 0) G.__cards_played.push(c);
                }
                G.__last_table_cards = fp.dCs;
                G.__last_table_player = fp;
                if (isMe(fp)) {
                  // Tôi vừa đánh thành công nhóm bài này
                  G.__my_cards = (G.__my_cards || []).filter((c) => !fp.dCs.includes(c));
                  G.__autotool_round_play_count = Number(G.__autotool_round_play_count || 0) + 1;
                  console.log(`[AutoTool V3] Đã đánh [${fp.dCs.join(", ")}], bài trên tay còn ${G.__my_cards.length} lá.`);
                  window.postMessage({
                    type: "AUTOTOOL_CARDS_UPDATED",
                    profile_name: getProfileName(),
                    cards: G.__my_cards,
                    played_cards: fp.dCs,
                    actor: fp.dn || fp.u || getProfileName(),
                    remaining: G.__my_cards.length,
                  }, "*");
                } else if (isPartner(fp)) {
                  if (G.__partner_cards_count !== undefined) {
                    G.__partner_cards_count = Math.max(0, G.__partner_cards_count - fp.dCs.length);
                  }
                  window.postMessage({
                    type: "AUTOTOOL_PARTNER_PLAYED",
                    profile_name: getProfileName(),
                    played_cards: fp.dCs,
                    partner_name: fp.dn || fp.u,
                  }, "*");
                }
              } else if (fp.pS === 2) {
                // Có người vừa Bỏ lượt / Pass
                console.log(`[AutoTool V3] Người chơi ${fp.dn || fp.u} BỎ LƯỢT (Pass).`);
                if (!isMe(fp)) {
                  // Đối phương bỏ lượt -> bàn trống, chuẩn bị vòng tự do mới!
                  G.__last_table_cards = null;
                  G.__last_table_player = null;
                  window.postMessage({
                    type: "AUTOTOOL_PARTNER_PASSED",
                    profile_name: getProfileName(),
                    partner_name: fp.dn || fp.u,
                  }, "*");
                }
              }

              // Kiểm tra xem có phải tới lượt của mình không
              if (tp && isMe(tp)) {
                console.log(`[AutoTool V3] >>> TỚI LƯỢT CỦA TÔI! Bài trên tay: ${G.__my_cards ? G.__my_cards.length : 0} lá <<<`);
                handleAutoTurn();
              }
            }

            // cmd 252: Kết thúc ván bài (Game Ended)
            if (p.cmd === 252) {
              if (G.__start_retry_timer) {
                clearInterval(G.__start_retry_timer);
                G.__start_retry_timer = null;
              }
              G.__game_in_progress = false;
              G.__my_cards = [];
              G.__last_table_cards = null;
              G.__last_table_player = null;
              const winner = p.fP ? (p.fP.dn || p.fP.u || "Người thắng") : "Kết thúc ván";
              console.log(`[AutoTool V3] 🏆 VÁN BÀI KẾT THÚC! Người thắng: ${winner}`);
              window.postMessage({
                type: "AUTOTOOL_GAME_ENDED",
                profile_name: getProfileName(),
                winner: winner,
                result: p,
              }, "*");

              // Account phụ xả xong PHẢI rời bàn để nhường chỗ cho khách ngoài.
              // Trước đây canh `__AUTOTOOL_AUTO_HUNT`, nhưng controller ở chế độ
              // backend-driven LUÔN tắt cờ đó (để không có hai engine cùng join)
              // -> nhánh này chết, phụ ngồi lì trong bàn sau khi đánh xong.
              // Canh cổng kích hoạt mới: đang chạy gom bàn thì phụ tự out.
              // Controller cũng ra lệnh out ở phía server; lệnh rời bàn trùng
              // nhau vô hại vì _do_leave_room kiểm tra đã ở sảnh thì bỏ qua.
              if (isAutoEngaged() && isSubMatchProfile()) {
                console.log("[AutoTool V3] Account phụ đã xả xong -> tự rời bàn về sảnh chọn bàn.");
                setTimeout(() => G.__autotool_exec_leave(), 700);
              }

              // VÒNG LẶP CHƠI TIẾP TỰ ĐỘNG (CONTINUOUS LOOP):
              if (G.__AUTOTOOL_AUTO_HUNT) {
                // 1. Tự động gửi Sẵn Sàng sau 1.5s
                setTimeout(() => {
                  console.log("[AutoTool V3] Tự động gửi SẴN SÀNG (cmd 363) cho ván kế tiếp...");
                  G.__autotool_exec_ready();
                }, 1500);

                // 2. Chủ bàn tự động gửi Bắt Đầu sau 2.5s
                if (isAnchorMatchProfile()) {
                  setTimeout(() => {
                    console.log("[AutoTool V3] Chủ bàn tự động gửi BẮT ĐẦU (cmd 364) cho ván kế tiếp!");
                    G.__autotool_exec_start();
                  }, 2500);
                }
              }
            }
          }
        } catch (_) {}
      }
    } catch (_) {}
  };

  // 1. Patch WebSocket Constructor
  const OrigWebSocket = G.WebSocket;
  if (OrigWebSocket) {
    const PatchedWebSocket = function (...args) {
      const ws = new OrigWebSocket(...args);
      try {
        if (!G.__ws_instances.includes(ws)) G.__ws_instances.push(ws);
        ws.addEventListener("message", (e) => {
          try {
            if (typeof e.data === "string" && e.data.includes('"Simms"')) {
              G.__ws_simms_instance = ws;
            }
          } catch (_) {}
          push("recv", e.data);
        });
      } catch (_) {}
      return ws;
    };
    PatchedWebSocket.prototype = OrigWebSocket.prototype;
    PatchedWebSocket.CONNECTING = OrigWebSocket.CONNECTING;
    PatchedWebSocket.OPEN = OrigWebSocket.OPEN;
    PatchedWebSocket.CLOSING = OrigWebSocket.CLOSING;
    PatchedWebSocket.CLOSED = OrigWebSocket.CLOSED;
    G.WebSocket = PatchedWebSocket;

    // 2. Patch WebSocket.prototype.send
    const origSend = OrigWebSocket.prototype.send;
    OrigWebSocket.prototype.send = function (data) {
      try {
        if (!G.__ws_instances.includes(this)) G.__ws_instances.push(this);
        if (typeof data === "string" && data.includes('"Simms"')) {
          G.__ws_simms_instance = this;
        }
        push("send", data);
      } catch (_) {}
      return origSend.apply(this, arguments);
    };
  }

  // 3. Helper gửi WS qua game socket
  G.__ws_get_simms = function () {
    try {
      if (G.__ws_simms_instance && G.__ws_simms_instance.readyState === 1) {
        return G.__ws_simms_instance;
      }
      const list = (G.__ws_instances || []).filter((s) => s && s.readyState === 1);
      const found = list.find((s) => (s.url || "").toLowerCase().includes("carkgwaiz") || (s.url || "").toLowerCase().includes("simms"));
      if (found) {
        G.__ws_simms_instance = found;
        return found;
      }
      const gameWs = list.find((s) => !(s.url || "").includes("millicast") && !(s.url || "").includes("socket.io"));
      if (gameWs) {
        G.__ws_simms_instance = gameWs;
        return gameWs;
      }
      return list[0] || null;
    } catch (_) {
      return null;
    }
  };

  G.__ws_send = function (text) {
    try {
      const target = G.__ws_get_simms();
      if (target) {
        target.send(text);
        push("inject", text);
        return true;
      }
    } catch (_) {}
    return false;
  };

  G.__ws_send_channel = function (channel, text) {
    try {
      const list = (G.__ws_instances || []).filter((s) => s && s.readyState === 1);
      const hint = channel === "Simms" ? "carkgwaiz" : "mynisketgw";
      const target = list.find((s) => (s.url || "").includes(hint));
      if (target) {
        target.send(text);
        push("inject", text);
        return true;
      }
    } catch (_) {}
    return false;
  };

  // 4. API điều khiển game trực tiếp từ Extension Hub
  G.__autotool_exec_join = function (rid, bet, mu) {
    // KHÔNG gửi bất kỳ lệnh WS nào khi account đã bị đăng xuất (giữ phiên đăng nhập)
    if (typeof checkAndHandleLoggedOut === "function" && checkAndHandleLoggedOut()) {
      return false;
    }
    const cleanBet = Number(bet || 100);
    const cleanMu = Number(mu || 2);
    // RID 1..28 cũng là RID bàn cố định hợp lệ. Trước đây chỉ coi >28 là
    // direct RID nên rid=2 ($100) rơi xuống cmd=308 auto-join và có thể quay
    // lại bàn $500 của phiên trước.
    const specificRid = (rid && !isNaN(Number(rid)) && Number(rid) > 0) ? Number(rid) : null;

    // Account phụ không được tự join theo bất kỳ command/room event nào. Chỉ
    // controller mới cấp vé ngắn hạn ngay sau khi đã xác minh Anchor đang một
    // mình ở đúng bàn trống. Vé dùng một lần để chặn JOIN_ROOM trễ/zombie.
    if (isSubMatchProfile()) {
      const ticket = G.__AUTOTOOL_SUB_JOIN_TICKET;
      const validTicket = ticket && !ticket.used &&
        Number(ticket.rid) === Number(specificRid) &&
        Number(ticket.bet) === cleanBet && Number(ticket.mu || 2) === cleanMu &&
        Number(ticket.expires_at || 0) > Date.now();
      if (!validTicket) {
        console.warn(`[AutoTool V3] CHẶN Account phụ join rid=${rid}: không có vé xác nhận từ Account chính.`);
        return false;
      }
      ticket.used = true;
    }

    // CHỐNG FLOOD JOIN (bằng chứng ws_capture: 18 cặp LEAVE+308 trong 2s -> server
    // trả [4,false,...,102] từ chối liên tục, kẹt vĩnh viễn ở bàn cũ):
    // mỗi lệnh join thực sự cách nhau tối thiểu 2.5s (open) / 1.2s (rid cụ thể).
    const now = Date.now();
    const minGap = specificRid ? 1200 : 2500;
    if (G.__last_join_ts && (now - G.__last_join_ts) < minGap) {
      console.warn(`[AutoTool V3] [Anti-Flood] Bỏ qua lệnh join (cách lần trước ${now - G.__last_join_ts}ms < ${minGap}ms)!`);
      return false;
    }
    G.__last_join_ts = now;

    console.log(`[AutoTool V3] Thực thi lệnh JOIN phòng: bet=$${cleanBet}, slot=${cleanMu}, rid=${specificRid || 'auto'}...`);
    const simms = G.__ws_get_simms();
    if (!simms || simms.readyState !== 1) {
      console.warn("[AutoTool V3] Chưa tìm thấy socket Simms của game bài hoặc chưa kết nối!");
      return false;
    }

    const doJoin = () => {
      // Frame thật đã capture khi click tay bàn $100: [3,"Simms",2,""] .
      // Không gửi cmd=308 hoặc frame room-id kiểu cũ, vì game sẽ tự chọn lại
      // mức cược theo state trước đó (nguồn gốc vào nhầm $500).
      if (specificRid) {
        const fixedJoin = JSON.stringify([3, "Simms", specificRid, ""]);
        try {
          simms.send(fixedJoin);
          push("inject", fixedJoin);
          console.log(`[AutoTool V3] Đã gửi FIXED JOIN rid=${specificRid} ($${cleanBet}): ${fixedJoin}`);
          return true;
        } catch (e) {
          console.error("[AutoTool V3] Lỗi gửi fixed join:", e);
          return false;
        }
      }
      const payload308 = {
        cmd: 308,
        aid: 1,
        gid: 1, // Tiến Lên Đếm Lá
        b: cleanBet,
        Mu: cleanMu,
        iJ: true,
        inc: false,
        pwd: "",
      };
      const msg308 = JSON.stringify([6, "Simms", "channelPlugin", payload308]);

      let sent = false;
      try {
        simms.send(msg308);
        push("inject", msg308);
        console.log(`[AutoTool V3] Đã gửi lệnh vào bàn [cmd 308, cược $${cleanBet}, slot ${cleanMu}${specificRid ? ', rid=' + specificRid : ''}] thành công!`);
        sent = true;
      } catch (e) {
        console.error("[AutoTool V3] Lỗi gửi lệnh cmd 308:", e);
      }

      return sent;
    };

    const stillInsideTable = () => {
      try {
        return (G.__room_players && G.__room_players.length > 0) ||
               (G.__last_room_info && G.__last_room_info.rid > 0 && G.__last_room_info.rid !== 100) ||
               (typeof isInsideGameTable === "function" && isInsideGameTable());
      } catch (_) { return true; }
    };

    // Với open join (tìm bàn trống công cộng): Nếu client đang kẹt TRONG bàn cũ (vd bàn 500)
    // thì gửi LEAVE TRƯỚC để về sảnh, tránh game client tự động rejoin đúng bàn 500 (cũ)
    // làm lệch mức cược đã cấu hình. Nếu đã ở sảnh thì JOIN ngay không cần LEAVE.
    if (!specificRid) {
      if (stillInsideTable()) {
        try {
          simms.send('[4,"Simms",-1]');
          push("inject", '[4,"Simms",-1]');
          console.log(`[AutoTool V3] Đã gửi LEAVE trước để đảm bảo ở sảnh trước khi join bàn $${cleanBet}`);
        } catch (_) {}
        // KHÔNG join mù sau 400ms: chỉ join khi đã XÁC NHẬN rời được bàn cũ (game gửi
        // cmd 203 / xoá room_players). Nếu sau 1.2s vẫn kẹt trong bàn cũ -> HUỶ lượt
        // này (server sẽ thử lại vòng sau) chứ KHÔNG spam 308 để bị từ chối 102.
        let joined = false;
        const tryJoinWhenLobby = () => {
          if (G.__is_matched_locked) return;
          if (stillInsideTable()) {
            console.warn("[AutoTool V3] [Chống nhầm bàn] Vẫn còn TRONG bàn cũ sau LEAVE -> huỷ join lượt này, chờ vòng lặp mới!");
            G.__last_join_ts = 0; // cho phép vòng lặp sau thử lại sớm
            return;
          }
          if (!joined) {
            joined = true;
            doJoin();
          }
        };
        setTimeout(tryJoinWhenLobby, 550);
        setTimeout(tryJoinWhenLobby, 1200);
        return true; // Trả về true vì lệnh sẽ được thực thi sau khi xác nhận đã về sảnh
      }
      return doJoin();
    }

    // Với direct join (join theo rid cụ thể): join ngay không cần delay
    return doJoin();
  };

  function execCocosLeaveTable() {
    let clicked = false;
    try {
      if (typeof cc !== "undefined" && cc.director) {
        const scene = cc.director.getScene();
        if (scene) {
          // 1. Quét tìm trực tiếp nút Rời Bàn / Thoát nếu đã hiển thị
          function scanLeave(node, depth) {
            if (!node || depth > 30 || clicked) return;
            const name = (node.name || "").toLowerCase();
            const text = getCocosNodeText(node).toUpperCase();
            if ((text.includes("RỜI BÀN") || text.includes("ROI BAN") || text === "THOÁT" || text === "THOAT" ||
                 name === "btn_roiban" || name === "btn_roi_ban" || name === "btn_leave" || name === "btn_exit") &&
                node.active && (node.opacity === undefined || node.opacity > 0)) {
              clicked = clickCocosNode(node);
              if (clicked) {
                console.log(`[AutoTool V3] Cocos: Đã click nút rời bàn: name='${node.name}', text='${text}'`);
                return;
              }
            }
            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
              scanLeave(children[i], depth + 1);
              if (clicked) return;
            }
          }
          scanLeave(scene, 0);

          // 2. Nếu chưa thấy nút rời bàn, quét tìm nút Menu góc trên bên trái để mở drawer
          if (!clicked) {
            function scanMenu(node, depth) {
              if (!node || depth > 30 || clicked) return;
              const name = (node.name || "").toLowerCase();
              if ((name === "btn_menu" || name === "btn_nav" || name === "btn_arrow" || name === "btn_drawer" ||
                   name === "btn_expand" || name.includes("menu")) &&
                  node.active && (node.opacity === undefined || node.opacity > 0)) {
                clicked = clickCocosNode(node);
                if (clicked) {
                  console.log(`[AutoTool V3] Cocos: Đã click nút Menu bàn: name='${node.name}'`);
                  return;
                }
              }
              const children = node.children || [];
              for (let i = 0; i < children.length; i++) {
                scanMenu(children[i], depth + 1);
                if (clicked) return;
              }
            }
            scanMenu(scene, 0);
          }
        }
      }
    } catch (e) {
      console.warn("[AutoTool V3] Lỗi execCocosLeaveTable:", e);
    }
    return clicked;
  }

  G.__autotool_exec_leave = function () {
    console.log("[AutoTool V3] Thực thi lệnh RỜI BÀN về sảnh...");

    // 1. Quét Cocos tìm nút Rời Bàn / Menu
    execCocosLeaveTable();

    // 2. Click vật lý canvas tại nút [>] góc trên bên trái (~0.040 sw, 0.238 sh)
    dispatchCanvasClick(0.040, 0.238);

    // 3. Sau 200ms: Quét Cocos lần 2 và click nút RỜI BÀN (drawer mở ra)
    setTimeout(() => {
      execCocosLeaveTable();
      dispatchCanvasClick(0.085, 0.238);
      dispatchCanvasClick(0.085, 0.300);
      setTimeout(() => {
        dismissPopupsAndBanners();
      }, 250);
    }, 200);

    // 4. Gửi gói rời phòng. `cmd:308` là JOIN (không phải leave); trước đây
    // gửi 308 không có b/Mu sau lúc rời bàn khiến game tự xếp lại vào bàn mặc
    // định $500, dù UI đang chọn $100.
    const simms = G.__ws_get_simms();
    if (simms && simms.readyState === 1) {
      try {
        simms.send('[4,"Simms",-1]');
        push("inject", '[4,"Simms",-1]');
      } catch (_) {}
      try {
        const pLeave = '[6,"Simms","channelPlugin",{"cmd":203}]';
        simms.send(pLeave);
        push("inject", pLeave);
      } catch (_) {}
    }
    return true;
  };

  G.__autotool_exec_ready = function () {
    // KHÔNG gửi lệnh khi tài khoản đã bị đăng xuất (giữ phiên đăng nhập)
    if (typeof checkAndHandleLoggedOut === "function" && checkAndHandleLoggedOut()) {
      return false;
    }
    // BẢO VỆ CHẶN: Trong một lượt ghép cặp, tuyệt đối không Ready với khách
    // lạ. `auto_start_guest_ss` chỉ dành cho luồng chơi khách độc lập, không
    // được cho phép Account chính/phụ Start trước khi xác minh đồng đội.
    const partner = (G.__room_players || []).find(isPartner);
    const matchingPair = G.__AUTOTOOL_MATCH_ROLE === "anchor" || G.__AUTOTOOL_MATCH_ROLE === "sub";
    if (!partner && G.__room_players && G.__room_players.length > 1 && (matchingPair || !G.__auto_start_guest_ss)) {
      console.warn("[AutoTool V3] BẢO VỆ CHẶN: Trong lượt ghép cặp bàn có khách lạ, không có đồng đội -> từ chối Ready/Start và rời bàn.");
      G.__autotool_exec_leave();
      return false;
    }
    console.log("[AutoTool V3] Thực thi lệnh SẴN SÀNG & BẮT ĐẦU (Cocos Native + WebSocket cmd 5 + cmd 363)...");

    // 1. Kích hoạt trực tiếp trên Engine Cocos Creator
    execCocosReadyOrStart();

    // 2. Bắn song song các gói tin chuẩn xác 100% của HitClub
    const p1 = '[6,"Simms","channelPlugin",{"cmd":363,"aRd":"true"}]';
    const p2 = '[5,"Simms",-1,{"cmd":5}]';
    const simms = G.__ws_get_simms();
    if (simms && simms.readyState === 1) {
      try { simms.send(p1); push("inject", p1); } catch (_) {}
      try { simms.send(p2); push("inject", p2); } catch (_) {}
      setTimeout(() => {
        try {
          if (simms.readyState === 1) {
            simms.send(p2);
            push("inject", p2);
          }
        } catch (_) {}
      }, 150);
    }

    // Nhắc lại Cocos sau 250ms nếu lần đầu chưa kịp nhận
    setTimeout(() => {
      execCocosReadyOrStart();
    }, 250);

    return true;
  };

  G.__autotool_exec_start = function () {
    console.log("[AutoTool V3] Thực thi lệnh BẮT ĐẦU VÁN (Cocos + cmd 5)...");
    execCocosReadyOrStart();
    const p = '[5,"Simms",-1,{"cmd":5}]';
    const simms = G.__ws_get_simms();
    if (simms && simms.readyState === 1) {
      try { simms.send(p); push("inject", p); } catch (_) {}
      setTimeout(() => {
        try { if (simms.readyState === 1) simms.send(p); } catch (_) {}
      }, 200);
      return true;
    }
    return false;
  };

  G.__autotool_exec_play = function (cardIds) {
    if (!Array.isArray(cardIds) || cardIds.length === 0) return false;
    console.log("[AutoTool V3] >>> THỰC THI GỬI LỆNH ĐÁNH BÀI (cmd 253):", cardIds);
    const packet = JSON.stringify([5, "Simms", -1, { cmd: 253, cs: cardIds }]);
    const simms = G.__ws_get_simms();
    if (simms && simms.readyState === 1) {
      simms.send(packet);
      push("inject", packet);
      return true;
    }
    return false;
  };

  G.__autotool_exec_pass = function () {
    console.log("[AutoTool V3] >>> THỰC THI GỬI LỆNH BỎ LƯỢT / PASS (cmd 254) <<<");
    const packet = JSON.stringify([5, "Simms", -1, { cmd: 254 }]);
    const simms = G.__ws_get_simms();
    if (simms && simms.readyState === 1) {
      simms.send(packet);
      push("inject", packet);
      return true;
    }
    return false;
  };

  G.__autotool_exec_discard = function (cardIds) {
    return G.__autotool_exec_play(cardIds);
  };

  // Nếu user đã bấm DỪNG ở phiên trước (localStorage) thì KHÔNG tự bật săn bàn
  // lại khi trang reload — nếu không sau khi Dừng, mỗi lần F5/navigation là
  // Account 1 lại tự chạy gom bàn (bug "bấm Dừng không dừng hẳn").
  const AUTOTOOL_STOP_KEY = "AUTOTOOL_STOPPED";
  let __user_stopped = false;
  try {
    __user_stopped = localStorage.getItem(AUTOTOOL_STOP_KEY) === "1";
  } catch (_) {}

  // Không tự chạy khi tab load/reload. Chỉ controller mới khởi tạo một lượt
  // ghép bàn và chỉ định rõ anchor/sub; nhờ vậy nick phụ luôn ở sảnh lắng nghe.
  G.__AUTOTOOL_ARMED = false;
  G.__AUTOTOOL_AUTO_HUNT = false;
  G.__AUTOTOOL_ENGAGED = false;   // chỉ controller mới được bật
  G.__cards_played = [];          // đếm bài: lá đã ra bàn trong ván này
  G.__autotool_partners = [];

  function persistStopState(stopped) {
    try {
      if (stopped) localStorage.setItem(AUTOTOOL_STOP_KEY, "1");
      else localStorage.removeItem(AUTOTOOL_STOP_KEY);
    } catch (_) {}
    // Đồng bộ trạng thái lên isolated world (cập nhật nút "Săn Bàn" trên overlay)
    window.postMessage({ type: "AUTOTOOL_HUNT_STATE", auto_hunt: !stopped, armed: !stopped }, "*");
  }

  // Lắng nghe lệnh từ Extension isolated script (từ Backend Hub gửi xuống)
  window.addEventListener("message", (event) => {
    if (!event.data) return;

    if (event.data.type === "AUTOTOOL_SET_ARM") {
      G.__AUTOTOOL_ARMED = !!event.data.armed;
      if (!G.__AUTOTOOL_ARMED) {
        G.__AUTOTOOL_AUTO_HUNT = false;
        persistStopState(true);
      }
      console.log(`[AutoTool V3] Tình trạng ARM chuyển sang: ${G.__AUTOTOOL_ARMED ? "BẬT" : "TẠM DỪNG"}`);
      return;
    }

    if (event.data.type === "AUTOTOOL_SET_HUNT") {
      G.__AUTOTOOL_AUTO_HUNT = !!event.data.auto_hunt;
      persistStopState(!G.__AUTOTOOL_AUTO_HUNT);
      if (event.data.auto_start_guest_ss !== undefined) {
        G.__auto_start_guest_ss = !!event.data.auto_start_guest_ss;
      }
      if (event.data.auto_xa !== undefined) {
        G.__AUTOTOOL_AUTO_DISCARD = !!event.data.auto_xa;
      }
      console.log(`[AutoTool V3] Chế độ SĂN BÀN & AUTO OUT chuyển sang: ${G.__AUTOTOOL_AUTO_HUNT ? "BẬT" : "TẮT"}, guest_ss=${G.__auto_start_guest_ss}`);
      return;
    }

    if (event.data.type === "AUTOTOOL_SYNC_PARTNERS" && Array.isArray(event.data.partners)) {
      G.__autotool_partners = event.data.partners;
      console.log("[AutoTool V3] Đã đồng bộ danh sách đồng đội:", G.__autotool_partners);
      return;
    }

    if (event.data.type === "AUTOTOOL_CONFIRM_MATCH") {
      const partner = event.data.partner || "Đồng đội";
      console.log(`[AutoTool V3] >>> NHẬN TÍN HIỆU CONFIRM_MATCH (${partner}) TỪ ISOLATED WORLD! <<<`);
      if (typeof triggerVerifiedMatchReadyAndStart === "function") {
        triggerVerifiedMatchReadyAndStart(partner, "Event Confirm");
      }
      return;
    }

    if (event.data.type !== "AUTOTOOL_EXEC_COMMAND") return;
    const { action, data } = event.data;
    console.log(`[AutoTool V3] Nhận lệnh từ Hub qua Extension Bridge: action=${action}`, data);

    if (action === "CONFIRM_MATCH") {
      const partner = (data && (data.partner || data.source)) || "Đồng đội";
      console.log(`[AutoTool V3] >>> HUB XÁC NHẬN: ĐỒNG ĐỘI ${partner} ĐÃ VÀO BÀN! <<<`);
      if (typeof triggerVerifiedMatchReadyAndStart === "function") {
        triggerVerifiedMatchReadyAndStart(partner, "Hub Confirm");
      }
    } else if (action === "PARTNER_CARDS_SHARED" && data && Array.isArray(data.cards)) {
      const expectedPartners = Array.isArray(G.__AUTOTOOL_PARTNER_PROFILES) ? G.__AUTOTOOL_PARTNER_PROFILES : [];
      const compact = (value) => String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
      const sharedBy = compact(data.source_profile);
      if (expectedPartners.length && !expectedPartners.some((name) => compact(name) === sharedBy)) {
        console.log(`[AutoTool V3] Bỏ qua bài của profile không cùng cặp: ${data.source_profile}`);
        return;
      }
      G.__partner_cards = data.cards;
      console.log(`[AutoTool V3] 👥 Nhận bài đồng đội (${data.cards.length} lá):`, data.cards);
      window.postMessage({
        type: "AUTOTOOL_PARTNER_CARDS_UPDATE",
        partner_name: data.source_profile || "Đồng đội",
        cards: data.cards,
      }, "*");
    } else if (action === "JOIN_ROOM" && data && data.rid) {
      const ticket = G.__AUTOTOOL_SUB_JOIN_TICKET;
      const hasValidTicket = ticket && !ticket.used && Number(ticket.rid) === Number(data.rid) &&
        Number(ticket.expires_at || 0) > Date.now();
      if (isSubMatchProfile() && !hasValidTicket) {
        console.warn(`[AutoTool V3] Bỏ JOIN_ROOM rid=${data.rid}: Account phụ chỉ nhận lệnh có vé controller.`);
        return;
      }
      // KIỂM TRA ĐIỀU KIỆN CHẶN: Chỉ bỏ qua nếu THỰC SỰ đang ngồi trong ván (>= 2 người và đang chơi)
      const currentPlayersCount = (G.__room_players || []).length;
      if (currentPlayersCount < 2) {
        // Đang ở sảnh hoặc ngồi 1 mình -> Reset ngay lập tức toàn bộ cờ khóa cũ để vào phòng mới!
        G.__is_matched_locked = false;
        G.__game_in_progress = false;
        G.__last_room_info = null;
      } else if (G.__game_in_progress) {
        console.log(`[AutoTool V3] Đang trong ván bài thực sự (${(G.__last_room_info && G.__last_room_info.rid) || 2}) -> BỎ QUA lệnh JOIN_ROOM mới!`);
        return;
      }

      // ===== CRITICAL FIX: PRE-LOAD ANCHOR IDENTITY TRƯỚC KHI VÀO PHÒNG =====
      const anchorDn   = (data.anchor_dn  || "").trim().toLowerCase();
      const anchorU    = (data.anchor_u   || "").trim().toLowerCase();
      const anchorUid  = (data.anchor_uid || "").trim();
      const srcProfile = (data.source_profile || "").trim().toLowerCase();

      // Lưu NGAY thông tin lời mời vào bàn
      G.__active_room_invite = {
        rid: Number(data.rid),
        source_profile: srcProfile,
        anchor_dn: anchorDn,
        anchor_u: anchorU,
        anchor_uid: anchorUid,
        ts: Date.now(),
      };

      G.__expected_anchor_profile = srcProfile;
      if (anchorDn)  G.__expected_anchor_dn  = anchorDn;
      if (anchorU)   G.__expected_anchor_u   = anchorU;
      if (anchorUid) G.__expected_anchor_uid = anchorUid;

      // Luôn inject srcProfile, anchorDn, anchorU, anchorUid vào partners list
      const currentPartners = G.__autotool_partners || [];
      const toAdd = [srcProfile, anchorDn, anchorU, anchorUid].filter(Boolean);
      for (const id of toAdd) {
        if (id && !currentPartners.some((p) => (typeof p === "string" ? p.toLowerCase() : "") === id.toLowerCase())) {
          currentPartners.push(id);
        }
      }
      G.__autotool_partners = currentPartners;
      console.log(`[AutoTool V3] [JOIN_ROOM] Pre-load anchor: src='${srcProfile}', dn='${anchorDn}', uid='${anchorUid}' -> Partners: ${currentPartners.length} entries`);
      // ===== END CRITICAL FIX =====

      // KHÔNG tự gọi __autotool_exec_join ở đây nữa: backend sẽ bắn lệnh join TRỰC TIẾP
      // qua page.evaluate (single-source-of-truth), tránh double-join & lệch phiên bản
      // hàm join (server_join_fn bị content_main re-inject đè khi page navigate).
    } else if (action === "LEAVE_ROOM") {
      G.__is_matched_locked = false;
      G.__game_in_progress = false;
      G.__last_room_info = null;
      if (G.__start_retry_timer) {
        clearInterval(G.__start_retry_timer);
        G.__start_retry_timer = null;
      }
      G.__autotool_exec_leave();
    } else if (action === "READY") {
      G.__autotool_exec_ready();
    } else if (action === "START") {
      G.__autotool_exec_start();
    } else if (action === "DISCARD_CARDS" && data && data.cards) {
      G.__autotool_exec_discard(data.cards);
    } else if (action === "SYNC_PARTNERS" && data && Array.isArray(data.partners)) {
      G.__autotool_partners = data.partners;
    } else if (action === "ENTER_TLDL_LOBBY") {
      const mu = (data && data.mu) || 2;
      autoEnterTLDLLobby(mu);
    } else if (action === "DISMISS_POPUPS") {
      dismissPopupsAndBanners();
    } else if (action === "START_HUNT") {
      const bet = (data && data.bet) || 100;
      const mu = (data && data.mu) || 2;
      G.__target_hunt_bet = bet;
      G.__target_hunt_mu = mu;

      const isSub = isSubMatchProfile();

      if (isSub) {
        // Nick phụ: Tuyệt đối không tự ý săn bàn hay click join phòng! Chờ ở sảnh nhận lệnh JOIN_ROOM từ Account 1
        console.log(`[AutoTool V3] Nick phụ (${getProfileName()}): Ở sảnh bàn Đếm Lá chờ lệnh mời từ Account 1...`);
        G.__AUTOTOOL_AUTO_HUNT = false;
        G.__is_hunt_initiator = false;
        persistStopState(true);
        return;
      }

      G.__AUTOTOOL_AUTO_HUNT = true;
      G.__is_hunt_initiator = true;
      persistStopState(false);
      G.__is_matched_locked = false;
      G.__game_in_progress = false;
      G.__last_room_info = null;
      if (data && data.auto_start_guest_ss !== undefined) {
        G.__auto_start_guest_ss = !!data.auto_start_guest_ss;
      }
      if (data && data.auto_xa !== undefined) {
        G.__AUTOTOOL_AUTO_DISCARD = !!data.auto_xa;
      }
      console.log(`[AutoTool V3] Account 1 bắt đầu SĂN BÀN: Cược ${bet}, Slot ${mu}, guest_ss=${G.__auto_start_guest_ss}...`);
      G.__autotool_exec_join(null, bet, mu);
    } else if (action === "STOP_HUNT") {
      console.log("[AutoTool V3] Nhận lệnh STOP_HUNT -> Dừng chế độ săn bàn & rời bàn");
      G.__AUTOTOOL_AUTO_HUNT = false;
      G.__AUTOTOOL_ARMED = false;
      // Xoá cấu hình lượt chạy: mức cược/vai trò/auto-xả còn sót lại sẽ tiếp
      // tục điều khiển hành vi khi người dùng chơi tay sau đó.
      clearRunConfig();
      persistStopState(true);
      G.__is_hunt_initiator = false;
      G.__is_matched_locked = false;
      G.__game_in_progress = false;
      G.__last_room_info = null;
      G.__room_players = [];
      G.__active_room_invite = null;
      if (G.__start_retry_timer) {
        clearInterval(G.__start_retry_timer);
        G.__start_retry_timer = null;
      }
      if (G.__hunt_wait_timer) {
        clearTimeout(G.__hunt_wait_timer);
        G.__hunt_wait_timer = null;
      }
      if (G.__hunt_retry_timer) {
        clearTimeout(G.__hunt_retry_timer);
        G.__hunt_retry_timer = null;
      }
      if (G.__guest_ss_wait_timer) {
        clearTimeout(G.__guest_ss_wait_timer);
        G.__guest_ss_wait_timer = null;
      }
      if (G.__auto_turn_timer) {
        clearTimeout(G.__auto_turn_timer);
        G.__auto_turn_timer = null;
      }
      G.__autotool_exec_leave();
    } else if (action === "RESET_STATE") {
      console.log("[AutoTool V3] Nhận lệnh RESET_STATE -> Làm sạch biến khóa & bộ nhớ tạm");
      G.__is_matched_locked = false;
      G.__game_in_progress = false;
      G.__last_room_info = null;
      G.__room_players = [];
      G.__active_room_invite = null;
      if (G.__start_retry_timer) {
        clearInterval(G.__start_retry_timer);
        G.__start_retry_timer = null;
      }
      if (G.__hunt_wait_timer) {
        clearTimeout(G.__hunt_wait_timer);
        G.__hunt_wait_timer = null;
      }
      if (G.__hunt_retry_timer) {
        clearTimeout(G.__hunt_retry_timer);
        G.__hunt_retry_timer = null;
      }
      if (G.__guest_ss_wait_timer) {
        clearTimeout(G.__guest_ss_wait_timer);
        G.__guest_ss_wait_timer = null;
      }
    }
  });

  // Thông báo trạng thái hunt thực tế cho overlay (nếu trước đó user đã Dừng)
  try {
    window.postMessage({
      type: "AUTOTOOL_HUNT_STATE",
      auto_hunt: !!G.__AUTOTOOL_AUTO_HUNT,
      armed: !!G.__AUTOTOOL_ARMED,
    }, "*");
  } catch (_) {}

  console.log(`[AutoTool V3] Main World Engine & WebSocket Bridge đã sẵn sàng (Auto-Hunt: ${G.__AUTOTOOL_AUTO_HUNT ? "BẬT" : "ĐÃ DỪNG/TẮT"})!`);
})();

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
  G.__AUTOTOOL_AUTO_DISCARD = true;

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

  function getMyRole() {
    if (G.__AUTOTOOL_ROLE) return G.__AUTOTOOL_ROLE;
    const pName = (getProfileName() || "").toLowerCase();
    if (pName.includes("2") || pName.includes("sub") || pName.includes("phu")) {
      return "dump";
    }
    return "winner";
  }

  function findBestPlay(myCards, tableCards, role, isPartnerTurn, partnerCardsCount = 13) {
    if (!myCards || !myCards.length) return null;
    const combs = findCombinations(myCards);

    // 1. LƯỢT TỰ DO (Free Turn / Mở ván hoặc đối phương vừa Pass)
    if (!tableCards || tableCards.length === 0) {
      if (role === "dump") {
        if (myCards.length === 1) {
          // Nick xả chỉ còn 1 lá -> PASS nhường đường cho Winner về Nhất!
          console.log("[AutoTool V3] [Role: DUMP] Còn đúng 1 lá rác đáy bài -> BỎ LƯỢT (cmd 254) để giữ thua tối thiểu!");
          return null;
        }
        // Ưu tiên xả: Sảnh dài nhất -> Tứ quý -> Ba -> Đôi -> Heo -> Rác to nhất
        if (combs.straights.length > 0) return combs.straights[0];
        if (combs.quads.length > 0) return combs.quads[combs.quads.length - 1];
        if (combs.triples.length > 0) return combs.triples[combs.triples.length - 1];
        if (combs.pairs.length > 0) return combs.pairs[combs.pairs.length - 1];
        const heos = myCards.filter((c) => getCardVal(c) === 15);
        if (heos.length > 0) return [heos[0]];
        const sorted = sortCards(myCards);
        return [sorted[sorted.length - 1]];
      } else {
        // Winner: Đánh từ nhóm nhỏ nhất để xả sạch bài về Nhất
        if (combs.straights.length > 0) return combs.straights[combs.straights.length - 1];
        if (combs.triples.length > 0) return combs.triples[0];
        if (combs.pairs.length > 0) return combs.pairs[0];
        return [sortCards(myCards)[0]];
      }
    }

    // 2. LƯỢT ĐÈ BÀI (Follow Turn)
    if (isPartnerTurn) {
      if (role === "winner") {
        // Đồng đội (Dump) vừa xả bài:
        if (partnerCardsCount > 1) {
          // Đồng đội còn nhiều bài -> Winner PASS để đồng đội có lượt tự do xả tiếp!
          console.log(`[AutoTool V3] [Role: WINNER] Đồng đội còn ${partnerCardsCount} lá bài -> PASS nhường xả tiếp!`);
          return null;
        } else {
          // Đồng đội chỉ còn 1 lá bài -> Winner đè để giành lượt và về Nhất!
          for (const cat of ["singles", "pairs", "triples", "straights"]) {
            for (const cand of combs[cat]) {
              if (canBeat(cand, tableCards)) return cand;
            }
          }
          return null;
        }
      } else {
        // Role là Dump: Đồng đội (Winner) vừa đánh bài
        if (myCards.length > 1) {
          for (const cat of ["straights", "triples", "pairs", "singles"]) {
            const list = combs[cat].slice().reverse();
            for (const cand of list) {
              if (canBeat(cand, tableCards)) return cand;
            }
          }
        }
        return null;
      }
    } else {
      // Đánh với khách lạ: Tìm nhóm nhỏ nhất đè được
      for (const cat of ["singles", "pairs", "triples", "straights"]) {
        for (const cand of combs[cat]) {
          if (canBeat(cand, tableCards)) return cand;
        }
      }
      return null;
    }
  }

  function handleAutoTurn() {
    if (G.__auto_turn_timer) {
      clearTimeout(G.__auto_turn_timer);
      G.__auto_turn_timer = null;
    }
    if (!G.__AUTOTOOL_AUTO_DISCARD) return;
    if (!G.__my_cards || !G.__my_cards.length) return;

    // Giãn cách an toàn 400ms - 750ms để mô phỏng tự nhiên và chống phát hiện bot
    const delay = 400 + Math.floor(Math.random() * 350);
    G.__auto_turn_timer = setTimeout(() => {
      if (!G.__my_cards || !G.__my_cards.length) return;
      const role = getMyRole();
      const isPartnerActor = G.__last_table_player ? isPartner(G.__last_table_player) : false;
      const partnerCardsCount = G.__partner_cards_count || 13;

      console.log(`[AutoTool V3] Tới lượt của tôi! Role=${role}, Bài trên tay: ${G.__my_cards.length} lá, Bàn: ${JSON.stringify(G.__last_table_cards)}`);

      const play = findBestPlay(G.__my_cards, G.__last_table_cards, role, isPartnerActor, partnerCardsCount);

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

      // Bắt lệnh gửi từ client (send) để lưu trước rid người chơi chủ động bấm vào
      if (dir === "send") {
        if (text.includes('"rid":')) {
          const m = text.match(/"rid"\s*:\s*(\d+)/);
          if (m && m[1] && Number(m[1]) > 0 && Number(m[1]) !== 100) {
            G.__ws_pending_rid = Number(m[1]);
          }
        } else if (text.includes('[3,"Simms",1,')) {
          const m = text.match(/\[3,"Simms",1,\s*"?(\d+)"?/);
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
              if (p.uid || p.id) G.__my_uid = p.uid || p.id;
              if (p.dn || p.u) {
                const realUser = p.dn || p.u;
                G.__my_dn = realUser;
                if (!G.__AUTOTOOL_PROFILE_NAME || G.__AUTOTOOL_PROFILE_NAME.includes("HitClub")) {
                  G.__AUTOTOOL_PROFILE_NAME = realUser;
                  window.postMessage({
                    type: "AUTOTOOL_INIT_PROFILE",
                    profile_name: realUser,
                  }, "*");
                }
              }
              const gold = (p.As && p.As.gold !== undefined) ? p.As.gold : (p.gold !== undefined ? p.gold : (p.m !== undefined ? p.m : (p.g !== undefined ? p.g : null)));
              if (gold !== null && !isNaN(Number(gold))) {
                window.postMessage({
                  type: "AUTOTOOL_BALANCE_UPDATE",
                  profile_name: getProfileName(),
                  balance: Number(gold),
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

            // cmd 202: Danh sách người chơi trong phòng & thông tin bàn
            if (p.cmd === 202) {
              G.__room_players = p.ps || [];
              G.__room_state = p.gS;

              function isMe(x) {
                if (!x) return false;
                if (G.__my_uid && x.uid && String(x.uid) === String(G.__my_uid)) return true;
                if (G.__my_dn) {
                  const d1 = String(x.dn || x.u || "").trim().toLowerCase();
                  const d2 = String(G.__my_dn).trim().toLowerCase();
                  if (d1 === d2) return true;
                }
                const pName = (getProfileName() || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                const dn = (x.dn || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                const u = (x.u || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                if (pName && (dn === pName || u === pName)) return true;
                return false;
              }

              function isPartner(x) {
                if (!x || isMe(x)) return false;
                const dn = (x.dn || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                const u = (x.u || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                const partnerList = (G.__autotool_partners || []).map((pt) => (pt || "").toLowerCase().replace(/[^a-z0-9]/g, ""));
                for (const pt of partnerList) {
                  if (!pt) continue;
                  if (dn === pt || u === pt) return true;
                  if (dn.length >= 6 && pt.length >= 6 && dn.slice(0, 8) === pt.slice(0, 8)) return true;
                }
                // Heuristic dự phòng: Nếu cả 2 account cùng prefix nick test
                const myName = (getProfileName() || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                if (myName.length >= 8 && dn.length >= 8 && dn.slice(0, 8) === myName.slice(0, 8)) {
                  return true;
                }
                return false;
              }

              const me = (p.ps || []).find(isMe) || (p.ps && p.ps[0]);
              const partner = (p.ps || []).find(isPartner);
              const strangers = (p.ps || []).filter((x) => !isMe(x) && !isPartner(x));

              // Cập nhật số dư & bài của tài khoản nếu có trong packet
              if (me) {
                const meGold = me.As && me.As.gold !== undefined ? me.As.gold : (me.m !== undefined ? me.m : null);
                if (meGold !== null && !isNaN(Number(meGold))) {
                  window.postMessage({
                    type: "AUTOTOOL_BALANCE_UPDATE",
                    profile_name: getProfileName(),
                    balance: Number(meGold),
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
                }
              }
              if (partner && partner.rmC !== undefined) {
                G.__partner_cards_count = partner.rmC;
              }

              // Xác định mã bàn: Có ID cụ thể hoặc Bàn Chống Vây
              let rid = (p.ri && p.ri.rid) || p.rid || G.__ws_pending_rid || null;
              const isChongVay = !rid || rid === -1 || String(rid) === "100" || rid === 2 || rid === 1;
              const targetRid = rid && !isNaN(Number(rid)) && Number(rid) > 28 ? Number(rid) : (p.Mu === 2 ? 2 : 1);

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

              // --- LOGIC TỰ ĐỘNG SĂN BÀN & AUTO OUT KHI THẤY KHÁCH LẠ ---
              if (G.__AUTOTOOL_AUTO_HUNT) {
                if (G.__hunt_wait_timer) {
                  clearTimeout(G.__hunt_wait_timer);
                  G.__hunt_wait_timer = null;
                }

                if (partner) {
                  // ĐÃ KHỚP ĐỒNG ĐỘI THÀNH CÔNG!
                  console.log(`[AutoTool V3] KHỚP ĐỒNG ĐỘI THÀNH CÔNG: ${partner.dn}!`);
                  if (G.__hunt_wait_timer) {
                    clearTimeout(G.__hunt_wait_timer);
                    G.__hunt_wait_timer = null;
                  }
                  window.postMessage({
                    type: "AUTOTOOL_MATCH_SUCCESS",
                    profile_name: getProfileName(),
                    partner_name: partner.dn || partner.u,
                  }, "*");

                  // 1. Tự động gửi lệnh Sẵn Sàng (cmd 363)
                  setTimeout(() => {
                    console.log("[AutoTool V3] Tự động gửi lệnh SẴN SÀNG (cmd 363)...");
                    G.__autotool_exec_ready();
                  }, 250);

                  // 2. Tự động gửi lệnh BẮT ĐẦU VÁN (cmd 364) nếu là Chủ Bàn (hoặc Account 1)
                  const isHost = me && (me.C === true || me.sit === 0 || (getProfileName() || "").toLowerCase().includes("1"));
                  if (isHost) {
                    setTimeout(() => {
                      console.log("[AutoTool V3] Là chủ bàn -> Tự động gửi lệnh BẮT ĐẦU VÁN (cmd 364)!");
                      G.__autotool_exec_start();
                    }, 650);
                  }
                } else if (strangers.length > 0) {
                  // CÓ KHÁCH LẠ -> TỰ ĐỘNG OUT BÀN TỨC THÌ (300ms)
                  const guestNames = strangers.map((g) => g.dn || g.u || "Khách").join(", ");
                  console.warn(`[AutoTool V3] Phát hiện khách lạ: ${guestNames} -> Tự động out sau 300ms!`);
                  window.postMessage({
                    type: "AUTOTOOL_AUTO_LEAVING",
                    profile_name: getProfileName(),
                    reason: `Thấy khách lạ: ${guestNames}`,
                  }, "*");
                  setTimeout(() => {
                    G.__autotool_exec_leave();
                  }, 300);
                } else {
                  // ĐANG NGỒI 1 MÌNH CHỜ ĐỒNG ĐỘI -> Chờ 5.0s, nếu quá 5.0s không ai vào thì out tìm lại
                  console.log("[AutoTool V3] Đang ngồi một mình, chờ đồng đội trong 5.0 giây...");
                  G.__hunt_wait_timer = setTimeout(() => {
                    if (!G.__last_room_info || !G.__last_room_info.partner_found) {
                      console.log("[AutoTool V3] Quá 5.0s chưa thấy đồng đội vào -> Tự động out để ghép lại!");
                      window.postMessage({
                        type: "AUTOTOOL_AUTO_LEAVING",
                        profile_name: getProfileName(),
                        reason: "Hết thời gian chờ đồng đội",
                      }, "*");
                      G.__autotool_exec_leave();
                    }
                  }, 5000);
                }
              }
            }

            // cmd 203: Rời phòng -> Về lại sảnh
            if (p.cmd === 203) {
              G.__room_players = [];
              G.__last_room_info = null;
              G.__ws_last_room_id = null;
              G.__ws_pending_rid = null;
              if (G.__hunt_wait_timer) {
                clearTimeout(G.__hunt_wait_timer);
                G.__hunt_wait_timer = null;
              }
              window.postMessage({
                type: "AUTOTOOL_ROOM_LEFT",
                profile_name: getProfileName(),
              }, "*");

              // Nếu đang bật Auto Hunt và là Account 1 (Anchor): Tự động tìm lại lượt mới với ANTI-FLOOD JITTER
              if (G.__AUTOTOOL_AUTO_HUNT) {
                const pName = (getProfileName() || "").toLowerCase();
                if (pName.includes("1") || G.__is_hunt_initiator) {
                  if (G.__hunt_retry_timer) clearTimeout(G.__hunt_retry_timer);

                  // ANTI-FLOOD JITTER: Giãn cách ngẫu nhiên an toàn 850ms - 1400ms
                  const jitterDelay = 850 + Math.floor(Math.random() * 550);
                  console.log(`[AutoTool V3] [Anti-Flood Jitter] Tự động thử lại lượt ghép mới sau ${jitterDelay}ms...`);

                  G.__hunt_retry_timer = setTimeout(() => {
                    window.postMessage({
                      type: "AUTOTOOL_HUNT_RETRYING",
                      profile_name: getProfileName(),
                      delay_ms: jitterDelay,
                    }, "*");
                    G.__autotool_exec_join(2, 100, 2);
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
                } else {
                  G.__last_room_info = {
                    rid: Number(rid),
                    b: p.b || 100,
                    Mu: p.Mu || 2,
                    rn: `Bàn #${rid}`,
                  };
                }
                window.postMessage({
                  type: "AUTOTOOL_ROOM_INFO",
                  profile_name: getProfileName(),
                  room_info: G.__last_room_info,
                }, "*");
              }
            }

            // cmd 250: Chia bài & Bắt đầu ván (Cards dealt)
            if (p.cmd === 250) {
              const cards = p.cs || [];
              if (Array.isArray(cards) && cards.length > 0) {
                G.__my_cards = cards;
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
                G.__last_table_cards = fp.dCs;
                G.__last_table_player = fp;
                if (isMe(fp)) {
                  // Tôi vừa đánh thành công nhóm bài này
                  G.__my_cards = (G.__my_cards || []).filter((c) => !fp.dCs.includes(c));
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

              // VÒNG LẶP CHƠI TIẾP TỰ ĐỘNG (CONTINUOUS LOOP):
              if (G.__AUTOTOOL_AUTO_HUNT) {
                // 1. Tự động gửi Sẵn Sàng sau 1.5s
                setTimeout(() => {
                  console.log("[AutoTool V3] Tự động gửi SẴN SÀNG (cmd 363) cho ván kế tiếp...");
                  G.__autotool_exec_ready();
                }, 1500);

                // 2. Chủ bàn tự động gửi Bắt Đầu sau 2.5s
                const pName = (getProfileName() || "").toLowerCase();
                if (pName.includes("1") || G.__is_hunt_initiator) {
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
        ws.addEventListener("message", (e) => push("recv", e.data));
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
        push("send", data);
      } catch (_) {}
      return origSend.apply(this, arguments);
    };
  }

  // 3. Helper gửi WS qua game socket
  G.__ws_get_simms = function () {
    try {
      const list = (G.__ws_instances || []).filter((s) => s && s.readyState === 1);
      return list.find((s) => (s.url || "").includes("carkgwaiz") || (s.url || "").includes("simms")) || null;
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
  G.__autotool_exec_join = function (rid, bet = 100, mu = 2) {
    console.log(`[AutoTool V3] Thực thi lệnh JOIN phòng: rid=${rid}, bet=${bet}, mu=${mu}...`);
    const simms = G.__ws_get_simms();
    if (!simms) {
      console.warn("[AutoTool V3] Chưa tìm thấy socket Simms của game bài!");
      return false;
    }

    // Bản đồ mức cược sang room id cố định của Hitclub Tiến Lên Đếm Lá (từ cmd 300)
    const betRoomMap = {
      "100_2": 2,  "100_4": 1,
      "500_2": 4,  "500_4": 3,
      "1000_2": 6, "1000_4": 5,
      "2000_2": 8, "2000_4": 7,
      "5000_2": 10, "5000_4": 9,
      "10000_2": 12, "10000_4": 11,
      "20000_2": 14, "20000_4": 13,
      "50000_2": 16, "50000_4": 15,
      "100000_2": 18, "100000_4": 17,
      "200000_2": 20, "200000_4": 19,
      "500000_2": 22, "500000_4": 21,
      "1000000_2": 24, "1000000_4": 23,
      "2000000_2": 26, "2000000_4": 25,
      "5000000_2": 28, "5000000_4": 27,
    };

    let targetRoomId = -1;
    const betKey = `${Number(bet || 100)}_${Number(mu || 2)}`;

    if (rid && !isNaN(Number(rid)) && Number(rid) >= 1 && Number(rid) <= 28) {
      // Room ID thuộc danh mục cược cố định (ví dụ 2 = Solo 100, 1 = 4 người 100)
      targetRoomId = Number(rid);
    } else if (betRoomMap[betKey]) {
      // Tra theo mức cược và số người (Solo 2 người hay 4 người)
      targetRoomId = betRoomMap[betKey];
    } else if (rid && !isNaN(Number(rid)) && Number(rid) > 28 && Number(rid) !== 100) {
      // Bàn có ID cụ thể từ danh sách
      targetRoomId = Number(rid);
    } else {
      // Mặc định Bàn Solo 100 (rid = 2)
      targetRoomId = 2;
    }

    // Packet chuẩn xác 100% của Hitclub: [3, "Simms", roomId, password]
    const joinMsg = JSON.stringify([3, "Simms", targetRoomId, ""]);

    try {
      simms.send(joinMsg);
      push("inject", joinMsg);
      console.log(`[AutoTool V3] Đã gửi lệnh vào bàn [3, "Simms", ${targetRoomId}, ""] thành công!`);
      return true;
    } catch (e) {
      console.error("[AutoTool V3] Lỗi gửi lệnh vào bàn:", e);
      return false;
    }
  };

  G.__autotool_exec_leave = function () {
    console.log("[AutoTool V3] Thực thi lệnh RỜI BÀN về sảnh...");
    const simms = G.__ws_get_simms();
    if (simms) {
      try {
        simms.send('[4,"Simms",-1]');
        push("inject", '[4,"Simms",-1]');
        return true;
      } catch (_) {}
    }
    return false;
  };

  G.__autotool_exec_ready = function () {
    console.log("[AutoTool V3] Thực thi lệnh SẴN SÀNG...");
    G.__ws_send_channel("Simms", '[6,"Simms","channelPlugin",{"cmd":363,"aRd":"true"}]');
    G.__ws_send('[6,"Simms","channelPlugin",{"cmd":363,"aRd":"true"}]');
    return true;
  };

  G.__autotool_exec_start = function () {
    console.log("[AutoTool V3] Thực thi lệnh BẮT ĐẦU VÁN...");
    G.__ws_send_channel("Simms", '[6,"Simms","channelPlugin",{"cmd":364}]');
    G.__ws_send('[6,"Simms","channelPlugin",{"cmd":364}]');
    return true;
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

  G.__AUTOTOOL_ARMED = true;
  G.__AUTOTOOL_AUTO_HUNT = true; // Mặc định BẬT tự động săn bàn & out khi thấy khách lạ
  G.__autotool_partners = [];

  // Lắng nghe lệnh từ Extension isolated script (từ Backend Hub gửi xuống)
  window.addEventListener("message", (event) => {
    if (!event.data) return;

    if (event.data.type === "AUTOTOOL_SET_ARM") {
      G.__AUTOTOOL_ARMED = !!event.data.armed;
      console.log(`[AutoTool V3] Tình trạng ARM chuyển sang: ${G.__AUTOTOOL_ARMED ? "BẬT" : "TẠM DỪNG"}`);
      return;
    }

    if (event.data.type === "AUTOTOOL_SET_HUNT") {
      G.__AUTOTOOL_AUTO_HUNT = !!event.data.auto_hunt;
      console.log(`[AutoTool V3] Chế độ SĂN BÀN & AUTO OUT chuyển sang: ${G.__AUTOTOOL_AUTO_HUNT ? "BẬT" : "TẮT"}`);
      return;
    }

    if (event.data.type === "AUTOTOOL_SYNC_PARTNERS" && Array.isArray(event.data.partners)) {
      G.__autotool_partners = event.data.partners;
      console.log("[AutoTool V3] Đã đồng bộ danh sách đồng đội:", G.__autotool_partners);
      return;
    }

    if (event.data.type === "AUTOTOOL_CONFIRM_MATCH") {
      console.log("[AutoTool V3] >>> NHẬN TÍN HIỆU CONFIRM_MATCH TỪ ĐỒNG ĐỘI! HỦY TIMEOUT & AUTO START! <<<");
      if (G.__hunt_wait_timer) {
        clearTimeout(G.__hunt_wait_timer);
        G.__hunt_wait_timer = null;
      }
      if (G.__last_room_info) {
        G.__last_room_info.partner_found = true;
      }
      // Tự động Sẵn Sàng và Bắt Đầu ván
      setTimeout(() => {
        G.__autotool_exec_ready();
      }, 250);
      const pName = (getProfileName() || "").toLowerCase();
      if (pName.includes("1") || G.__is_hunt_initiator) {
        setTimeout(() => {
          console.log("[AutoTool V3] Tự động BẮT ĐẦU VÁN (cmd 364) sau khi đồng đội vào bàn!");
          G.__autotool_exec_start();
        }, 650);
      }
      return;
    }

    if (event.data.type !== "AUTOTOOL_EXEC_COMMAND") return;
    const { action, data } = event.data;
    console.log(`[AutoTool V3] Nhận lệnh từ Hub qua Extension Bridge: action=${action}`, data);

    if (action === "CONFIRM_MATCH") {
      console.log("[AutoTool V3] >>> HUB XÁC NHẬN: ĐỒNG ĐỘI ĐÃ VÀO BÀN! HỦY LỆNH OUT & AUTO START! <<<");
      if (G.__hunt_wait_timer) {
        clearTimeout(G.__hunt_wait_timer);
        G.__hunt_wait_timer = null;
      }
      if (G.__last_room_info) {
        G.__last_room_info.partner_found = true;
      }
      setTimeout(() => {
        G.__autotool_exec_ready();
      }, 250);
      const pName = (getProfileName() || "").toLowerCase();
      if (pName.includes("1") || G.__is_hunt_initiator) {
        setTimeout(() => {
          console.log("[AutoTool V3] Tự động BẮT ĐẦU VÁN (cmd 364) sau khi đồng đội vào bàn!");
          G.__autotool_exec_start();
        }, 650);
      }
    } else if (action === "JOIN_ROOM" && data && data.rid) {
      G.__autotool_exec_join(data.rid, data.bet || 100, data.mu || 2);
    } else if (action === "LEAVE_ROOM") {
      G.__autotool_exec_leave();
    } else if (action === "READY") {
      G.__autotool_exec_ready();
    } else if (action === "START") {
      G.__autotool_exec_start();
    } else if (action === "DISCARD_CARDS" && data && data.cards) {
      G.__autotool_exec_discard(data.cards);
    } else if (action === "SYNC_PARTNERS" && data && Array.isArray(data.partners)) {
      G.__autotool_partners = data.partners;
    } else if (action === "START_HUNT") {
      G.__AUTOTOOL_AUTO_HUNT = true;
      G.__is_hunt_initiator = true;
      G.__autotool_exec_join(2, 100, 2);
    } else if (action === "STOP_HUNT") {
      G.__AUTOTOOL_AUTO_HUNT = false;
      G.__autotool_exec_leave();
    }
  });

  console.log("[AutoTool V3] Main World Engine & WebSocket Bridge đã sẵn sàng (Auto-Hunt: BẬT)!");
})();

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

  // Lấy định danh profile được inject từ Playwright hoặc localStorage
  function getProfileName() {
    return G.__AUTOTOOL_PROFILE_NAME || localStorage.getItem("AUTOTOOL_PROFILE_NAME") || document.title || "";
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
                const pName = (getProfileName() || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                const dn = (x.dn || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                const u = (x.u || "").toLowerCase().replace(/[^a-z0-9]/g, "");
                if (!pName) return false;
                if (dn === pName || u === pName) return true;
                if (dn.length >= 6 && pName.length >= 6) {
                  if (dn.slice(0, 8) === pName.slice(0, 8)) return true;
                }
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

              // Cập nhật số dư của tài khoản nếu có trong packet
              if (me) {
                const meGold = me.As && me.As.gold !== undefined ? me.As.gold : (me.m !== undefined ? me.m : null);
                if (meGold !== null && !isNaN(Number(meGold))) {
                  window.postMessage({
                    type: "AUTOTOOL_BALANCE_UPDATE",
                    profile_name: getProfileName(),
                    balance: Number(meGold),
                  }, "*");
                }
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
                  window.postMessage({
                    type: "AUTOTOOL_MATCH_SUCCESS",
                    profile_name: getProfileName(),
                    partner_name: partner.dn || partner.u,
                  }, "*");
                } else if (strangers.length > 0) {
                  // CÓ KHÁCH LẠ -> TỰ ĐỘNG OUT BÀN TỨC THÌ (350ms)
                  const guestNames = strangers.map((g) => g.dn || g.u || "Khách").join(", ");
                  console.warn(`[AutoTool V3] Phát hiện khách lạ: ${guestNames} -> Tự động out sau 350ms!`);
                  window.postMessage({
                    type: "AUTOTOOL_AUTO_LEAVING",
                    profile_name: getProfileName(),
                    reason: `Thấy khách lạ: ${guestNames}`,
                  }, "*");
                  setTimeout(() => {
                    G.__autotool_exec_leave();
                  }, 350);
                } else {
                  // ĐANG NGỒI 1 MÌNH CHỜ ĐỒNG ĐỘI -> Chờ 2.5s, nếu quá 2.5s không ai vào thì out tìm lại
                  console.log("[AutoTool V3] Đang ngồi một mình, chờ đồng đội trong 2.5 giây...");
                  G.__hunt_wait_timer = setTimeout(() => {
                    if (!G.__last_room_info || !G.__last_room_info.partner_found) {
                      console.log("[AutoTool V3] Quá 2.5s chưa thấy đồng đội vào -> Tự động out để ghép lại!");
                      window.postMessage({
                        type: "AUTOTOOL_AUTO_LEAVING",
                        profile_name: getProfileName(),
                        reason: "Hết thời gian chờ đồng đội",
                      }, "*");
                      G.__autotool_exec_leave();
                    }
                  }, 2500);
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

              // Nếu đang bật Auto Hunt và là Account 1 (Anchor): Tự động tìm lại lượt mới sau 700ms
              if (G.__AUTOTOOL_AUTO_HUNT) {
                const pName = (getProfileName() || "").toLowerCase();
                if (pName.includes("1") || G.__is_hunt_initiator) {
                  if (G.__hunt_retry_timer) clearTimeout(G.__hunt_retry_timer);
                  G.__hunt_retry_timer = setTimeout(() => {
                    console.log("[AutoTool V3] Tự động thử lại lượt ghép mới Bàn Solo 100...");
                    window.postMessage({
                      type: "AUTOTOOL_HUNT_RETRYING",
                      profile_name: getProfileName(),
                    }, "*");
                    G.__autotool_exec_join(2, 100, 2);
                  }, 700);
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

            // Bắt bài chia (Cards dealt)
            if (p.c || p.cards || (p.cmd && [310, 311, 312, 350].includes(p.cmd))) {
              const cards = p.c || p.cards || [];
              if (Array.isArray(cards) && cards.length > 0) {
                G.__my_cards = cards;
                window.postMessage({
                  type: "AUTOTOOL_BRIDGE_PACKET",
                  action: "CARDS_DEALT",
                  profile_name: getProfileName(),
                  cards: cards,
                }, "*");
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

  G.__autotool_exec_discard = function (cardIds) {
    console.log("[AutoTool V3] Thực thi lệnh ĐÁNH BÀI:", cardIds);
    if (Array.isArray(cardIds) && cardIds.length > 0) {
      const payload = { cmd: 352, c: cardIds };
      G.__ws_send_channel("Simms", JSON.stringify([6, "Simms", "channelPlugin", payload]));
    }
    return true;
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

    if (event.data.type !== "AUTOTOOL_EXEC_COMMAND") return;
    const { action, data } = event.data;
    console.log(`[AutoTool V3] Nhận lệnh từ Hub qua Extension Bridge: action=${action}`, data);

    if (action === "JOIN_ROOM" && data && data.rid) {
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

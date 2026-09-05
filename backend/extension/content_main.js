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
              const pName = (getProfileName() || "").toLowerCase();
              const me = (p.ps || []).find(x => x && (
                (x.dn && x.dn.toLowerCase() === pName) ||
                (x.u && x.u.toLowerCase() === pName) ||
                (x.uid && String(x.uid) === String(G.__AUTOTOOL_ACCOUNT_ID))
              ));

              // Chỉ kích hoạt bàn khi người chơi THỰC SỰ ĐANG NGỒI TẠI BÀN
              if (me || (p.ps && p.ps.length > 0)) {
                const meGold = me && me.As && me.As.gold !== undefined ? me.As.gold : (me && me.m !== undefined ? me.m : null);
                if (meGold !== null && !isNaN(Number(meGold))) {
                  window.postMessage({
                    type: "AUTOTOOL_BALANCE_UPDATE",
                    profile_name: getProfileName(),
                    balance: Number(meGold),
                  }, "*");
                }

                const rid = (p.ri && p.ri.rid) || G.__ws_pending_rid || null;
                G.__last_room_info = {
                  rid: rid,
                  rn: p.rn || (p.Mu === 2 ? `Bàn Solo $${p.b || 100}` : `Bàn $${p.b || 100}`),
                  b: p.b || 100,
                  Mu: p.Mu || 2,
                };
                G.__ws_last_room_id = rid;

                window.postMessage({
                  type: "AUTOTOOL_ROOM_INFO",
                  profile_name: getProfileName(),
                  room_info: G.__last_room_info,
                  players: G.__room_players,
                  state: G.__room_state,
                }, "*");
              }
            }

            // cmd 203: Rời phòng -> Về lại sảnh
            if (p.cmd === 203) {
              G.__room_players = [];
              G.__last_room_info = null;
              G.__ws_last_room_id = null;
              G.__ws_pending_rid = null;
              window.postMessage({
                type: "AUTOTOOL_ROOM_LEFT",
                profile_name: getProfileName(),
              }, "*");
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
  G.__ws_send = function (text) {
    try {
      const list = (G.__ws_instances || []).filter((s) => s && s.readyState === 1);
      const simms = list.find((s) => (s.url || "").includes("carkgwaiz") || (s.url || "").includes("simms"));
      const target = simms || list[0];
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
      const target = list.find((s) => (s.url || "").includes(hint)) || list[0];
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
    console.log(`[AutoTool V3] Thực thi lệnh JOIN phòng #${rid} ($${bet})...`);
    const payload = {
      cmd: 308, aid: 1, gid: 1, b: Number(bet), Mu: Number(mu),
      iJ: true, inc: false, pwd: "", rid: Number(rid)
    };
    G.__ws_send_channel("Simms", JSON.stringify([6, "Simms", "channelPlugin", payload]));
    G.__ws_send_channel("Simms", JSON.stringify([3, "Simms", 1, { rid: Number(rid) }]));
    G.__ws_send_channel("Simms", JSON.stringify([3, "Simms", 1, String(rid)]));
    G.__ws_send(JSON.stringify([6, "Simms", "channelPlugin", payload]));
    return true;
  };

  G.__autotool_exec_leave = function () {
    console.log("[AutoTool V3] Thực thi lệnh RỜI BÀN về sảnh...");
    G.__ws_send_channel("Simms", '[4,"Simms",-1]');
    G.__ws_send_channel("Simms", '[6,"Simms","channelPlugin",{"cmd":203}]');
    G.__ws_send('[4,"Simms",-1]');
    return true;
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

  // Lắng nghe lệnh từ Extension isolated script (từ Backend Hub gửi xuống)
  window.addEventListener("message", (event) => {
    if (!event.data) return;

    if (event.data.type === "AUTOTOOL_SET_ARM") {
      G.__AUTOTOOL_ARMED = !!event.data.armed;
      console.log(`[AutoTool V3] Tình trạng ARM chuyển sang: ${G.__AUTOTOOL_ARMED ? "BẬT" : "TẠM DỪNG"}`);
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
    }
  });

  console.log("[AutoTool V3] Main World Engine & WebSocket Bridge đã sẵn sàng!");
})();

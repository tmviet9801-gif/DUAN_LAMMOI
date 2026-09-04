// content_main.js — Chạy trong MAIN world của trang web (không bị CSP của game chặn).
// Intercept WebSocket của game Cocos/Wasm, ghi nhận room info, player list và hỗ trợ gửi lệnh WS.
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
            // cmd 202: Danh sách người chơi trong phòng & thông tin bàn
            if (p.cmd === 202) {
              G.__room_players = p.ps || [];
              G.__room_state = p.gS;
              if (p.ri && p.ri.rid) {
                G.__last_room_info = p.ri;
                G.__ws_last_room_id = p.ri.rid;
              } else if (!G.__last_room_info || !G.__last_room_info.rid) {
                G.__last_room_info = {
                  rid: null,
                  rn: p.Mu === 2 ? `Bàn Solo $${p.b || 100}` : `Bàn $${p.b || 100}`,
                  b: p.b || 100,
                  Mu: p.Mu || 2,
                };
              }
            }
            // cmd 203: Rời phòng
            if (p.cmd === 203) {
              G.__room_players = [];
              G.__last_room_info = null;
              G.__ws_last_room_id = null;
            }
            // cmd 305: Người chơi tham gia phòng / thông tin bàn
            if (p.cmd === 305) {
              if (p.ri && p.ri.rid) {
                G.__last_room_info = p.ri;
                G.__ws_last_room_id = p.ri.rid;
              }
              if (p.fu && G.__room_players) {
                const exists = G.__room_players.some((pl) => (pl.u && pl.u === p.fu.u) || (pl.dn && pl.dn === p.fu.dn));
                if (!exists) G.__room_players.push(p.fu);
              }
            }
            // cmd 308: Phản hồi join phòng thành công (chứa ri.rid thật)
            if (p.cmd === 308) {
              if (p.ri && p.ri.rid) {
                G.__last_room_info = p.ri;
                G.__ws_last_room_id = p.ri.rid;
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
      // Ưu tiên socket carkgwaiz (Simms / game chính)
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

  console.log("[AutoTool] Main world WebSocket hook đã kích hoạt thành công!");
})();

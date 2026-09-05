// Content script chạy ở ISOLATED world (document_start). Inject 1 thẻ <script>
// vào MAIN world (page context) để patch WebSocket.prototype của game — vì manifest
// content_scripts không hỗ trợ "world":"MAIN".
//
// PHẢI khớp logic với `_INJECT_JS` trong ws_sniffer.py: cùng guard `__ws_hooked`,
// cùng registry `__ws_instances`, cùng helper `__ws_send*` — để 2 hook không xung
// đột (ai load trước thì thắng, người kia no-op một cách nhất quán).
(function () {
  const mainWorldCode = function () {
    const G = globalThis;
    if (G.__ws_hooked) return;
    G.__ws_hooked = true;
    G.__ws_capture = [];
    G.__ws_map = {};
    G.__ws_instances = [];

    const push = (dir, data) => {
      try {
        let text = "";
        if (typeof data === "string") text = data;
        else if (data instanceof Blob) text = "[Blob " + data.size + "b]";
        else if (data instanceof ArrayBuffer) text = new TextDecoder().decode(data);
        else if (data && data.data !== undefined) text = typeof data.data === "string" ? data.data : "[binary]";
        else text = "[?]";
        G.__ws_capture.push({ ts: Date.now(), dir, text: String(text).slice(0, 8000) });
        if (G.__ws_capture.length > 3000) G.__ws_capture.splice(0, 1500);

        if (text.startsWith("[") && text.includes('"cmd"')) {
          try {
            const arr = JSON.parse(text);
            const p = (Array.isArray(arr) && arr.length > 1 && typeof arr[1] === "object") ? arr[1] : (arr.length > 3 && typeof arr[3] === "object" ? arr[3] : null);
            if (p) {
              if (p.cmd === 202) {
                G.__room_players = p.ps || [];
                G.__room_state = p.gS;
                G.__last_room_202 = p;

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
                const ri = G.__last_room_info;
                try {
                  window.top.postMessage({ type: "AUTOTOOL_ROOM_INFO", room_info: ri }, "*");
                } catch (_) {}
                try {
                  document.dispatchEvent(new CustomEvent("__autotool_room_event", { detail: ri }));
                } catch (_) {}

                // Tự động kiểm tra và phản ứng tức thời với khách lạ (out_guest)
                if (G.__auto_protect && G.__auto_protect.out_guest) {
                  const known = (G.__auto_protect.known_names || []).map((x) => String(x).toLowerCase().trim());
                  const ps = p.ps || [];
                  let hasStranger = false;
                  for (const ply of ps) {
                    const dn = String(ply.dn || "").toLowerCase().trim();
                    const u = String(ply.u || "").toLowerCase().trim();
                    const isKnown = known.some((k) => k && (k === dn || k === u || dn.indexOf(k) !== -1 || k.indexOf(dn) !== -1));
                    if (!isKnown && (dn || u)) {
                      hasStranger = true;
                      break;
                    }
                  }
                  if (hasStranger) {
                    console.warn("[AutoProtect] Phát hiện khách lạ trong phòng! Lập tức gửi lệnh rời bàn [4,'Simms',-1]");
                    G.__stranger_detected = true;
                    try {
                      if (typeof G.__ws_send_channel === "function") {
                        G.__ws_send_channel("Simms", '[4,"Simms",-1]');
                      } else if (typeof G.__ws_send === "function") {
                        G.__ws_send('[4,"Simms",-1]');
                      }
                    } catch (_) {}
                  }
                }
              } else if (p.cmd === 203) {
                G.__room_players = [];
                G.__last_room_info = null;
                G.__ws_last_room_id = null;
                try {
                  window.top.postMessage({ type: "AUTOTOOL_ROOM_INFO", room_info: null }, "*");
                } catch (_) {}
              } else if (p.cmd === 308 || p.cmd === 305) {
                if (p.ri && p.ri.rid) {
                  G.__last_room_info = p.ri;
                  G.__ws_last_room_id = p.ri.rid;
                  try {
                    window.top.postMessage({ type: "AUTOTOOL_ROOM_INFO", room_info: p.ri }, "*");
                  } catch (_) {}
                  try {
                    document.dispatchEvent(new CustomEvent("__autotool_room_event", { detail: p.ri }));
                  } catch (_) {}
                }
              }
            }
          } catch (_) {}
        }
      } catch (e) {}
    };

    const hookRecv = (ws) => {
      try {
        if (!ws || ws.__recv_hooked) return;
        ws.__recv_hooked = true;
        ws.addEventListener("message", (ev) => {
          push("recv", ev.data);
        });
      } catch (_) {}
    };

    const register = (ws) => {
      try {
        if (G.__ws_instances.indexOf(ws) === -1) {
          G.__ws_instances.push(ws);
          if (G.__ws_instances.length > 30) G.__ws_instances.shift();
        }
        hookRecv(ws);
        const url = (ws.url || "");
        if (url) G.__ws_map[url] = ws;
      } catch (e) {}
    };

    const origSend = WebSocket.prototype.send;
    WebSocket.prototype.send = function (...args) {
      register(this);
      hookRecv(this);
      push("send", args[0]);
      return origSend.apply(this, args);
    };

    const OrigWS = G.WebSocket;
    G.WebSocket = function (...args) {
      const ws = new OrigWS(...args);
      register(ws);
      return ws;
    };
    G.WebSocket.prototype = OrigWS.prototype;
    G.WebSocket.CONNECTING = OrigWS.CONNECTING;
    G.WebSocket.OPEN = OrigWS.OPEN;
    G.WebSocket.CLOSING = OrigWS.CLOSING;
    G.WebSocket.CLOSED = OrigWS.CLOSED;

    const score = (s) => {
      const u = (s.url || "");
      return (/carkgwaiz/.test(u) ? 3 : 0) + (/mynisketgw/.test(u) ? 2 : 0) + (/Simms/.test(u) ? 1 : 0);
    };

    G.__ws_send_hint = (hint, text) => {
      try {
        const arr = G.__ws_instances.slice().sort((a, b) => score(b) - score(a));
        for (const s of arr) {
          if (!s || s.readyState !== 1) continue;
          if (hint && (s.url || "").indexOf(hint) === -1) continue;
          try { s.send(text); G.__ws_capture.push({ ts: Date.now(), dir: "inject", text: String(text) }); return true; } catch (e) {}
        }
      } catch (e) {}
      return false;
    };
    G.__ws_send = (text) => G.__ws_send_hint("", text);
    G.__ws_send_channel = (channel, text) => G.__ws_send_hint(
      channel === "Simms" ? "carkgwaiz" : "mynisketgw", text
    );
  };

  const code = "(" + mainWorldCode.toString() + ")();";

  function inject() {
    const target = document.documentElement || document.head || document.body;
    if (!target) return false;
    const s = document.createElement("script");
    s.textContent = code;
    target.appendChild(s);
    try { s.remove(); } catch (e) {}
    return true;
  }

  if (!inject()) {
    const obs = new MutationObserver(function () {
      if (inject()) obs.disconnect();
    });
    obs.observe(document, { childList: true, subtree: true });
  }

  // ---- IN-PAGE FLOATING HUD (Hiển thị trực quan trên view game) ----
  function initInPageHUD() {
    if (document.getElementById("autotool-hud") || window !== window.top) return;

    const hud = document.createElement("div");
    hud.id = "autotool-hud";
    hud.style.cssText = `
      position: fixed;
      top: 10px;
      right: 10px;
      z-index: 999999999;
      background: rgba(18, 19, 24, 0.88);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(245, 176, 65, 0.4);
      border-radius: 8px;
      padding: 8px 12px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 11px;
      color: #fff;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6);
      display: flex;
      flex-direction: column;
      gap: 5px;
      min-width: 170px;
      user-select: none;
      transition: all 0.3s ease;
    `;

    hud.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:4px;">
        <span style="font-weight:bold; color:#f5b041; font-size:12px;">🎰 AUTOTOOL HUD</span>
        <button id="hud-toggle" style="background:transparent; border:none; color:#8e95a5; cursor:pointer; font-size:12px;">➖</button>
      </div>
      <div id="hud-content" style="display:flex; flex-direction:column; gap:4px;">
        <div>Bàn: <b id="hud-room" style="color:#3498db;">Sảnh</b></div>
        <div>Cược: <b id="hud-bet" style="color:#f5b041;">--</b></div>
        <div>Người: <span id="hud-players" style="color:#2ecc71;">0</span></div>
        <div id="hud-alert" style="color:#e74c3c; font-weight:bold; display:none;">⚠️ Khách lạ!</div>
        <div id="hud-status" style="font-size:11px; color:#e0e6ed; line-height:1.3; margin-top:3px; word-break:break-word; border-top:1px dashed rgba(255,255,255,0.15); padding-top:3px;">Sẵn sàng</div>
        <div style="display:flex; gap:4px; margin-top:4px;">
          <button id="hud-leave" style="flex:1; background:rgba(231,76,60,0.3); border:1px solid rgba(231,76,60,0.6); color:#ff6b6b; border-radius:4px; padding:3px 6px; cursor:pointer; font-size:10px; font-weight:bold;">Rời bàn</button>
          <button id="hud-xa" style="flex:1; background:rgba(243,156,18,0.3); border:1px solid rgba(243,156,18,0.6); color:#f5b041; border-radius:4px; padding:3px 6px; cursor:pointer; font-size:10px; font-weight:bold;">Xả bài</button>
        </div>
      </div>
    `;

    document.body.appendChild(hud);

    let collapsed = false;
    document.getElementById("hud-toggle").addEventListener("click", () => {
      collapsed = !collapsed;
      document.getElementById("hud-content").style.display = collapsed ? "none" : "flex";
      document.getElementById("hud-toggle").textContent = collapsed ? "➕" : "➖";
    });

    document.getElementById("hud-leave").addEventListener("click", () => {
      try {
        if (typeof window.__ws_send_channel === "function") window.__ws_send_channel("Simms", '[4,"Simms",-1]');
        else if (typeof window.__ws_send === "function") window.__ws_send('[4,"Simms",-1]');
      } catch (_) {}
    });

    document.getElementById("hud-xa").addEventListener("click", () => {
      try {
        chrome.runtime.sendMessage(
          {
            type: "API_CALL",
            path: "/api/autoplay/test-discard",
            method: "POST",
            body: { profile_name: "Account01", delay_ms: 500 },
          },
          () => {}
        );
      } catch (_) {
        try {
          fetch("http://127.0.0.1:8000/api/autoplay/test-discard", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ profile_name: "Account01", delay_ms: 500 }),
          }).catch(() => {});
        } catch (_) {}
      }
    });

    // Cập nhật dữ liệu thời gian thực
    setInterval(() => {
      try {
        const info = window.__last_room_info;
        const ps = window.__room_players || [];
        const alertEl = document.getElementById("hud-alert");
        const statusEl = document.getElementById("hud-status");

        if (statusEl && window.__autotool_hud_status) {
          statusEl.textContent = window.__autotool_hud_status;
        }

        if (info && info.rid) {
          document.getElementById("hud-room").textContent = info.rn || `#${info.rid}`;
          document.getElementById("hud-bet").textContent = info.b ? `$${Number(info.b).toLocaleString()}` : "--";
          document.getElementById("hud-players").textContent = `${ps.length}/${info.Mu || 4}`;
        } else {
          document.getElementById("hud-room").textContent = "Sảnh";
          document.getElementById("hud-bet").textContent = "--";
          document.getElementById("hud-players").textContent = "0";
        }

        if (window.__stranger_detected) {
          alertEl.style.display = "block";
        } else {
          alertEl.style.display = "none";
        }
      } catch (_) {}
    }, 1000);
  }

  function handleRoomInfo(ri) {
    if (!ri || !ri.rid) return;
    window.__last_room_info = ri;
    const hudRoom = document.getElementById("hud-room");
    const hudBet = document.getElementById("hud-bet");
    if (hudRoom) hudRoom.textContent = ri.rn || `#${ri.rid}`;
    if (hudBet && ri.b) hudBet.textContent = `$${Number(ri.b).toLocaleString()}`;

    try {
      chrome.runtime.sendMessage({
        type: "API_CALL",
        path: "/api/autoplay/report-room",
        method: "POST",
        body: {
          profile_name: localStorage.getItem("KEY_USER_NAME") || document.title || "",
          rid: ri.rid,
          b: ri.b,
          rn: ri.rn,
          Mu: ri.Mu
        }
      });
    } catch (_) {}
  }

  // 1. Nhận lệnh từ background.js (Backend Hub) -> Chuyển tiếp xuống Main World
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "HUB_COMMAND") {
      window.postMessage({
        type: "AUTOTOOL_EXEC_COMMAND",
        action: msg.action,
        data: msg.data || {},
      }, "*");
      sendResponse({ ok: true });
    }
    return true;
  });

  // 2. Nhận event từ Main World -> Chuyển tiếp lên background.js (Backend Hub)
  window.addEventListener("message", (ev) => {
    if (!ev.data) return;

    if (ev.data.type === "AUTOTOOL_INIT_PROFILE" && ev.data.profile_name) {
      chrome.runtime.sendMessage({
        type: "REGISTER_PROFILE",
        profile_name: ev.data.profile_name,
      });
    } else if (ev.data.type === "AUTOTOOL_ROOM_INFO") {
      handleRoomInfo(ev.data.room_info);
      chrome.runtime.sendMessage({
        type: "ROOM_UPDATE",
        profile_name: ev.data.profile_name,
        room_info: ev.data.room_info,
        players: ev.data.players,
      });
    } else if (ev.data.type === "AUTOTOOL_BRIDGE_PACKET") {
      chrome.runtime.sendMessage({
        type: "BRIDGE_PACKET",
        profile_name: ev.data.profile_name,
        action: ev.data.action,
        data: ev.data,
      });
    }
  });

  document.addEventListener("__autotool_room_event", (ev) => {
    if (ev.detail) {
      handleRoomInfo(ev.detail);
    }
  });

  if (document.readyState === "complete" || document.readyState === "interactive") {
    initInPageHUD();
  } else {
    document.addEventListener("DOMContentLoaded", initInPageHUD);
  }
})();

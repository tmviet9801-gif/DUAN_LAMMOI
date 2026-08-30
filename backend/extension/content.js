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
      } catch (e) {}
    };

    const register = (ws) => {
      try {
        if (G.__ws_instances.indexOf(ws) === -1) {
          G.__ws_instances.push(ws);
          if (G.__ws_instances.length > 30) G.__ws_instances.shift();
        }
        const url = (ws.url || "");
        if (url) G.__ws_map[url] = ws;
      } catch (e) {}
    };

    const origSend = WebSocket.prototype.send;
    WebSocket.prototype.send = function (...args) {
      register(this);
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
})();

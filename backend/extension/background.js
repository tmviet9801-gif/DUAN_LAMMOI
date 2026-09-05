// background.js — AutoTool V3 Multi-Profile Extension Bridge (Port 17832)
// Service Worker kết nối WebSocket & HTTP Proxy với Local Server Python.

const BACKEND_PORT = 17832;
const BACKEND_BASE = `http://127.0.0.1:${BACKEND_PORT}`;
const BACKEND_WS = `ws://127.0.0.1:${BACKEND_PORT}/ws/bridge`;

let hubSocket = null;
let currentProfileName = "";
let reconnectTimer = null;
let pingInterval = null;

// Khởi tạo đọc profile_name đã lưu từ trước
chrome.storage.local.get(["profile_name"], (res) => {
  if (res && res.profile_name) {
    currentProfileName = res.profile_name;
    connectToHub(currentProfileName);
  }
});

// Kết nối WebSocket tới Extension Hub
function connectToHub(profileName) {
  if (!profileName) return;
  if (hubSocket && (hubSocket.readyState === WebSocket.OPEN || hubSocket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const url = `${BACKEND_WS}?profile=${encodeURIComponent(profileName)}`;
  try {
    hubSocket = new WebSocket(url);
  } catch (_) {
    scheduleReconnect();
    return;
  }

  hubSocket.onopen = () => {
    console.log(`[AutoTool V3] Đã kết nối Hub (Port ${BACKEND_PORT}) - Profile: ${profileName}`);
    if (reconnectTimer) clearTimeout(reconnectTimer);

    if (pingInterval) clearInterval(pingInterval);
    pingInterval = setInterval(() => {
      if (hubSocket && hubSocket.readyState === WebSocket.OPEN) {
        hubSocket.send(JSON.stringify({ action: "PING", profile_name: profileName, ts: Date.now() }));
      }
    }, 15000);
  };

  hubSocket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.action === "PONG") return;

      // Chuyển tiếp lệnh điều khiển từ Hub xuống toàn bộ tab game
      chrome.tabs.query({}, (tabs) => {
        for (const tab of tabs) {
          if (tab.id) {
            chrome.tabs.sendMessage(tab.id, { type: "HUB_COMMAND", ...msg }).catch(() => {});
          }
        }
      });
    } catch (_) {}
  };

  hubSocket.onclose = () => {
    if (pingInterval) clearInterval(pingInterval);
    scheduleReconnect();
  };

  hubSocket.onerror = () => {
    try { hubSocket.close(); } catch (_) {}
  };
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    if (currentProfileName) connectToHub(currentProfileName);
  }, 3000);
}

// Giữ Service Worker luôn thức
chrome.alarms.create("keepAliveAlarm", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepAliveAlarm" && currentProfileName) {
    if (!hubSocket || hubSocket.readyState !== WebSocket.OPEN) {
      connectToHub(currentProfileName);
    }
  }
});

// Xử lý các thông điệp từ Content Scripts
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) return false;

  // 1. HTTP_PROXY: Bỏ qua hạn chế Mixed Content / CORS
  if (message.type === "HTTP_PROXY" || message.type === "API_CALL") {
    handleHttpProxy(message)
      .then((res) => sendResponse({ ok: true, ...res }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  // 2. Đăng ký Profile
  if (message.type === "REGISTER_PROFILE") {
    const pName = message.profile_name || "";
    if (pName) {
      currentProfileName = pName;
      chrome.storage.local.set({ profile_name: pName });
      connectToHub(pName);
      sendResponse({ ok: true, profile_name: pName });
    }
    return true;
  }

  // 3. Chuyển tiếp gói tin / trạng thái phòng / Số dư / Log lên Backend Hub (Port 17832)
  if (message.type === "BRIDGE_PACKET" || 
      message.type === "AUTOTOOL_ROOM_INFO" || 
      message.type === "ROOM_UPDATE" || 
      message.type === "ROOM_LEFT" || 
      message.type === "BALANCE_UPDATE" || 
      message.type === "LOG_UPDATE" ||
      message.type === "PARTNER_MATCHED") {
    if (hubSocket && hubSocket.readyState === WebSocket.OPEN) {
      hubSocket.send(JSON.stringify({
        type: message.type,
        profile_name: currentProfileName || message.profile_name,
        balance: message.balance,
        log: message.log,
        data: message.data || message.room_info || message,
        timestamp: Date.now(),
      }));
    }
    sendResponse({ ok: true });
    return true;
  }

  // 4. Kiểm tra sức khỏe kết nối
  if (message.type === "CHECK_HEALTH") {
    sendResponse({
      ok: true,
      hub_connected: hubSocket ? hubSocket.readyState === WebSocket.OPEN : false,
      profile_name: currentProfileName,
      port: BACKEND_PORT,
    });
    return true;
  }

  // 5. Kết nối lại chủ động
  if (message.type === "RECONNECT_HUB") {
    if (message.profile_name) {
      currentProfileName = message.profile_name;
      chrome.storage.local.set({ profile_name: currentProfileName });
    }
    try { if (hubSocket) hubSocket.close(); } catch (_) {}
    connectToHub(currentProfileName);
    sendResponse({ ok: true });
    return true;
  }

  // 6. Bật/Tắt tự động (ARM/DISARM)
  if (message.type === "TOGGLE_ARM") {
    chrome.tabs.query({}, (tabs) => {
      for (const tab of tabs) {
        if (tab.id) chrome.tabs.sendMessage(tab.id, { type: "SET_ARM", armed: message.armed }).catch(() => {});
      }
    });
    sendResponse({ ok: true, armed: message.armed });
    return true;
  }
});

async function handleHttpProxy({ path, method = "GET", body = null }) {
  const opts = {
    method: method || "GET",
    headers: { "Content-Type": "application/json" },
  };
  if (body && opts.method !== "GET") {
    opts.body = typeof body === "string" ? body : JSON.stringify(body);
  }

  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${BACKEND_BASE}${cleanPath}`;
  try {
    const res = await fetch(url, opts);
    let data = null;
    const cType = res.headers.get("content-type") || "";
    if (cType.includes("application/json")) {
      data = await res.json().catch(() => null);
    } else {
      data = await res.text().catch(() => null);
    }
    return { status: res.status, ok: res.ok, data };
  } catch (err) {
    throw new Error(`[HTTP_PROXY Error] ${err.message} (${url})`);
  }
}

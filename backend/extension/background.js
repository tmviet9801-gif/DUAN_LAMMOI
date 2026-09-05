// background.js — AutoTool V3 Multi-Profile Extension Bridge Hub
// Service Worker kết nối WebSocket 2 chiều với Local Server Python (Port 8000).

const BACKEND_BASE = "http://127.0.0.1:8000";
const BACKEND_WS = "ws://127.0.0.1:8000/ws/bridge";

let hubSocket = null;
let currentProfileName = "";
let reconnectTimer = null;
let pingInterval = null;

// Khởi tạo đọc profile_name đã lưu từ trước (nếu có)
chrome.storage.local.get(["profile_name"], (res) => {
  if (res && res.profile_name) {
    currentProfileName = res.profile_name;
    connectToHub(currentProfileName);
  }
});

// Kết nối WebSocket tới ExtensionHubManager trên backend
function connectToHub(profileName) {
  if (!profileName) return;
  if (hubSocket && (hubSocket.readyState === WebSocket.OPEN || hubSocket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const url = `${BACKEND_WS}?profile=${encodeURIComponent(profileName)}`;
  console.log(`[AutoTool V3 Bridge] Đang kết nối tới Hub: ${url}...`);

  try {
    hubSocket = new WebSocket(url);
  } catch (err) {
    console.warn("[AutoTool V3 Bridge] Lỗi khởi tạo WebSocket:", err);
    scheduleReconnect();
    return;
  }

  hubSocket.onopen = () => {
    console.log(`[AutoTool V3 Bridge] >>> ĐÃ KẾT NỐI HUB THÀNH CÔNG CHO PROFILE '${profileName}'! <<<`);
    if (reconnectTimer) clearTimeout(reconnectTimer);

    // Bắt đầu chu kỳ Keep-Alive ping 15s để giữ kết nối và chống Service Worker ngủ
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
      if (msg.action === "PONG") return; // Keep-alive response

      console.log("[AutoTool V3 Bridge] Nhận lệnh từ Backend Hub:", msg);

      // Chuyển tiếp lệnh điều khiển từ Backend xuống toàn bộ tab game đang mở
      chrome.tabs.query({}, (tabs) => {
        for (const tab of tabs) {
          if (tab.id) {
            chrome.tabs.sendMessage(tab.id, { type: "HUB_COMMAND", ...msg }).catch(() => {});
          }
        }
      });
    } catch (e) {
      console.warn("[AutoTool V3 Bridge] Lỗi parse tin nhắn từ Hub:", e);
    }
  };

  hubSocket.onclose = () => {
    console.log("[AutoTool V3 Bridge] Kết nối Hub bị đóng. Sẽ tự động kết nối lại...");
    if (pingInterval) clearInterval(pingInterval);
    scheduleReconnect();
  };

  hubSocket.onerror = (err) => {
    console.warn("[AutoTool V3 Bridge] Socket lỗi:", err);
    try { hubSocket.close(); } catch (_) {}
  };
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    if (currentProfileName) {
      connectToHub(currentProfileName);
    }
  }, 2500);
}

// Lắng nghe alarm để duy trì Service Worker không bao giờ bị Chrome suspend
chrome.alarms.create("keepAliveAlarm", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepAliveAlarm" && currentProfileName) {
    if (!hubSocket || hubSocket.readyState !== WebSocket.OPEN) {
      connectToHub(currentProfileName);
    }
  }
});

// Lắng nghe message từ Content Scripts (isolated world)
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // 1. Đăng ký nhận diện Profile từ trang game
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

  // 2. Chuyển tiếp gói tin từ game lên Backend Hub qua WebSocket
  if (message.type === "BRIDGE_PACKET" || message.type === "AUTOTOOL_ROOM_INFO" || message.type === "ROOM_UPDATE") {
    if (hubSocket && hubSocket.readyState === WebSocket.OPEN) {
      const payload = {
        type: message.type,
        profile_name: currentProfileName || message.profile_name,
        data: message.data || message.room_info || message,
        timestamp: Date.now(),
      };
      hubSocket.send(JSON.stringify(payload));
    }
    sendResponse({ ok: true });
    return true;
  }

  // 3. Hỗ trợ REST API Call cũ cho popup và các component khác
  if (message.type === "API_CALL") {
    handleApiCall(message)
      .then((res) => sendResponse({ ok: true, data: res }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === "CHECK_HEALTH") {
    sendResponse({
      ok: true,
      hub_connected: hubSocket ? hubSocket.readyState === WebSocket.OPEN : false,
      profile_name: currentProfileName,
    });
    return true;
  }
});

async function handleApiCall({ path, method = "GET", body = null }) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body && method !== "GET") {
    opts.body = typeof body === "string" ? body : JSON.stringify(body);
  }

  const res = await fetch(`${BACKEND_BASE}${path}`, opts);
  return await res.json();
}

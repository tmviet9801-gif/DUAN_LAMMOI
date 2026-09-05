// content.js — AutoTool V3 Isolated Bridge & Floating Status Pill (Port 17832)
// Giao diện nút bấm nổi góc trái dưới và cầu nối 2 chiều giữa Game Canvas & Extension Hub.

(function () {
  let isToolArmed = true;
  let isHubConnected = false;
  let activeProfileName = "";
  let lastRoomInfo = null;

  let matchedPartner = "";
  let pendingJoinRid = null;
  let customStatusMessage = "";

  // ---- 1. CƠ CHẾ HTTP_PROXY QUA BACKGROUND ----
  function requestControl(path, body = null, method = "GET") {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(
          { type: "HTTP_PROXY", path, method, body },
          (response) => {
            if (chrome.runtime.lastError) {
              resolve({ ok: false, error: chrome.runtime.lastError.message });
            } else {
              resolve(response || { ok: false, error: "Empty response" });
            }
          }
        );
      } catch (err) {
        resolve({ ok: false, error: err.message });
      }
    });
  }

  // ---- 2. HIỂN THỊ TOAST THÔNG BÁO VIEW WEB ----
  function showToast(text, type = "info") {
    if (window !== window.top) return;
    let toast = document.getElementById("autotool-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "autotool-toast";
      (document.body || document.documentElement).appendChild(toast);
    }

    toast.className = `autotool-toast-visible ${type}`;
    toast.innerHTML = text;

    if (toast.__timer) clearTimeout(toast.__timer);
    toast.__timer = setTimeout(() => {
      if (toast) toast.className = "";
    }, 4500);
  }

  // ---- 3. GIAO DIỆN NÚT BẤM NỔI (#autotool-connect-btn) ----
  function ensureStyles() {
    if (document.getElementById("autotool-pill-style")) return;
    const style = document.createElement("style");
    style.id = "autotool-pill-style";
    style.textContent = `
      #autotool-connect-btn {
        position: fixed !important;
        left: 12px !important;
        bottom: 12px !important;
        z-index: 2147483647 !important;
        display: inline-flex !important;
        align-items: center !important;
        gap: 8px !important;
        padding: 7px 14px !important;
        border-radius: 9999px !important;
        border: 1.5px solid #f0c040 !important;
        background: #0b1220 !important;
        color: #f0c040 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 12px !important;
        font-weight: 700 !important;
        line-height: 1 !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.6) !important;
        cursor: pointer !important;
        user-select: none !important;
        transition: all 0.2s ease !important;
      }
      #autotool-connect-btn:hover {
        transform: translateY(-2px) scale(1.02) !important;
      }
      #autotool-connect-btn:active {
        transform: translateY(0px) scale(0.98) !important;
      }
      #autotool-connect-btn .at-dot {
        width: 8px !important;
        height: 8px !important;
        border-radius: 50% !important;
        background: #f0c040 !important;
        display: inline-block !important;
      }
      #autotool-connect-btn.on {
        background: #14532d !important;
        border-color: #22c55e !important;
        color: #86efac !important;
        box-shadow: 0 0 14px rgba(34, 197, 94, 0.4) !important;
      }
      #autotool-connect-btn.on .at-dot {
        background: #4ade80 !important;
        box-shadow: 0 0 8px #4ade80 !important;
      }
      #autotool-connect-btn.wait {
        background: #451a03 !important;
        border-color: #f59e0b !important;
        color: #fde68a !important;
        box-shadow: 0 0 14px rgba(245, 158, 11, 0.4) !important;
      }
      #autotool-connect-btn.wait .at-dot {
        background: #fbbf24 !important;
      }
      #autotool-connect-btn.err {
        background: #450a0a !important;
        border-color: #ef4444 !important;
        color: #fca5a5 !important;
      }
      #autotool-connect-btn.err .at-dot {
        background: #f87171 !important;
      }
      #autotool-connect-btn.disarmed {
        opacity: 0.8 !important;
        border-color: #94a3b8 !important;
        color: #cbd5e1 !important;
      }

      /* TOAST BANNER TRÊN MÀN HÌNH */
      #autotool-toast {
        position: fixed !important;
        top: -60px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 2147483647 !important;
        padding: 9px 20px !important;
        border-radius: 8px !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 13px !important;
        font-weight: 700 !important;
        box-shadow: 0 6px 22px rgba(0, 0, 0, 0.75) !important;
        pointer-events: none !important;
        opacity: 0 !important;
        transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
      }
      #autotool-toast.autotool-toast-visible {
        top: 20px !important;
        opacity: 1 !important;
      }
      #autotool-toast.warn {
        background: #451a03 !important;
        border: 1.5px solid #f59e0b !important;
        color: #fde68a !important;
      }
      #autotool-toast.success {
        background: #14532d !important;
        border: 1.5px solid #22c55e !important;
        color: #86efac !important;
      }
      #autotool-toast.info {
        background: #0b1220 !important;
        border: 1.5px solid #38bdf8 !important;
        color: #bae6fd !important;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function initConnectButton() {
    if (document.getElementById("autotool-connect-btn") || window !== window.top) return;
    ensureStyles();

    const btn = document.createElement("button");
    btn.id = "autotool-connect-btn";
    btn.className = "wait";
    btn.innerHTML = `<span class="at-dot"></span><span id="autotool-btn-text">⚡ TOOL V3: ĐANG KẾT NỐI (17832)...</span>`;

    btn.addEventListener("click", () => {
      if (!isHubConnected) {
        btn.className = "wait";
        const txt = document.getElementById("autotool-btn-text");
        if (txt) txt.textContent = "⏳ ĐANG KẾT NỐI LẠI (17832)...";

        const pName = activeProfileName || localStorage.getItem("AUTOTOOL_PROFILE_NAME") || localStorage.getItem("KEY_USER_NAME") || document.title || "";
        chrome.runtime.sendMessage({ type: "RECONNECT_HUB", profile_name: pName }, () => {
          updatePill();
        });
      } else {
        isToolArmed = !isToolArmed;
        chrome.runtime.sendMessage({ type: "TOGGLE_ARM", armed: isToolArmed }, () => {});
        window.postMessage({ type: "AUTOTOOL_SET_ARM", armed: isToolArmed }, "*");
        updatePill();
      }
    });

    (document.body || document.documentElement).appendChild(btn);
    updatePill();
  }

  function updatePill() {
    const btn = document.getElementById("autotool-connect-btn");
    const txt = document.getElementById("autotool-btn-text");
    if (!btn || !txt) return;

    chrome.runtime.sendMessage({ type: "CHECK_HEALTH" }, (res) => {
      if (chrome.runtime.lastError || !res || !res.ok) {
        isHubConnected = false;
        btn.className = "err";
        txt.textContent = "🔴 MẤT KẾT NỐI HUB (Bấm thử lại)";
        return;
      }

      isHubConnected = res.hub_connected;
      if (res.profile_name) activeProfileName = res.profile_name;

      const pLabel = activeProfileName || "Tool V3";

      // Ưu tiên hiển thị thông báo tức thời nếu có lệnh đang xử lý
      if (customStatusMessage) {
        txt.textContent = customStatusMessage;
        return;
      }

      const roomStr = lastRoomInfo && lastRoomInfo.rid ? ` [Bàn #${lastRoomInfo.rid}]` : "";

      if (!isHubConnected) {
        btn.className = "wait";
        txt.textContent = `⏳ ĐANG KẾT NỐI HUB (${pLabel})...`;
      } else if (!isToolArmed) {
        btn.className = "on disarmed";
        txt.textContent = `⏸️ TOOL V3: TẠM DỪNG (${pLabel})${roomStr}`;
      } else if (lastRoomInfo && lastRoomInfo.rid) {
        btn.className = "on";
        if (pendingJoinRid && Number(lastRoomInfo.rid) === Number(pendingJoinRid)) {
          txt.textContent = `🟢 ĐÃ VÀO BÀN #${lastRoomInfo.rid} CÙNG ${matchedPartner || 'A'}`;
        } else {
          txt.textContent = `🟢 BÀN #${lastRoomInfo.rid} (${pLabel})`;
        }
      } else {
        btn.className = "on";
        txt.textContent = `🟢 TOOL V3: ĐÃ KẾT NỐI (${pLabel})`;
      }
    });
  }

  // ---- 4. CẦU NỐI THÔNG ĐIỆP (2-WAY BRIDGE TỨC THỜI <2ms) ----
  // Nhận lệnh từ Background (Hub gửi xuống) -> Bắn vào Main World
  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg) return true;

    if (msg.type === "HUB_COMMAND") {
      const action = msg.action;
      const data = msg.data || {};

      // 1. NHẬN ID BÀN TỪ PROFILE A -> B NHẢY VÀO NGAY LẬP TỨC
      if (action === "JOIN_ROOM" && data.rid) {
        const rid = data.rid;
        const source = data.source_profile || "A";
        matchedPartner = source;
        pendingJoinRid = rid;

        const btn = document.getElementById("autotool-connect-btn");
        const txt = document.getElementById("autotool-btn-text");
        if (btn) btn.className = "wait";
        customStatusMessage = `⚡ ĐÃ NHẬN ID PHÒNG ${rid} TỪ ${source}! ĐANG VÀO...`;
        if (txt) txt.textContent = customStatusMessage;

        // Bắn banner thông báo nổi bật trên view web
        showToast(`⚡ <b>ĐÃ NHẬN ID PHÒNG ${rid} TỪ ${source}!</b> Đang tự động vào bàn...`, "warn");

        // Gửi lệnh xuống Main World để game WS gửi packet join ngay tức thì (<2ms)
        window.postMessage({
          type: "AUTOTOOL_EXEC_COMMAND",
          action: "JOIN_ROOM",
          data: data,
        }, "*");

        setTimeout(() => {
          customStatusMessage = "";
          updatePill();
        }, 5000);
      }

      // 2. PROFILE A NHẬN XÁC NHẬN ĐÃ CHIA SẺ ID PHÒNG CHO B
      else if (action === "ROOM_SHARED_CONFIRM") {
        const rid = data.rid;
        const btn = document.getElementById("autotool-connect-btn");
        const txt = document.getElementById("autotool-btn-text");
        if (btn) btn.className = "on";
        customStatusMessage = `🟢 BÀN #${rid}: ĐÃ GỬI ID CHO B!`;
        if (txt) txt.textContent = customStatusMessage;

        showToast(`🟢 ĐÃ GỬI ID PHÒNG <b>#${rid}</b> CHO B (Đang đợi B vào bàn)...`, "info");

        setTimeout(() => {
          customStatusMessage = "";
          updatePill();
        }, 4000);
      } else {
        window.postMessage({
          type: "AUTOTOOL_EXEC_COMMAND",
          action: action,
          data: data,
        }, "*");
      }
    } else if (msg.type === "SET_ARM") {
      isToolArmed = !!msg.armed;
      window.postMessage({ type: "AUTOTOOL_SET_ARM", armed: isToolArmed }, "*");
      updatePill();
    }
    return true;
  });

  // Nhận event từ Main World -> Chuyển tiếp lên Background Hub
  window.addEventListener("message", (ev) => {
    if (!ev.data) return;

    if (ev.data.type === "AUTOTOOL_INIT_PROFILE" && ev.data.profile_name) {
      activeProfileName = ev.data.profile_name;
      chrome.runtime.sendMessage({
        type: "REGISTER_PROFILE",
        profile_name: ev.data.profile_name,
      });
      updatePill();
    } else if (ev.data.type === "AUTOTOOL_ROOM_INFO") {
      const prevRid = lastRoomInfo ? lastRoomInfo.rid : null;
      lastRoomInfo = ev.data.room_info;

      // Nếu vừa mới vào bàn thành công
      if (lastRoomInfo && lastRoomInfo.rid && lastRoomInfo.rid !== prevRid) {
        if (pendingJoinRid && Number(lastRoomInfo.rid) === Number(pendingJoinRid)) {
          showToast(`🟢 <b>ĐÃ VÀO BÀN #${lastRoomInfo.rid} CÙNG ${matchedPartner || 'A'} THÀNH CÔNG!</b>`, "success");
        }
      }

      updatePill();

      if (lastRoomInfo && lastRoomInfo.rid) {
        requestControl("/api/autoplay/report-room", {
          profile_name: activeProfileName || localStorage.getItem("KEY_USER_NAME") || document.title || "",
          rid: lastRoomInfo.rid,
          b: lastRoomInfo.b,
          rn: lastRoomInfo.rn,
          Mu: lastRoomInfo.Mu,
        }, "POST").catch(() => {});
      }

      chrome.runtime.sendMessage({
        type: "ROOM_UPDATE",
        profile_name: activeProfileName,
        room_info: ev.data.room_info,
        players: ev.data.players,
      });
    } else if (ev.data.type === "AUTOTOOL_BRIDGE_PACKET") {
      chrome.runtime.sendMessage({
        type: "BRIDGE_PACKET",
        profile_name: activeProfileName,
        action: ev.data.action,
        data: ev.data,
      });
    }
  });

  // Khởi động giao diện & chu kỳ cập nhật
  if (document.readyState === "complete" || document.readyState === "interactive") {
    initConnectButton();
  } else {
    document.addEventListener("DOMContentLoaded", initConnectButton);
  }
  setInterval(updatePill, 2000);
})();


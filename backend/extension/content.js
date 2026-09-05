// content.js — AutoTool V3 Isolated Bridge & Minimalist Game Overlay (Port 17832)
// Cầu nối siêu tốc (<2ms) điều phối giữa Game Canvas, Extension Hub & Desktop App.

(function () {
  let isToolArmed = true;
  let isHubConnected = false;
  let activeProfileName = "";
  let lastRoomInfo = null;

  let matchedPartner = "";
  let pendingJoinRid = null;

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

  // ---- 2. GIAO DIỆN VIEW GAME: TOP BANNER & TOAST ----
  function ensureStyles() {
    if (document.getElementById("autotool-overlay-styles")) return;
    const style = document.createElement("style");
    style.id = "autotool-overlay-styles";
    style.textContent = `
      /* 1. TOP VIEW BANNER: HIỂN THỊ RÕ BÀN VÀ TRẠNG THÁI TRÊN MÀN HÌNH GAME */
      #autotool-view-banner {
        position: fixed !important;
        top: 14px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 2147483647 !important;
        display: inline-flex !important;
        align-items: center !important;
        gap: 10px !important;
        padding: 8px 22px !important;
        border-radius: 9999px !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 13px !important;
        font-weight: 700 !important;
        letter-spacing: 0.3px !important;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.75) !important;
        pointer-events: none !important;
        user-select: none !important;
        backdrop-filter: blur(8px) !important;
        transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
        opacity: 0.95 !important;
      }
      #autotool-view-banner.active {
        background: rgba(11, 44, 25, 0.92) !important;
        border: 1.5px solid #22c55e !important;
        color: #86efac !important;
        text-shadow: 0 1px 4px rgba(0,0,0,0.8) !important;
      }
      #autotool-view-banner.joining {
        background: rgba(69, 26, 3, 0.92) !important;
        border: 1.5px solid #f59e0b !important;
        color: #fde68a !important;
        animation: autotool-pulse 1.2s infinite ease-in-out !important;
      }
      #autotool-view-banner.lobby {
        background: rgba(15, 23, 42, 0.9) !important;
        border: 1.5px solid #64748b !important;
        color: #cbd5e1 !important;
      }
      @keyframes autotool-pulse {
        0%, 100% { transform: translateX(-50%) scale(1); }
        50% { transform: translateX(-50%) scale(1.03); box-shadow: 0 0 20px rgba(245, 158, 11, 0.6) !important; }
      }

      /* 2. NÚT NỔI TỐI GIẢN GÓC TRÁI DƯỚI (#autotool-connect-btn) */
      #autotool-connect-btn {
        position: fixed !important;
        left: 10px !important;
        bottom: 10px !important;
        z-index: 2147483647 !important;
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
        padding: 5px 12px !important;
        border-radius: 9999px !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        background: rgba(15, 23, 42, 0.85) !important;
        color: #94a3b8 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5) !important;
        cursor: pointer !important;
        user-select: none !important;
        backdrop-filter: blur(4px) !important;
        transition: all 0.2s ease !important;
      }
      #autotool-connect-btn:hover {
        background: rgba(30, 41, 59, 0.95) !important;
        color: #f1f5f9 !important;
      }
      #autotool-connect-btn .at-dot {
        width: 7px !important;
        height: 7px !important;
        border-radius: 50% !important;
        background: #f59e0b !important;
        display: inline-block !important;
      }
      #autotool-connect-btn.on .at-dot {
        background: #22c55e !important;
        box-shadow: 0 0 6px #22c55e !important;
      }
      #autotool-connect-btn.err .at-dot {
        background: #ef4444 !important;
      }

      /* 3. TOAST THÔNG BÁO TẠM THỜI */
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
        top: 60px !important;
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

      /* 4. IN-GAME VISUAL CARDS BAR */
      #autotool-cards-panel {
        position: fixed !important;
        top: 56px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 2147483646 !important;
        display: none;
        align-items: center !important;
        gap: 4px !important;
        padding: 5px 12px !important;
        border-radius: 8px !important;
        background: rgba(15, 23, 42, 0.95) !important;
        border: 1px solid rgba(56, 189, 248, 0.4) !important;
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.7) !important;
        backdrop-filter: blur(6px) !important;
        pointer-events: none !important;
        user-select: none !important;
        transition: all 0.2s ease !important;
      }
      #autotool-cards-panel.visible {
        display: inline-flex !important;
      }
      .autotool-card-chip {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        min-width: 26px !important;
        height: 30px !important;
        padding: 0 5px !important;
        border-radius: 4px !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace !important;
        font-size: 13px !important;
        font-weight: 800 !important;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.4) !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
      }
      .autotool-card-chip.black {
        background: #1e293b !important;
        color: #f8fafc !important;
        border-color: #475569 !important;
      }
      .autotool-card-chip.red {
        background: #450a0a !important;
        color: #f87171 !important;
        border-color: #ef4444 !important;
      }

      /* 5. IN-GAME PARTNER CARDS BAR (HIỂN THỊ BÀI ĐỒNG ĐỘI) */
      #autotool-partner-cards-panel {
        position: fixed !important;
        top: 96px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 2147483645 !important;
        display: none;
        align-items: center !important;
        gap: 4px !important;
        padding: 4px 10px !important;
        border-radius: 8px !important;
        background: rgba(30, 27, 75, 0.95) !important;
        border: 1px solid rgba(168, 85, 247, 0.5) !important;
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.7) !important;
        backdrop-filter: blur(6px) !important;
        pointer-events: none !important;
        user-select: none !important;
        transition: all 0.2s ease !important;
      }
      #autotool-partner-cards-panel.visible {
        display: inline-flex !important;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function parseCardInfo(c) {
    if (typeof c !== "number" || c < 0 || c > 51) return null;
    const rawRank = Math.floor(c / 4);
    const suitIndex = c % 4;
    const rankNames = {
      2: "3", 3: "4", 4: "5", 5: "6", 6: "7", 7: "8", 8: "9", 9: "10",
      10: "J", 11: "Q", 12: "K", 0: "A", 1: "2"
    };
    const suitIcons = ["♠", "♣", "♦", "♥"];
    const isRed = (suitIndex === 2 || suitIndex === 3);
    const rank = rankNames[rawRank] || "?";
    const icon = suitIcons[suitIndex] || "";
    return { id: c, rank, icon, isRed, text: rank + icon };
  }

  function updateCardsPanel(cards) {
    if (window !== window.top) return;
    ensureStyles();
    let panel = document.getElementById("autotool-cards-panel");
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "autotool-cards-panel";
      (document.body || document.documentElement).appendChild(panel);
    }
    if (!cards || !cards.length) {
      panel.className = "";
      panel.innerHTML = "";
      return;
    }
    panel.className = "visible";
    const sorted = cards.slice().sort((a, b) => {
      function getVal(x) {
        const r = Math.floor(x / 4);
        if (r >= 2) return r + 1;
        if (r === 0) return 14;
        if (r === 1) return 15;
        return 0;
      }
      const va = getVal(a), vb = getVal(b);
      if (va !== vb) return va - vb;
      return (a % 4) - (b % 4);
    });

    const chips = sorted.map((c) => {
      const info = parseCardInfo(c);
      if (!info) return "";
      const cls = info.isRed ? "autotool-card-chip red" : "autotool-card-chip black";
      return `<span class="${cls}">${info.text}</span>`;
    }).join("");

    panel.innerHTML = `<span style="font-size:11px;font-weight:700;color:#38bdf8;margin-right:4px;">🃏 Bạn (${cards.length}):</span>` + chips;
  }

  function updatePartnerCardsPanel(cards, partnerName = "Đồng đội") {
    if (window !== window.top) return;
    ensureStyles();
    let panel = document.getElementById("autotool-partner-cards-panel");
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "autotool-partner-cards-panel";
      (document.body || document.documentElement).appendChild(panel);
    }
    if (!cards || !cards.length) {
      panel.className = "";
      panel.innerHTML = "";
      return;
    }
    panel.className = "visible";
    const sorted = cards.slice().sort((a, b) => {
      function getVal(x) {
        const r = Math.floor(x / 4);
        if (r >= 2) return r + 1;
        if (r === 0) return 14;
        if (r === 1) return 15;
        return 0;
      }
      const va = getVal(a), vb = getVal(b);
      if (va !== vb) return va - vb;
      return (a % 4) - (b % 4);
    });

    const chips = sorted.map((c) => {
      const info = parseCardInfo(c);
      if (!info) return "";
      const cls = info.isRed ? "autotool-card-chip red" : "autotool-card-chip black";
      return `<span class="${cls}">${info.text}</span>`;
    }).join("");

    panel.innerHTML = `<span style="font-size:11px;font-weight:700;color:#c084fc;margin-right:4px;">👥 ${partnerName} (${cards.length}):</span>` + chips;
  }

  function updateViewBanner(htmlText, type = "lobby") {
    if (window !== window.top) return;
    ensureStyles();
    let b = document.getElementById("autotool-view-banner");
    if (!b) {
      b = document.createElement("div");
      b.id = "autotool-view-banner";
      (document.body || document.documentElement).appendChild(b);
    }
    b.className = type;
    b.innerHTML = htmlText;
  }

  function showToast(text, type = "info") {
    if (window !== window.top) return;
    ensureStyles();
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
    }, 4000);
  }

  function isExtensionValid() {
    try {
      return !!(window.chrome && chrome.runtime && chrome.runtime.id);
    } catch (_) {
      return false;
    }
  }

  function safeSendMessage(msg, callback) {
    if (!isExtensionValid()) return;
    try {
      chrome.runtime.sendMessage(msg, (res) => {
        if (chrome.runtime.lastError) {
          // Context bị reload
          return;
        }
        if (typeof callback === "function") callback(res);
      });
    } catch (_) {}
  }

  function initOverlay() {
    if (document.getElementById("autotool-connect-btn") || window !== window.top) return;
    ensureStyles();

    // Nút trạng thái tối giản
    const btn = document.createElement("button");
    btn.id = "autotool-connect-btn";
    btn.innerHTML = `<span class="at-dot"></span><span id="autotool-btn-text">V3: Đang kết nối...</span>`;
    btn.addEventListener("click", () => {
      const pName = activeProfileName || localStorage.getItem("AUTOTOOL_PROFILE_NAME") || localStorage.getItem("KEY_USER_NAME") || document.title || "";
      safeSendMessage({ type: "RECONNECT_HUB", profile_name: pName }, () => {
        updatePill();
      });
    });
    (document.body || document.documentElement).appendChild(btn);

    // Nút Bật/Tắt Săn Bàn & Tự động Out khi gặp khách lạ
    const huntBtn = document.createElement("button");
    huntBtn.id = "autotool-hunt-btn";
    huntBtn.style.cssText = "position:fixed!important;left:150px!important;bottom:10px!important;z-index:2147483647!important;display:inline-flex!important;align-items:center!important;gap:5px!important;padding:5px 12px!important;border-radius:9999px!important;border:1px solid rgba(245,158,11,0.5)!important;background:rgba(69,26,3,0.88)!important;color:#fde68a!important;font-family:sans-serif!important;font-size:11px!important;font-weight:700!important;cursor:pointer!important;backdrop-filter:blur(4px)!important;box-shadow:0 4px 12px rgba(0,0,0,0.5)!important;";
    huntBtn.innerHTML = "🎯 Săn Bàn: BẬT";
    let isHuntOn = true;
    huntBtn.addEventListener("click", () => {
      isHuntOn = !isHuntOn;
      huntBtn.innerHTML = isHuntOn ? "🎯 Săn Bàn: BẬT" : "⚪ Săn Bàn: TẮT";
      huntBtn.style.background = isHuntOn ? "rgba(69,26,3,0.88)" : "rgba(30,41,59,0.85)";
      huntBtn.style.color = isHuntOn ? "#fde68a" : "#94a3b8";
      huntBtn.style.borderColor = isHuntOn ? "rgba(245,158,11,0.5)" : "rgba(255,255,255,0.2)";
      window.postMessage({ type: "AUTOTOOL_SET_HUNT", auto_hunt: isHuntOn }, "*");
      showToast(`🎯 Chế độ Săn Bàn & Auto Out: <b>${isHuntOn ? 'BẬT' : 'TẮT'}</b>`, isHuntOn ? "warn" : "info");
    });
    (document.body || document.documentElement).appendChild(huntBtn);

    // Banner mặc định khi mở tab
    const pLabel = activeProfileName || "Tool V3";
    updateViewBanner(`🏠 <b>${pLabel}</b>: Đang ở sảnh (Chờ tìm bàn)`, "lobby");

    updatePill();
  }

  function updatePill() {
    const btn = document.getElementById("autotool-connect-btn");
    const txt = document.getElementById("autotool-btn-text");
    if (!btn || !txt) return;

    if (!isExtensionValid()) {
      btn.className = "err";
      txt.textContent = "🔄 Cần F5 trang game";
      return;
    }

    safeSendMessage({ type: "CHECK_HEALTH" }, (res) => {
      if (!res || !res.ok) {
        isHubConnected = false;
        btn.className = "err";
        txt.textContent = "🔴 Mất kết nối Hub";
        return;
      }

      isHubConnected = res.hub_connected;
      if (res.profile_name) activeProfileName = res.profile_name;
      const pLabel = activeProfileName || "Tool V3";

      if (!isHubConnected) {
        btn.className = "";
        txt.textContent = `⏳ Đang kết nối (${pLabel})`;
      } else {
        btn.className = "on";
        if (lastRoomInfo && lastRoomInfo.rid) {
          txt.textContent = `🟢 ${lastRoomInfo.rn || 'Bàn ' + lastRoomInfo.rid} (${pLabel})`;
        } else {
          txt.textContent = `🟢 Online (${pLabel})`;
        }
      }
    });
  }

  // ---- 3. CẦU NỐI THÔNG ĐIỆP 2 CHIỀU (TỨC THỜI <2ms) ----
  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg) return true;

    if (msg.type === "HUB_COMMAND") {
      const action = msg.action;
      const data = msg.data || {};

      // 1. NHẬN ID BÀN TỪ PROFILE A -> B HIỂN THỊ VÀ VÀO PHÒNG NGAY LẬP TỨC
      if (action === "JOIN_ROOM") {
        const rid = data.rid || "Chống Vây";
        const source = data.source_profile || "A";
        matchedPartner = source;
        pendingJoinRid = rid;

        // HIỂN THỊ TRỰC TIẾP TRÊN MÀN HÌNH VIEW CỦA B
        updateViewBanner(`⚡ <b>ĐÃ NHẬN BÀN ${rid} TỪ ${source}!</b> ĐANG VÀO BÀN...`, "joining");
        showToast(`⚡ <b>ĐÃ NHẬN BÀN ${rid} TỪ ${source}!</b> Đang tự động vào bàn...`, "warn");

        // Ghi log lên App Desktop
        requestControl("/api/accounts/update-log", {
          profile_name: activeProfileName,
          log: `Nhận bàn ${rid} từ ${source} -> Vào bàn`,
        }, "POST").catch(() => {});

        // Gửi lệnh xuống Main World để game WS gửi packet join tức thì
        window.postMessage({
          type: "AUTOTOOL_EXEC_COMMAND",
          action: "JOIN_ROOM",
          data: data,
        }, "*");
      }

      // 2. PROFILE A NHẬN XÁC NHẬN ĐÃ CHIA SẺ ID PHÒNG CHO B
      else if (action === "ROOM_SHARED_CONFIRM") {
        const rid = data.rid || "Chống Vây";
        updateViewBanner(`🟢 <b>BÀN ${rid} - ${activeProfileName}</b>: Đã gửi ID cho Account 2!`, "active");
        showToast(`🟢 ĐÃ GỬI BÀN <b>${rid}</b> CHO ACCOUNT 2!`, "info");

        // Ghi log lên App Desktop
        requestControl("/api/accounts/update-log", {
          profile_name: activeProfileName,
          log: `Bàn ${rid} (Đã gửi ID cho Acc 2)`,
        }, "POST").catch(() => {});
      } else if (action === "CONFIRM_MATCH") {
        const partner = data.source || data.partner || "Đồng đội";
        updateViewBanner(`🟢 <b>ĐÃ VÀO CÙNG NHAU THÀNH CÔNG! (${activeProfileName} & ${partner})</b> - ĐANG KHÓA BÀN!`, "active");
        showToast(`🟢 <b>ĐỒNG ĐỘI ĐÃ VÀO BÀN!</b><br>Đã khóa bàn thành công!`, "success");

        requestControl("/api/accounts/update-log", {
          profile_name: activeProfileName,
          log: `🟢 Đã khớp bàn cùng ${partner}`,
        }, "POST").catch(() => {});

        window.postMessage({
          type: "AUTOTOOL_CONFIRM_MATCH",
          partner: partner,
        }, "*");
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

  // Nhận event từ Main World -> Chuyển tiếp lên Background Hub & Backend Server
  window.addEventListener("message", (ev) => {
    if (!ev.data) return;

    // Khởi tạo Profile
    if (ev.data.type === "AUTOTOOL_INIT_PROFILE" && ev.data.profile_name) {
      activeProfileName = ev.data.profile_name;
      safeSendMessage({
        type: "REGISTER_PROFILE",
        profile_name: ev.data.profile_name,
      });
      // Xóa sạch bài rác lưu cũ nếu đang ở sảnh
      requestControl("/api/accounts/update-cards", {
        profile_name: activeProfileName,
        cards: [],
      }, "POST").catch(() => {});
      requestControl("/api/accounts/update-log", {
        profile_name: activeProfileName,
        log: "Đang ở sảnh (Chờ tìm bàn)",
      }, "POST").catch(() => {});
      updatePill();
      updateViewBanner(`🏠 <b>${activeProfileName}</b>: Đang ở sảnh (Chờ tìm bàn)`, "lobby");
    }

    // ĐỒNG BỘ SỐ DƯ (BALANCE) REALTIME VỀ APP
    else if (ev.data.type === "AUTOTOOL_BALANCE_UPDATE") {
      const bal = ev.data.balance;
      if (bal !== undefined && bal !== null) {
        safeSendMessage({
          type: "BALANCE_UPDATE",
          profile_name: activeProfileName || ev.data.profile_name,
          balance: bal,
        });
        requestControl("/api/accounts/update-balance", {
          profile_name: activeProfileName || ev.data.profile_name,
          balance: bal,
        }, "POST").catch(() => {});
      }
    }

    // THÔNG TIN PHÒNG (VÀO BÀN THỰC SỰ)
    else if (ev.data.type === "AUTOTOOL_ROOM_INFO") {
      const prevRid = lastRoomInfo ? lastRoomInfo.rid : null;
      lastRoomInfo = ev.data.room_info;

      if (lastRoomInfo) {
        const rid = lastRoomInfo.rid || "Chống Vây";
        const betStr = lastRoomInfo.b ? ` ($${lastRoomInfo.b})` : "";
        const pLabel = activeProfileName || "Tool V3";

        // Bóc tách thông tin khách lạ
        let guestStr = "";
        let guestNames = "";
        if (ev.data.guests && ev.data.guests.length > 0) {
          guestNames = ev.data.guests.map((g) => g.dn || g.u || "Khách").join(", ");
          guestStr = ` | ⚠️ Khách: ${guestNames}`;
        }

        // HIỂN THỊ RÕ RÀNG TRÊN VIEW GAME CỦA TÀI KHOẢN
        if (pendingJoinRid && String(rid) === String(pendingJoinRid)) {
          updateViewBanner(`🟢 <b>ĐÃ VÀO BÀN ${rid} CÙNG ${matchedPartner || 'A'} THÀNH CÔNG!</b>${guestStr}`, "active");
          showToast(`🟢 <b>ĐÃ VÀO BÀN ${rid} CÙNG ${matchedPartner || 'A'} THÀNH CÔNG!</b>`, "success");
        } else {
          updateViewBanner(`📌 <b>BÀN ${rid}</b> - ${pLabel}${betStr}${guestStr}`, "active");
        }

        // Cập nhật log về App Desktop
        const logMsg = guestNames 
          ? `Bàn ${rid}${betStr} (Thấy khách lạ: ${guestNames})` 
          : `Bàn ${rid}${betStr} (Chờ bắt đầu)`;

        requestControl("/api/accounts/update-log", {
          profile_name: activeProfileName,
          log: logMsg,
        }, "POST").catch(() => {});

        // Đảm bảo không hiển thị bài cũ khi mới vào bàn chưa chia bài
        if (!ev.data.cards || !ev.data.cards.length) {
          requestControl("/api/accounts/update-cards", {
            profile_name: activeProfileName,
            cards: [],
          }, "POST").catch(() => {});
        }

        requestControl("/api/autoplay/report-room", {
          profile_name: activeProfileName || localStorage.getItem("KEY_USER_NAME") || document.title || "",
          rid: lastRoomInfo.rid,
          b: lastRoomInfo.b,
          rn: lastRoomInfo.rn,
          Mu: lastRoomInfo.Mu,
        }, "POST").catch(() => {});
      }

      updatePill();

      safeSendMessage({
        type: "ROOM_UPDATE",
        profile_name: activeProfileName,
        room_info: ev.data.room_info,
        players: ev.data.players,
        guests: ev.data.guests,
      });
    }

    // RỜI PHÒNG / VỀ SẢNH
    else if (ev.data.type === "AUTOTOOL_ROOM_LEFT") {
      lastRoomInfo = null;
      pendingJoinRid = null;
      matchedPartner = "";
      updateCardsPanel([]);
      updatePartnerCardsPanel([]);

      const pLabel = activeProfileName || "Tool V3";
      updateViewBanner(`🏠 <b>${pLabel}</b>: Đang ở sảnh (Chờ tìm bàn)`, "lobby");

      // XÓA BÀI & CẬP NHẬT LOG KHI VỀ SẢNH
      requestControl("/api/accounts/update-log", {
        profile_name: activeProfileName,
        log: "Đang ở sảnh (Chưa vào bàn)",
      }, "POST").catch(() => {});

      requestControl("/api/accounts/update-cards", {
        profile_name: activeProfileName,
        cards: [],
      }, "POST").catch(() => {});

      safeSendMessage({
        type: "ROOM_LEFT",
        profile_name: activeProfileName,
      });
      safeSendMessage({
        type: "CARDS_UPDATED",
        profile_name: activeProfileName,
        cards: [],
      });
      updatePill();
    }

    // KHỚP BÀN THÀNH CÔNG (CẢ 2 NICK Ở CÙNG NHAU) -> TỰ ĐỘNG SẴN SÀNG & BẮT ĐẦU VÁN
    else if (ev.data.type === "AUTOTOOL_MATCH_SUCCESS" || ev.data.type === "AUTOTOOL_MATCH_LOCKED") {
      const partner = ev.data.partner_name || "Đồng đội";
      const pLabel = activeProfileName || "Tool V3";
      updateViewBanner(`🟢 <b>ĐÃ KHỚP BÀN (${pLabel} & ${partner})</b> - ĐÃ KHÓA BÀN & BẮT ĐẦU!`, "active");
      showToast(`🟢 <b>KHỚP BÀN THÀNH CÔNG!</b><br>${pLabel} & ${partner}<br>⚡ Đã khóa bàn & tự động Sẵn Sàng!`, "success");

      // Báo ngay lên Extension Hub để cứu hẹn giờ của đồng đội và dừng mọi lệnh Join
      safeSendMessage({
        type: "PARTNER_MATCHED",
        profile_name: activeProfileName,
        partner_name: partner,
      });

      requestControl("/api/accounts/update-log", {
        profile_name: activeProfileName,
        log: `🟢 Đã khớp bàn cùng ${partner} (Đã khóa bàn & bắt đầu)`,
      }, "POST").catch(() => {});
    }

    // TỰ ĐỘNG THOÁT BÀN KHI THẤY KHÁCH LẠ HOẶC TIMEOUT
    else if (ev.data.type === "AUTOTOOL_AUTO_LEAVING") {
      const reason = ev.data.reason || "Lệch bàn";
      const pLabel = activeProfileName || "Tool V3";
      updateViewBanner(`⚠️ <b>${reason.toUpperCase()}!</b> ĐANG TỰ ĐỘNG OUT BÀN (0.3s)...`, "joining");
      showToast(`⚠️ <b>${reason}</b><br>Đang tự động Out bàn để ghép lại...`, "warn");

      requestControl("/api/accounts/update-log", {
        profile_name: activeProfileName,
        log: `${reason} -> Tự động Out để tìm lại`,
      }, "POST").catch(() => {});
    }

    // TỰ ĐỘNG THỬ LẠI LƯỢT GHÉP MỚI (ANTI-FLOOD JITTER)
    else if (ev.data.type === "AUTOTOOL_HUNT_RETRYING") {
      const pLabel = activeProfileName || "Tool V3";
      const delayMs = ev.data.delay_ms ? ` (${ev.data.delay_ms}ms)` : "";
      updateViewBanner(`🔄 <b>${pLabel}</b>: Đang tìm lượt ghép mới${delayMs}... [Anti-Flood]`, "joining");

      requestControl("/api/accounts/update-log", {
        profile_name: activeProfileName,
        log: `Đang tìm lượt ghép mới${delayMs}...`,
      }, "POST").catch(() => {});
    }

    // GÓI TIN CHUYỂN TIẾP
    else if (ev.data.type === "AUTOTOOL_BRIDGE_PACKET") {
      safeSendMessage({
        type: "BRIDGE_PACKET",
        profile_name: activeProfileName,
        action: ev.data.action,
        data: ev.data,
      });
    }

    // NHẬN BÀI CHIA ĐẦU VÁN HOẶC CẬP NHẬT
    else if (ev.data.type === "AUTOTOOL_CARDS_DEALT") {
      const cards = ev.data.cards || [];
      updateCardsPanel(cards);
      const pLabel = activeProfileName || "Tool V3";
      updateViewBanner(`🃏 <b>${pLabel}</b>: Đã nhận bài (${cards.length} lá) - Đang xả bài tự động...`, "active");
      showToast(`🃏 <b>ĐÃ CHIA BÀI (${cards.length} LÁ)!</b><br>Tự động xả bài theo thuật toán`, "info");

      safeSendMessage({
        type: "CARDS_DEALT",
        profile_name: activeProfileName,
        cards: cards,
      });

      requestControl("/api/accounts/update-cards", {
        profile_name: activeProfileName,
        cards: cards,
      }, "POST").catch(() => {});
    }

    // CẬP NHẬT BÀI SAU KHI ĐÁNH
    else if (ev.data.type === "AUTOTOOL_CARDS_UPDATED") {
      const cards = ev.data.cards || [];
      const played = ev.data.played_cards || [];
      updateCardsPanel(cards);
      const pLabel = activeProfileName || "Tool V3";
      const playedText = played.map((c) => {
        const inf = parseCardInfo(c);
        return inf ? inf.text : c;
      }).join(" ");

      updateViewBanner(`🃏 <b>${pLabel}</b>: Đã đánh [${playedText}] (Còn ${cards.length} lá)`, "active");

      safeSendMessage({
        type: "CARDS_UPDATED",
        profile_name: activeProfileName,
        cards: cards,
      });

      requestControl("/api/accounts/update-cards", {
        profile_name: activeProfileName,
        cards: cards,
      }, "POST").catch(() => {});
    }

    // HIỂN THỊ BÀI ĐỒNG ĐỘI (CHIA SẺ TỪ EXTENSION HUB)
    else if (ev.data.type === "AUTOTOOL_PARTNER_CARDS_UPDATE") {
      const pName = ev.data.partner_name || "Đồng đội";
      const pCards = ev.data.cards || [];
      updatePartnerCardsPanel(pCards, pName);
    }

    // KẾT THÚC VÁN BÀI
    else if (ev.data.type === "AUTOTOOL_GAME_ENDED") {
      updateCardsPanel([]);
      updatePartnerCardsPanel([]);
      const winner = ev.data.winner || "Kết thúc ván";
      const pLabel = activeProfileName || "Tool V3";
      updateViewBanner(`🏆 <b>VÁN BÀI KẾT THÚC!</b> (${winner} Thắng) | Chuẩn bị ván mới...`, "active");
      showToast(`🏆 <b>VÁN BÀI KẾT THÚC!</b><br>${winner} Về Nhất!<br>Chuẩn bị ván mới tự động...`, "success");

      safeSendMessage({
        type: "CARDS_UPDATED",
        profile_name: activeProfileName,
        cards: [],
      });

      requestControl("/api/accounts/update-cards", {
        profile_name: activeProfileName,
        cards: [],
      }, "POST").catch(() => {});
    }
  });

  // Khởi tạo
  if (document.readyState === "complete" || document.readyState === "interactive") {
    initOverlay();
  } else {
    document.addEventListener("DOMContentLoaded", initOverlay);
  }
  setInterval(updatePill, 2500);
})();

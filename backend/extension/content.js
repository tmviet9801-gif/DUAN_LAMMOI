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
      /* 1. SWEETALERT2 FLOATING TOAST CONTAINER & CARDS */
      #autotool-sweet-container {
        position: fixed !important;
        top: 20px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 2147483647 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        gap: 8px !important;
        pointer-events: none !important;
        user-select: none !important;
      }
      .sw-toast {
        display: flex !important;
        flex-direction: column !important;
        min-width: 260px !important;
        max-width: 480px !important;
        border-radius: 12px !important;
        background: rgba(15, 23, 42, 0.94) !important;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.75), 0 0 1px rgba(255, 255, 255, 0.2) !important;
        backdrop-filter: blur(10px) !important;
        border: 1.5px solid rgba(255, 255, 255, 0.15) !important;
        overflow: hidden !important;
        pointer-events: auto !important;
        cursor: move !important;
        opacity: 0 !important;
        transform: translateY(-20px) scale(0.95) !important;
        transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
      }
      .sw-toast.sw-show {
        opacity: 1 !important;
        transform: translateY(0) scale(1) !important;
      }
      .sw-toast.sw-hide {
        opacity: 0 !important;
        transform: translateY(-15px) scale(0.95) !important;
        transition: all 0.2s ease !important;
      }
      .sw-toast-content {
        display: flex !important;
        align-items: center !important;
        gap: 12px !important;
        padding: 10px 18px !important;
      }
      .sw-icon {
        width: 26px !important;
        height: 26px !important;
        flex-shrink: 0 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 50% !important;
      }
      .sw-icon svg {
        width: 18px !important;
        height: 18px !important;
      }
      .sw-toast-text {
        display: flex !important;
        flex-direction: column !important;
        gap: 2px !important;
        color: #f8fafc !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
      }
      .sw-toast-title {
        font-size: 13px !important;
        font-weight: 700 !important;
        letter-spacing: 0.2px !important;
        line-height: 1.3 !important;
      }
      .sw-toast-body {
        font-size: 11px !important;
        color: #cbd5e1 !important;
        font-weight: 500 !important;
        line-height: 1.2 !important;
      }
      .sw-toast-progress {
        height: 3px !important;
        width: 100% !important;
        background: rgba(255, 255, 255, 0.3) !important;
        transform-origin: left !important;
        animation: sw-progress-shrink linear forwards !important;
      }
      @keyframes sw-progress-shrink {
        from { transform: scaleX(1); }
        to { transform: scaleX(0); }
      }

      /* Biến thể màu SweetAlert2 */
      .sw-type-success {
        border-color: #22c55e !important;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.75), 0 0 15px rgba(34, 197, 94, 0.35) !important;
      }
      .sw-type-success .sw-icon {
        background: rgba(34, 197, 94, 0.2) !important;
        color: #4ade80 !important;
      }
      .sw-type-success .sw-toast-progress {
        background: #22c55e !important;
      }

      .sw-type-warn, .sw-type-joining {
        border-color: #f59e0b !important;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.75), 0 0 15px rgba(245, 158, 11, 0.35) !important;
      }
      .sw-type-warn .sw-icon, .sw-type-joining .sw-icon {
        background: rgba(245, 158, 11, 0.2) !important;
        color: #fbbf24 !important;
      }
      .sw-type-warn .sw-toast-progress, .sw-type-joining .sw-toast-progress {
        background: #f59e0b !important;
      }

      .sw-type-info, .sw-type-lobby, .sw-type-active {
        border-color: #38bdf8 !important;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.75), 0 0 15px rgba(56, 189, 248, 0.35) !important;
      }
      .sw-type-info .sw-icon, .sw-type-lobby .sw-icon, .sw-type-active .sw-icon {
        background: rgba(56, 189, 248, 0.2) !important;
        color: #38bdf8 !important;
      }
      .sw-type-info .sw-toast-progress, .sw-type-lobby .sw-toast-progress, .sw-type-active .sw-toast-progress {
        background: #38bdf8 !important;
      }

      .sw-type-error {
        border-color: #ef4444 !important;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.75), 0 0 15px rgba(239, 68, 68, 0.35) !important;
      }
      .sw-type-error .sw-icon {
        background: rgba(239, 68, 68, 0.2) !important;
        color: #f87171 !important;
      }
      .sw-type-error .sw-toast-progress {
        background: #ef4444 !important;
      }

      /* 2. NÚT NỔI TỐI GIẢN GÓC PHẢI DƯỚI (DRAGGABLE - KHÔNG CHE AVATAR / GOLD GÓC TRÁI) */
      #autotool-connect-btn {
        position: fixed !important;
        right: 145px !important;
        bottom: 12px !important;
        z-index: 2147483647 !important;
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
        padding: 5px 12px !important;
        border-radius: 9999px !important;
        border: 1px solid rgba(255, 255, 255, 0.18) !important;
        background: rgba(15, 23, 42, 0.9) !important;
        color: #94a3b8 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.6) !important;
        cursor: move !important;
        user-select: none !important;
        backdrop-filter: blur(6px) !important;
        transition: background 0.2s ease, border-color 0.2s ease !important;
      }
      #autotool-connect-btn:hover {
        background: rgba(30, 41, 59, 0.98) !important;
        color: #f1f5f9 !important;
        border-color: rgba(255, 255, 255, 0.3) !important;
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

  // Helper biến bất kỳ phần tử nào thành có thể kéo thả (Draggable) và lưu vị trí vào localStorage
  function makeDraggable(el, storageKey) {
    if (!el) return;

    // Phục hồi vị trí đã lưu từ lần trước
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      try {
        const pos = JSON.parse(saved);
        if (typeof pos.x === "number" && typeof pos.y === "number") {
          const maxX = Math.max(10, window.innerWidth - (el.offsetWidth || 120));
          const maxY = Math.max(10, window.innerHeight - (el.offsetHeight || 30));
          const clX = Math.min(Math.max(0, pos.x), maxX);
          const clY = Math.min(Math.max(0, pos.y), maxY);
          el.style.left = clX + "px";
          el.style.top = clY + "px";
          el.style.right = "auto";
          el.style.bottom = "auto";
          el.style.transform = "none";
        }
      } catch (_) {}
    }

    let isDragging = false;
    let hasMoved = false;
    let startX = 0, startY = 0;
    let initialLeft = 0, initialTop = 0;

    el.style.cursor = "move";

    el.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return; // Chỉ kéo khi click chuột trái
      isDragging = true;
      hasMoved = false;
      startX = e.clientX;
      startY = e.clientY;

      const rect = el.getBoundingClientRect();
      initialLeft = rect.left;
      initialTop = rect.top;

      function onMouseMove(moveEv) {
        if (!isDragging) return;
        const dx = moveEv.clientX - startX;
        const dy = moveEv.clientY - startY;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
          hasMoved = true;
        }
        const newX = Math.max(0, Math.min(window.innerWidth - (el.offsetWidth || 100), initialLeft + dx));
        const newY = Math.max(0, Math.min(window.innerHeight - (el.offsetHeight || 30), initialTop + dy));

        el.style.left = newX + "px";
        el.style.top = newY + "px";
        el.style.right = "auto";
        el.style.bottom = "auto";
        el.style.transform = "none";
      }

      function onMouseUp() {
        if (!isDragging) return;
        isDragging = false;
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);

        if (hasMoved) {
          const finalRect = el.getBoundingClientRect();
          try {
            localStorage.setItem(storageKey, JSON.stringify({ x: finalRect.left, y: finalRect.top }));
          } catch (_) {}
        }
      }

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    });

    el.addEventListener("click", (e) => {
      if (hasMoved) {
        e.stopPropagation();
        e.preventDefault();
      }
    }, true);
  }

  // THÔNG BÁO NỔI DẠNG SWEETALERT2 (TỰ TẮT SAU 1.5 - 2 GIÂY, DRAGGABLE)
  function showSweetToast(title, bodyText = "", type = "info", duration = 1800) {
    if (window !== window.top) return;
    ensureStyles();

    let container = document.getElementById("autotool-sweet-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "autotool-sweet-container";
      (document.body || document.documentElement).appendChild(container);
      makeDraggable(container, "AUTOTOOL_POS_SWEET_TOAST");
    }

    const icons = {
      success: `<div class="sw-icon"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg></div>`,
      warn: `<div class="sw-icon"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg></div>`,
      joining: `<div class="sw-icon"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M13 2.05v2.02c3.95.49 7 3.85 7 7.93 0 3.21-1.92 6-4.72 7.28L14.47 21A9.99 9.99 0 0 0 22 12c0-5.18-3.95-9.45-9-9.95z"/></svg></div>`,
      info: `<div class="sw-icon"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg></div>`,
      active: `<div class="sw-icon"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg></div>`,
    };

    const iconHtml = icons[type] || icons.info;
    const toast = document.createElement("div");
    toast.className = `sw-toast sw-type-${type}`;
    toast.innerHTML = `
      <div class="sw-toast-content">
        ${iconHtml}
        <div class="sw-toast-text">
          <div class="sw-toast-title">${title}</div>
          ${bodyText ? `<div class="sw-toast-body">${bodyText}</div>` : ""}
        </div>
      </div>
      <div class="sw-toast-progress" style="animation-duration: ${duration}ms"></div>
    `;

    container.appendChild(toast);
    requestAnimationFrame(() => {
      toast.classList.add("sw-show");
    });

    setTimeout(() => {
      toast.classList.remove("sw-show");
      toast.classList.add("sw-hide");
      setTimeout(() => {
        try { toast.remove(); } catch (_) {}
      }, 250);
    }, duration);
  }

  function updateViewBanner(htmlText, type = "lobby") {
    if (window !== window.top) return;
    // Bóc tách title và body từ htmlText nếu có thẻ <b>
    let title = htmlText;
    let body = "";
    if (htmlText.includes("<b>") && htmlText.includes("</b>")) {
      const parts = htmlText.split("</b>");
      title = parts[0].replace("<b>", "").trim();
      body = parts.slice(1).join("</b>").replace(/<[^>]+>/g, "").replace(/^[\s:|-]+/, "").trim();
    } else {
      title = htmlText.replace(/<[^>]+>/g, "").trim();
    }
    showSweetToast(title, body, type, 1800);
  }

  function showToast(text, type = "info") {
    if (window !== window.top) return;
    let title = "AutoTool V3";
    let body = text;
    if (text.includes("<b>") && text.includes("</b>")) {
      const parts = text.split("</b>");
      title = parts[0].replace(/<[^>]+>/g, "").trim();
      body = parts.slice(1).join("</b>").replace(/<[^>]+>/g, "").replace(/^[\s:|-]+/, "").trim();
    }
    showSweetToast(title, body, type, 1800);
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

    // Nút trạng thái tối giản (Mặc định ở GÓC PHẢI DƯỚI, DRAGGABLE - KHÔNG CHE AVATAR/GOLD)
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
    makeDraggable(btn, "AUTOTOOL_POS_CONNECT_BTN");

    // Nút Bật/Tắt Săn Bàn & Tự động Out khi gặp khách lạ (Mặc định ở GÓC PHẢI DƯỚI, DRAGGABLE)
    const huntBtn = document.createElement("button");
    huntBtn.id = "autotool-hunt-btn";
    huntBtn.style.cssText = "position:fixed!important;right:12px!important;bottom:12px!important;z-index:2147483647!important;display:inline-flex!important;align-items:center!important;gap:5px!important;padding:5px 12px!important;border-radius:9999px!important;border:1px solid rgba(245,158,11,0.5)!important;background:rgba(69,26,3,0.9)!important;color:#fde68a!important;font-family:sans-serif!important;font-size:11px!important;font-weight:700!important;cursor:move!important;user-select:none!important;backdrop-filter:blur(6px)!important;box-shadow:0 4px 14px rgba(0,0,0,0.6)!important;";
    huntBtn.innerHTML = "🎯 Săn Bàn: BẬT";
    let isHuntOn = true;
    huntBtn.addEventListener("click", () => {
      isHuntOn = !isHuntOn;
      huntBtn.innerHTML = isHuntOn ? "🎯 Săn Bàn: BẬT" : "⚪ Săn Bàn: TẮT";
      huntBtn.style.background = isHuntOn ? "rgba(69,26,3,0.9)" : "rgba(30,41,59,0.9)";
      huntBtn.style.color = isHuntOn ? "#fde68a" : "#94a3b8";
      huntBtn.style.borderColor = isHuntOn ? "rgba(245,158,11,0.5)" : "rgba(255,255,255,0.2)";
      window.postMessage({ type: "AUTOTOOL_SET_HUNT", auto_hunt: isHuntOn }, "*");
      showSweetToast("Chế độ Săn Bàn", `Đã ${isHuntOn ? 'BẬT' : 'TẮT'} tự động tìm & out bàn`, isHuntOn ? "warn" : "info", 1800);
    });
    (document.body || document.documentElement).appendChild(huntBtn);
    makeDraggable(huntBtn, "AUTOTOOL_POS_HUNT_BTN");

    // Thông báo mở đầu dạng SweetAlert2 (tự tắt sau 1.8s)
    const pLabel = activeProfileName || "Tool V3";
    showSweetToast(`AutoTool V3 (${pLabel})`, "Đang ở sảnh Tiến Lên Đếm Lá", "info", 1800);

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

    const pName = activeProfileName || localStorage.getItem("AUTOTOOL_PROFILE_NAME") || localStorage.getItem("KEY_USER_NAME") || document.title || "";
    const pLabel = (pName || "Tool V3").replace(/^#\d+\s*/, "");

    btn.className = "on";
    if (lastRoomInfo && lastRoomInfo.rid) {
      txt.textContent = `🟢 ${lastRoomInfo.rn || 'Bàn ' + lastRoomInfo.rid} (${pLabel})`;
    } else {
      txt.textContent = `🟢 Online (${pLabel})`;
    }

    safeSendMessage({ type: "CHECK_HEALTH", profile_name: pLabel }, (res) => {
      if (res && res.profile_name) activeProfileName = res.profile_name;
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
      } else if (action === "LEAVE_ROOM") {
        pendingJoinRid = null;
        matchedPartner = "";
        updateViewBanner(`🏠 <b>${activeProfileName}</b>: Đang về sảnh (Hủy bàn)`, "lobby");
        showToast("⚠️ Hủy lệnh vào bàn / Rời phòng về sảnh!", "warn");
        requestControl("/api/accounts/update-log", {
          profile_name: activeProfileName,
          log: (data && data.reason) || "Rời phòng về sảnh",
        }, "POST").catch(() => {});
        window.postMessage({
          type: "AUTOTOOL_EXEC_COMMAND",
          action: "LEAVE_ROOM",
          data: data,
        }, "*");
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
      } else if (action === "START_HUNT") {
        isHuntOn = true;
        const hBtn = document.getElementById("autotool-hunt-btn");
        if (hBtn) {
          hBtn.innerHTML = "🎯 Săn Bàn: BẬT";
          hBtn.style.background = "rgba(69,26,3,0.9)";
          hBtn.style.color = "#fde68a";
          hBtn.style.borderColor = "rgba(245,158,11,0.5)";
        }
        window.postMessage({
          type: "AUTOTOOL_SET_HUNT",
          auto_hunt: true,
          auto_start_guest_ss: data && data.auto_start_guest_ss,
          auto_xa: data && data.auto_xa,
        }, "*");
        updateViewBanner(`🎯 <b>${activeProfileName || 'Tool V3'}</b>: Đang SĂN BÀN mức $${((data && data.bet) || 100).toLocaleString()}`, "active");
        showToast(`🎯 Bắt đầu SĂN BÀN mức $${((data && data.bet) || 100).toLocaleString()}!`, "info");
        window.postMessage({
          type: "AUTOTOOL_EXEC_COMMAND",
          action: "START_HUNT",
          data: data,
        }, "*");
      } else if (action === "WAIT_IN_LOBBY") {
        isHuntOn = false;
        const anchor = (data && data.anchor) || "Account 1";
        const bet = (data && data.bet) || 100;
        updateViewBanner(`⏳ <b>${activeProfileName || 'Nick phụ'}</b>: Đang đợi ${anchor} tìm bàn trống $${bet.toLocaleString()}...`, "lobby");
        showToast(`⏳ Đang đợi ${anchor} tìm bàn trống $${bet.toLocaleString()}...`, "info");
        requestControl("/api/accounts/update-log", {
          profile_name: activeProfileName,
          log: `Đang đợi ${anchor} tìm bàn...`,
        }, "POST").catch(() => {});
      } else if (action === "STOP_HUNT") {
        isHuntOn = false;
        const hBtn = document.getElementById("autotool-hunt-btn");
        if (hBtn) {
          hBtn.innerHTML = "⚪ Săn Bàn: TẮT";
          hBtn.style.background = "rgba(30,41,59,0.9)";
          hBtn.style.color = "#94a3b8";
          hBtn.style.borderColor = "rgba(255,255,255,0.2)";
        }
        window.postMessage({ type: "AUTOTOOL_SET_HUNT", auto_hunt: false }, "*");
        updateViewBanner(`⏹️ <b>${activeProfileName || 'Tool V3'}</b>: Đã DỪNG săn bàn`, "lobby");
        showSweetToast("AutoTool", "Đã DỪNG săn bàn theo lệnh", "info", 1800);
        window.postMessage({
          type: "AUTOTOOL_EXEC_COMMAND",
          action: "STOP_HUNT",
          data: data,
        }, "*");
      } else if (action === "RESET_STATE") {
        // RESET_STATE CHỈ XÓA BỘ NHỚ BIẾN TRẠNG THÁI CŨ, TUYỆT ĐỐI KHÔNG TẮT SĂN BÀN!
        window.postMessage({
          type: "AUTOTOOL_EXEC_COMMAND",
          action: "RESET_STATE",
          data: data,
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
      // FIX CRITICAL: Nếu có dn/uid (từ cmd 100), forward NGAY lên Hub để Hub biết
      // tên in-game thực tế của profile. Thiếu bước này → anchor_dn luôn rỗng
      // → B không nhận ra A khi cmd 202 đến (race condition).
      if (ev.data.dn || ev.data.uid) {
        safeSendMessage({
          type: "AUTOTOOL_USERNAME_SYNC",
          profile_name: ev.data.profile_name,
          real_dn:  ev.data.dn  || "",
          real_u:   ev.data.u   || "",
          real_uid: String(ev.data.uid || ""),
        });
      }
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

    // ĐỒNG BỘ TÊN IN-GAME THỰC TẾ (TRÁNH LỆCH KÝ TỰ) — chạy 1 lần khi game trả về cmd 100
    else if (ev.data.type === "AUTOTOOL_USERNAME_SYNC") {
      const realDn  = ev.data.real_dn;
      const realU   = ev.data.real_u;
      const realUid = ev.data.real_uid;
      const pName   = activeProfileName || ev.data.profile_name;
      if (realDn && pName) {
        // Cập nhật banner để người dùng thấy tên thực đang dùng
        const btn = document.getElementById("autotool-btn-text");
        if (btn) btn.textContent = `🟢 Online (${realDn})`;

        // Gửi lên Hub qua WebSocket (để broadcast_partners dùng đúng tên)
        safeSendMessage({
          type: "AUTOTOOL_USERNAME_SYNC",
          profile_name: pName,
          real_dn: realDn,
          real_u: realU,
          real_uid: realUid,
        });

        // Gọi REST API để cập nhật username vào accounts.json ngay lập tức
        requestControl("/api/accounts/update-username", {
          profile_name: pName,
          real_dn: realDn,
          real_u: realU,
          real_uid: realUid,
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

    // HỦY LỆNH MỜI BÀN (DO CÓ NGƯỜI LẠ HOẶC BÀN FULL)
    else if (ev.data.type === "AUTOTOOL_CANCEL_ROOM_INVITE") {
      pendingJoinRid = null;
      matchedPartner = "";
      safeSendMessage({
        type: "CANCEL_ROOM_INVITE",
        profile_name: activeProfileName || ev.data.profile_name,
        rid: ev.data.rid,
        reason: ev.data.reason,
      });
    }

    // XÁC NHẬN BÀN TRỐNG 100% TỪ CHỦ BÀN
    else if (ev.data.type === "AUTOTOOL_ANCHOR_ROOM_VERIFIED_EMPTY") {
      const rId = ev.data.rid || (ev.data.room_info && ev.data.room_info.rid) || "Chống Vây";
      const bVal = ev.data.b || 100;
      updateViewBanner(`🎯 <b>${activeProfileName || 'Account 1'}</b>: Bàn #${rId} ($${bVal}) trống 100%! Đang phát lệnh mời đồng đội vào ghép...`, "active");
      showToast(`🎯 Bàn #${rId} ($${bVal}) TRỐNG 100%! Đang gọi Account 2...`, "success");
      safeSendMessage({
        type: "ANCHOR_ROOM_VERIFIED_EMPTY",
        profile_name: activeProfileName || ev.data.profile_name,
        room_info: ev.data.room_info,
        rid: ev.data.rid,
        bet: ev.data.b,
        mu: ev.data.Mu,
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
      if (partner && !["none", "null", "undefined", ""].includes(String(partner).trim().toLowerCase())) {
        safeSendMessage({
          type: "PARTNER_MATCHED",
          profile_name: activeProfileName,
          partner_name: partner,
        });
      }

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

    // HIỂN THỊ HÀNH ĐỘNG ĐỒNG ĐỘI VỪA ĐÁNH BÀI
    else if (ev.data.type === "AUTOTOOL_PARTNER_PLAYED") {
      const pName = ev.data.partner_name || "Đồng đội";
      const played = ev.data.played_cards || [];
      const playedText = played.map((c) => {
        const inf = parseCardInfo(c);
        return inf ? inf.text : c;
      }).join(" ");
      updateViewBanner(`⚡ <b>${pName}</b>: Đã đánh [${playedText}]`, "joining");
    }

    // HIỂN THỊ ĐỒNG ĐỘI / ĐỐI PHƯƠNG BỎ LƯỢT
    else if (ev.data.type === "AUTOTOOL_PARTNER_PASSED") {
      const pName = ev.data.partner_name || "Đồng đội";
      updateViewBanner(`🟡 <b>${pName}</b>: Đã BỎ LƯỢT! Đến lượt bạn xả tiếp!`, "active");
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

    // TÀI KHOẢN BỊ ĐĂNG XUẤT / HẾT PHIÊN
    else if (ev.data.type === "AUTOTOOL_ACCOUNT_LOGGED_OUT") {
      const pLabel = activeProfileName || "Tool V3";
      const reason = ev.data.reason || "Hết phiên / bị kick";
      updateViewBanner(`⚠️ <b>${pLabel}: TÀI KHOẢN BỊ ĐĂNG XUẤT!</b> ${reason}`, "error");
      showToast(`⚠️ <b>TÀI KHOẢN BỊ ĐĂNG XUẤT!</b><br>${pLabel}<br>${reason}`, "warn");

      requestControl("/api/accounts/update-log", {
        profile_name: activeProfileName,
        log: `⚠️ Tài khoản bị đăng xuất: ${reason}`,
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

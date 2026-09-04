const BACKEND_URL = "http://127.0.0.1:8000";

let currentProfile = "Account01";
let autoDetected = false;
let knownNames = ["nicktestxabai1", "nicktestxabai2", "nicktestxxabai1", "nicktestxxabai2", "account01", "account02"];

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initActions();
  loadConfig();
  detectCurrentTab();
  refreshStatus();
  setInterval(refreshStatus, 2500);
});

function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      currentProfile = tab.dataset.profile;
      autoDetected = true; // user manually chose
      refreshStatus();
    });
  });
}

function selectTab(profileName) {
  currentProfile = profileName;
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach((t) => {
    if (t.dataset.profile === profileName) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });
  fetchProfileInfo(profileName);
}

async function fetchProfileInfo(profileName) {
  try {
    const data = await callBackend(`/api/autoplay/profile-info?profile_name=${profileName}`);
    if (data && data.ok) {
      const elAcc = document.getElementById("cur-account");
      const elBal = document.getElementById("cur-balance");
      if (elAcc) elAcc.textContent = data.user || data.dn;
      if (elBal && data.gold !== null && data.gold !== undefined) {
        elBal.textContent = `${Number(data.gold).toLocaleString()} đ`;
      }
      const elRoom = document.getElementById("cur-room");
      const elBet = document.getElementById("cur-bet");
      if (elRoom && elRoom.textContent.includes("Chưa vào bàn")) {
        elRoom.textContent = data.room || "Ở sảnh (Chưa vào bàn)";
        if (elBet) elBet.textContent = data.bet || "--";
      }
    }
  } catch (_) {}
}

function initActions() {
  document.getElementById("btn-refresh").addEventListener("click", refreshStatus);

  document.getElementById("btn-gom-ban").addEventListener("click", handleGomBan);
  document.getElementById("btn-roi-ban").addEventListener("click", handleLeaveRoom);
  document.getElementById("btn-xa-bai").addEventListener("click", handleDiscard);

  // Save config changes
  document.getElementById("select-bet").addEventListener("change", saveConfig);
  document.getElementById("select-mu").addEventListener("change", saveConfig);
  document.getElementById("chk-chong-pha").addEventListener("change", saveConfig);
  document.getElementById("chk-auto-xa").addEventListener("change", saveConfig);
  document.getElementById("input-delay").addEventListener("change", saveConfig);
  document.getElementById("input-max-tries").addEventListener("change", saveConfig);
}

function saveConfig() {
  const cfg = {
    bet: document.getElementById("select-bet").value,
    mu: document.getElementById("select-mu").value,
    chong_pha: document.getElementById("chk-chong-pha").checked,
    auto_xa: document.getElementById("chk-auto-xa").checked,
    delay: document.getElementById("input-delay").value,
    max_tries: document.getElementById("input-max-tries").value,
  };
  chrome.storage.local.set({ autotool_config: cfg });
}

function loadConfig() {
  chrome.storage.local.get(["autotool_config"], (res) => {
    if (res && res.autotool_config) {
      const cfg = res.autotool_config;
      if (cfg.bet) document.getElementById("select-bet").value = cfg.bet;
      if (cfg.mu) document.getElementById("select-mu").value = cfg.mu;
      if (typeof cfg.chong_pha === "boolean") document.getElementById("chk-chong-pha").checked = cfg.chong_pha;
      if (typeof cfg.auto_xa === "boolean") document.getElementById("chk-auto-xa").checked = cfg.auto_xa;
      if (cfg.delay) document.getElementById("input-delay").value = cfg.delay;
      if (cfg.max_tries) document.getElementById("input-max-tries").value = cfg.max_tries;
    }
  });
}

function showMsg(text, type = "success") {
  const box = document.getElementById("action-msg");
  box.textContent = text;
  box.className = `msg-box ${type}`;
  box.classList.remove("hidden");
  setTimeout(() => box.classList.add("hidden"), 4000);
}

// Tự động nhận diện tab hiện tại đang mở là Account nào
function detectCurrentTab() {
  try {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || !tabs[0] || !tabs[0].id) return;
      chrome.scripting.executeScript(
        {
          target: { tabId: tabs[0].id },
          world: "MAIN",
          func: () => {
            return {
              user: localStorage.getItem("KEY_USER_NAME") || "",
              token: !!localStorage.getItem("token"),
              room: window.__last_room_info || null,
              players: window.__room_players || [],
              state: window.__room_state,
            };
          },
        },
        (results) => {
          if (chrome.runtime.lastError || !results || !results[0]) return;
          const info = results[0].result;
          if (info && info.user) {
            const u = info.user.toLowerCase();
            if (u.includes("2") || u.includes("acc02") || u.includes("account02") || u.includes("xabai2")) {
              selectTab("Account02");
            } else {
              selectTab("Account01");
            }
            renderInfo(info);
          }
        }
      );
    });
  } catch (_) {}
}

function renderInfo(info) {
  if (!info) return;

  // 1. Account name
  if (info.user) {
    document.getElementById("cur-account").textContent = info.user;
  }

  // 2. Room info
  if (info.room && info.room.rid) {
    document.getElementById("cur-room").textContent = info.room.rn || `Bàn #${info.room.rid}`;
    const betVal = info.room.b ? `$ ${Number(info.room.b).toLocaleString()}` : "--";
    document.getElementById("cur-bet").textContent = betVal;
  } else {
    document.getElementById("cur-room").textContent = "Ở sảnh (Chưa vào bàn)";
    document.getElementById("cur-bet").textContent = "--";
  }

  // 3. Players list
  const tagsContainer = document.getElementById("player-tags");
  const countEl = document.getElementById("player-count");
  const alertBox = document.getElementById("stranger-alert");

  const players = info.players || [];
  const maxUsers = (info.room && info.room.Mu) || 4;
  countEl.textContent = `${players.length}/${maxUsers}`;

  if (players.length === 0) {
    tagsContainer.innerHTML = '<span class="empty-hint">Chưa có người chơi</span>';
    alertBox.classList.add("hidden");
  } else {
    tagsContainer.innerHTML = "";
    let hasStranger = false;

    players.forEach((p) => {
      const dn = (p.dn || p.u || "Unknown").trim();
      const lower = dn.toLowerCase();
      const isTeam = knownNames.some((k) => k === lower || lower.includes(k) || k.includes(lower));

      if (!isTeam) hasStranger = true;

      const span = document.createElement("span");
      span.className = `player-tag ${isTeam ? "team" : "stranger"}`;
      span.textContent = `${dn} ${isTeam ? "(Phe mình)" : "(Khách lạ!)"}`;
      tagsContainer.appendChild(span);
    });

    if (hasStranger) {
      alertBox.classList.remove("hidden");
    } else {
      alertBox.classList.add("hidden");
    }
  }
}

async function callBackend(path, method = "GET", body = null) {
  // Luôn ưu tiên dùng background service worker để tránh lỗi Mixed Content/CSP
  try {
    return await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: "API_CALL", path, method, body },
        (response) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else if (response && response.ok) {
            resolve(response.data);
          } else {
            reject(new Error((response && response.error) || "Lỗi gọi API Backend"));
          }
        }
      );
    });
  } catch (err1) {
    // Fallback thử fetch trực tiếp
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body && method !== "GET") opts.body = JSON.stringify(body);
    const res = await fetch(`${BACKEND_URL}${path}`, opts);
    return await res.json();
  }
}

async function refreshStatus() {
  detectCurrentTab();

  let isConnected = false;
  // 1. Kiểm tra qua service worker
  try {
    isConnected = await new Promise((res) => {
      chrome.runtime.sendMessage({ type: "CHECK_HEALTH" }, (resp) => {
        if (chrome.runtime.lastError || !resp) res(false);
        else res(resp.ok === true);
      });
    });
  } catch (_) {}

  // 2. Fallback kiểm tra trực tiếp
  if (!isConnected) {
    try {
      const r = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(1500) });
      if (r.ok) isConnected = true;
    } catch (_) {
      try {
        const r2 = await fetch(`http://localhost:8000/health`, { signal: AbortSignal.timeout(1500) });
        if (r2.ok) isConnected = true;
      } catch (_) {}
    }
  }

  const badge = document.getElementById("backend-status");
  if (badge) {
    if (isConnected) {
      badge.className = "status-badge connected";
      badge.innerHTML = '<span class="dot"></span> Online';
    } else {
      badge.className = "status-badge disconnected";
      badge.innerHTML = '<span class="dot"></span> Offline';
    }
  }
}

async function handleGomBan() {
  const btn = document.getElementById("btn-gom-ban");
  btn.disabled = true;
  btn.innerHTML = "<span>⏳</span> ĐANG TÌM BÀN TRỐNG...";

  let mainName = "Account01";
  let subName = "Account02";
  const selMain = document.getElementById("select-main-profile");
  const selSub = document.getElementById("select-sub-profile");
  if (selMain && selMain.value) mainName = selMain.value;
  if (selSub && selSub.value) subName = selSub.value;

  const targetBet = parseInt(document.getElementById("select-bet").value, 10);
  const targetMu = parseInt(document.getElementById("select-mu").value, 10);
  const maxTries = parseInt(document.getElementById("input-max-tries").value, 10) || 10;

  try {
    const data = await callBackend("/api/autoplay/find-and-match-ws", "POST", {
      profile_a: mainName,
      profile_b: subName,
      target_bet: targetBet,
      mu: targetMu,
      gid: 1, // Tiến Lên Đếm Lá
      max_tries: maxTries,
    });

    if (data && data.ok) {
      showMsg(`Đã gom ${mainName} và ${subName} vào chung bàn (Cược $${(data.bet || targetBet).toLocaleString()})!`);
    } else {
      showMsg((data && data.error) || "Không tìm được bàn trống phù hợp mức cược đã chọn.", "error");
    }
  } catch (e) {
    showMsg(`Lỗi kết nối gom bàn: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = "<span>🚀</span> BẮT ĐẦU GOM BÀN";
    setTimeout(refreshStatus, 1500);
  }
}

async function handleLeaveRoom() {
  try {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs && tabs[0]) {
        chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          func: () => {
            if (typeof window.__ws_send_channel === "function") {
              window.__ws_send_channel("Simms", '[4,"Simms",-1]');
            } else if (typeof window.__ws_send === "function") {
              window.__ws_send('[4,"Simms",-1]');
            }
          },
        });
      }
    });
    showMsg("Đã gửi lệnh rời bàn");
    setTimeout(refreshStatus, 1000);
  } catch (e) {
    showMsg(`Lỗi rời bàn: ${e.message}`, "error");
  }
}

async function handleDiscard() {
  try {
    const delay = parseInt(document.getElementById("input-delay").value, 10) || 1000;
    const data = await callBackend("/api/autoplay/test-discard", "POST", {
      profile_name: currentProfile,
      delay_ms: delay,
    });
    if (data && data.ok) {
      showMsg(`Đã thực hiện xả bài cho ${currentProfile}`);
    } else {
      showMsg("Xả bài thất bại", "error");
    }
  } catch (e) {
    showMsg(`Lỗi xả bài: ${e.message}`, "error");
  }
}

const API = window.desktop ? window.desktop.backendUrl : "http://127.0.0.1:8000";

const state = {
  config: null,
  accounts: [],
  sessions: [],
  antiDetect: null,
  info: null,
  ws: null,
  version: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("toastContainer").appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function confirmDialog(title, message, onOk, okLabel = "Xác nhận") {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <h3>${esc(title)}</h3>
      <p>${esc(message)}</p>
      <div class="actions">
        <button class="modal-cancel">Hủy</button>
        <button class="primary modal-ok">${esc(okLabel)}</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector(".modal-cancel").onclick = close;
  overlay.querySelector(".modal-ok").onclick = () => {
    close();
    onOk();
  };
  overlay.onclick = (e) => {
    if (e.target === overlay) close();
  };
}

async function runApi(path, options, okMsg, errMsg) {
  try {
    await api(path, options);
    if (okMsg) toast(okMsg, "success");
  } catch (e) {
    toast(errMsg || `Lỗi: ${e.message}`, "error");
  }
}

function setBackend(ok) {
  $("backendDot").className = "dot " + (ok ? "ok" : "err");
  $("backendText").textContent = ok ? "Backend sẵn sàng" : "Mất kết nối";
}

async function refresh() {
  try {
    state.config = await api("/api/config");
    state.accounts = await api("/api/accounts");
    state.sessions = await api("/api/sessions");
    if (!state.antiDetect) state.antiDetect = await api("/api/antidetect");
    if (!state.info) state.info = await api("/api/info");
    if (!state.version) state.version = await api("/api/version");
    setBackend(true);
    renderConfig();
    renderAccounts();
    renderSessions();
    renderInfo();
  } catch (e) {
    setBackend(false);
  }
}

function renderInfo() {
  if (!state.info) return;
  $("infoProfilesDir").textContent = state.info.profiles_dir;
  $("infoDataDir").textContent = state.info.data_dir;
  $("infoVersion").textContent = state.version
    ? `${state.version.app} v${state.version.version}`
    : "…";
}

function fillSelect(sel, options, value, labelFn) {
  sel.innerHTML = "";
  for (const opt of options) {
    const o = document.createElement("option");
    o.value = opt;
    o.textContent = labelFn ? labelFn(opt) : opt;
    if (opt === value) o.selected = true;
    sel.appendChild(o);
  }
}

function renderConfig() {
  const g = state.config.grid;
  const w = state.config.window;
  const ad = state.config.anti_detect;
  $("cfgCols").value = g.cols;
  $("cfgGap").value = g.gap;
  $("cfgMargin").value = g.margin;
  $("cfgDirection").value = state.config.open_direction || "row";
  $("cfgWinW").value = w.width || 0;
  $("cfgWinH").value = w.height || 0;
  $("cfgCount").value = state.config.default_count;
  $("cfgAutoLayout").checked = !!state.config.auto_layout;
  if (state.antiDetect) {
    const osLabels = { random: "Ngẫu nhiên", windows: "Windows", macos: "macOS", linux: "Linux" };
    fillSelect($("cfgOs"), state.antiDetect.os, ad.os, (o) => osLabels[o] || o);
    fillSelect($("cfgLocale"), state.antiDetect.locale, ad.locale, (l) =>
      l === "random" ? "Ngẫu nhiên" : l
    );
  }
}

function renderAccounts() {
  const list = $("accountList");
  list.innerHTML = "";
  if (!state.accounts.length) {
    list.innerHTML = '<li class="hint">Chưa có profile. Thêm profile đầu tiên bên trên.</li>';
    return;
  }
  for (const a of state.accounts) {
    const li = document.createElement("li");
    li.className = "account-item";
    const sessionBadge = a.save_session
      ? '<span class="profile-badge">profile</span>'
      : '<span class="profile-badge temp">tạm thời</span>';
    const uaInfo = a.user_agent
      ? esc(a.user_agent)
      : a.profile_ua
        ? esc(a.profile_ua)
        : "ngẫu nhiên khi mở";
    li.innerHTML = `
      <div class="name">
        <span>#${a.index} ${esc(a.name)} ${sessionBadge}</span>
        <button class="remove" title="Xóa">×</button>
      </div>
      <div class="meta">${esc(a.url || "about:blank")}</div>
      <div class="meta">UA: ${uaInfo}</div>
    `;
    li.querySelector(".remove").onclick = async () => {
      confirmDialog(
        `Xóa profile #${a.index} "${a.name}"?`,
        a.save_session
          ? "Profile này có lưu session (cookies, đăng nhập). Xóa sẽ đóng cửa sổ đang mở và xóa profile khỏi danh sách."
          : "Xóa sẽ đóng cửa sổ đang mở (nếu có) và xóa profile khỏi danh sách.",
        async () => {
          await runApi(
            "/api/accounts/" + a.id,
            { method: "DELETE" },
            `Đã xóa profile #${a.index} "${a.name}"`,
            "Xóa profile thất bại"
          );
          refresh();
        },
        "Xóa"
      );
    };
    list.appendChild(li);
  }
}

function renderSessions() {
  $("sessionCount").textContent = state.sessions.length;
  const grid = $("sessionGrid");
  grid.innerHTML = "";
  if (!state.sessions.length) {
    grid.innerHTML = '<div class="hint">Chưa có cửa sổ nào đang mở.</div>';
    return;
  }
  for (const s of state.sessions) {
    const item = document.createElement("div");
    item.className = "session-item";
    let accountName = "(tab trống)";
    let accountIdx = "";
    if (s.account) {
      accountName = s.account.name;
      accountIdx = `#${s.account.index || ""} `;
    }
    const stateClass = s.error ? "error" : s.state;
    const fpOs = s.fp_os && s.fp_os !== "random" ? s.fp_os : "tự động";
    item.innerHTML = `
      <span class="badge ${stateClass}">${stateClass}</span>
      <div class="info">
        <div class="t">${accountIdx}${esc(accountName)}</div>
        <div class="u">${esc(s.url)}</div>
        <div class="fp">Fingerprint: OS ${esc(fpOs)} · UA ${esc(s.ua ? s.ua.slice(0, 90) + "…" : "đang tạo…")}</div>
      </div>
      <button class="close" title="Đóng">×</button>
    `;
    item.querySelector(".close").onclick = async () => {
      await runApi(
        "/api/browser/close",
        {
          method: "POST",
          body: JSON.stringify({ session_ids: [s.session_id] }),
        },
        accountName !== "(tab trống)" ? `Đã đóng "${accountName}"` : "Đã đóng cửa sổ",
        "Đóng cửa sổ thất bại"
      );
    };
    grid.appendChild(item);
  }
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function connectWs() {
  const ws = new WebSocket(`ws://127.0.0.1:8000/ws`);
  ws.onopen = () => setBackend(true);
  ws.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.sessions) {
      state.sessions = ev.sessions;
      renderSessions();
    }
  };
  ws.onclose = () => {
    setBackend(false);
    setTimeout(connectWs, 2000);
  };
  state.ws = ws;
}

async function saveConfig() {
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        grid: {
          cols: +$("cfgCols").value,
          gap: +$("cfgGap").value,
          margin: +$("cfgMargin").value,
        },
        window: {
          width: +$("cfgWinW").value || 0,
          height: +$("cfgWinH").value || 0,
        },
        open_direction: $("cfgDirection").value,
        anti_detect: {
          os: $("cfgOs").value,
          locale: $("cfgLocale").value,
        },
        default_count: +$("cfgCount").value,
        auto_layout: $("cfgAutoLayout").checked,
      }),
    });
    toast("Đã lưu cấu hình", "success");
    refresh();
  } catch (e) {
    toast("Lưu cấu hình thất bại: " + e.message, "error");
  }
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab-panel").forEach((p) =>
      p.classList.toggle("hidden", p.id !== "tab-" + btn.dataset.tab)
    );
  };
});

$("btnSaveConfig").onclick = saveConfig;

function applyLayout() {
  runApi("/api/browser/layout", { method: "POST" }, "Đã xếp lại lưới cửa sổ", "Xếp lưới thất bại");
}
$("btnLayout").onclick = applyLayout;
$("btnLayout2").onclick = applyLayout;

function openTabs(count, all) {
  if (!state.accounts.length) {
    toast("Chưa có profile nào. Hãy thêm profile trước khi mở.", "error");
    return;
  }
  const body = all ? {} : { count };
  runApi("/api/browser/open", { method: "POST", body: JSON.stringify(body) }, null, "Mở tab thất bại");
}

$("btnOpenCount").onclick = () => openTabs(+$("cfgCount").value, false);

$("btnOpenAll").onclick = () => openTabs(null, true);

$("btnCloseAll").onclick = () => {
  if (!state.sessions.length) {
    toast("Không có cửa sổ nào đang mở", "warn");
    return;
  }
  confirmDialog(
    "Đóng tất cả cửa sổ?",
    `Có ${state.sessions.length} cửa sổ đang mở. Nếu profile có lưu session, đăng nhập vẫn được giữ lại và lần sau mở lại không cần login.`,
    () => runApi("/api/browser/close", { method: "POST", body: JSON.stringify({}) }, "Đã đóng tất cả cửa sổ", "Đóng cửa sổ thất bại"),
    "Đóng tất cả"
  );
};

$("accountForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify({
        name: $("accName").value,
        url: $("accUrl").value || "about:blank",
        user_agent: $("accUa").value,
        proxy: "",
        save_session: $("accSaveSession").checked,
      }),
    });
    toast(`Đã thêm profile #${r.index} "${r.name}"`, "success");
  } catch (err) {
    toast("Thêm profile thất bại: " + err.message, "error");
  }
  $("accName").value = "";
  $("accUrl").value = "";
  $("accUa").value = "";
  $("accSaveSession").checked = true;
  refresh();
};

refresh();
connectWs();

function setupUpdater() {
  if (!window.updater) return;
  const banner = $("updateBanner");
  const text = $("updateText");
  const progWrap = $("updateProgressWrap");
  const progBar = $("updateProgressBar");
  const btnInstall = $("btnUpdateInstall");
  const btnDownload = $("btnUpdateDownload");
  const btnDismiss = $("btnUpdateDismiss");

  const show = (stateName, message) => {
    banner.classList.remove("hidden");
    text.textContent = message;
    progWrap.classList.toggle("hidden", stateName !== "downloading");
    btnInstall.classList.toggle("hidden", stateName !== "ready");
    btnDownload.classList.toggle("hidden", stateName !== "available");
    btnDismiss.classList.toggle("hidden", stateName === "up-to-date" || stateName === "error");
  };

  window.updater.onStatus((s) => {
    switch (s.state) {
      case "checking":
        show("checking", "Đang kiểm tra bản cập nhật…");
        break;
      case "available":
        show("available", `Có phiên bản mới v${s.version}!`);
        break;
      case "up-to-date":
        show("up-to-date", "Bạn đang dùng phiên bản mới nhất.");
        setTimeout(() => banner.classList.add("hidden"), 3000);
        break;
      case "downloading":
        progBar.style.width = s.percent + "%";
        show("downloading", `Đang tải bản cập nhật… ${s.percent}%`);
        break;
      case "ready":
        show("ready", "Bản cập nhật đã tải xong.");
        break;
      case "error":
        show("error", "Không thể kiểm tra cập nhật: " + (s.message || "lỗi"));
        break;
    }
  });

  btnDownload.onclick = () => window.updater.downloadUpdate();
  btnInstall.onclick = () => window.updater.installUpdate();
  btnDismiss.onclick = () => banner.classList.add("hidden");
  $("btnCheckUpdate").onclick = () => {
    banner.classList.remove("hidden");
    text.textContent = "Đang kiểm tra bản cập nhật…";
    window.updater.checkForUpdate();
  };

  setTimeout(() => window.updater.checkForUpdate(), 5000);
}

setupUpdater();

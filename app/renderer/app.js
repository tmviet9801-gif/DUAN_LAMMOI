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
  if (state.version) {
    $("brandVersion").textContent = `v${state.version.version}`;
    $("infoVersion").textContent = `${state.version.app} v${state.version.version}`;
  }
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
        ${s.error ? `<div class="err">Lỗi: ${esc(s.error)}</div>` : ""}
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
    if (ev.type === "browser_installing") {
      const pct = ev.percent || 0;
      $("installModal").classList.remove("hidden");
      $("installProgressBar").style.width = pct + "%";
      $("installPercent").textContent = pct + "%";
      return;
    }
    if (ev.type === "browser_installed") {
      $("installModal").classList.add("hidden");
      toast("Trình duyệt đã sẵn sàng", "success");
      return;
    }
    if (ev.type === "browser_install_error") {
      $("installModal").classList.add("hidden");
      toast("Cập nhật trình duyệt thất bại: " + (ev.error || "lỗi"), "error");
      return;
    }
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
  const text = $("updateText");
  const progWrap = $("updateProgressWrap");
  const progBar = $("updateProgressBar");
  const btnInstall = $("btnUpdateInstall");
  const btnDownload = $("btnUpdateDownload");

  const show = (stateName, message, cls) => {
    text.textContent = message;
    text.className = "update-text" + (cls ? " " + cls : "");
    progWrap.classList.toggle("hidden", stateName !== "downloading");
    btnInstall.classList.toggle("hidden", stateName !== "ready");
    btnDownload.classList.toggle("hidden", stateName !== "available");
    if (stateName === "available") {
      btnDownload.textContent = "Cài đặt bản mới";
    }
  };

  window.updater.onStatus((s) => {
    switch (s.state) {
      case "checking":
        show("checking", "Đang kiểm tra cập nhật…");
        break;
      case "available":
        show("available", `Bản mới v${s.version} có sẵn!`, "new-version");
        break;
      case "up-to-date":
        show("up-to-date", "Bạn đang dùng bản mới nhất", "latest");
        break;
      case "downloading":
        progBar.style.width = s.percent + "%";
        show("downloading", `Đang tải… ${s.percent}%`, "downloading");
        break;
      case "ready":
        show("ready", "Đã tải xong bản cập nhật", "new-version");
        btnInstall.textContent = "Cài đặt & khởi động lại";
        break;
      case "error":
        show("error", "");
        break;
    }
  });

  btnDownload.onclick = () => window.updater.downloadUpdate();
  btnInstall.onclick = () => window.updater.installUpdate();
  $("btnCheckUpdate").onclick = () => {
    text.textContent = "Đang kiểm tra cập nhật…";
    text.className = "update-text";
    window.updater.checkForUpdate();
  };

  setTimeout(() => window.updater.checkForUpdate(), 5000);
}

setupUpdater();

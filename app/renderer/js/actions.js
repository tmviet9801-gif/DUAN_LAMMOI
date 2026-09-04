(function () {
  // Actions - sự kiện người dùng: mở tab, thêm/xóa profile, lưu config
  const App = (window.App = window.App || {});
  const $ = App.$;
  const state = App.state;

  // --- Mở các profile đã chọn trong picker ---
  function openSelected() {
    const ids = Array.from(App.selectedProfileIds);
    if (!state.accounts.length) {
      App.toast("Chưa có profile nào. Hãy thêm profile trước khi mở.", "error");
      return;
    }
    if (!ids.length) {
      App.toast("Chưa chọn profile nào — bấm vào ô chọn để đánh dấu", "warn");
      return;
    }
    App.runApi(
      "/api/browser/open",
      { method: "POST", body: JSON.stringify({ account_ids: ids }) },
      `Đang mở ${ids.length} profile…`,
      "Mở profile thất bại"
    );
  }
  if ($("btnOpenSelected")) $("btnOpenSelected").onclick = openSelected;
  if ($("btnOpenChrome")) $("btnOpenChrome").onclick = openSelected;
  App.openSelected = openSelected;

  // --- Xóa các profile đã chọn trong bảng ---
  function deleteSelected() {
    const ids = Array.from(App.selectedProfileIds);
    if (!ids.length) {
      App.toast("Chưa chọn profile nào — click dòng hoặc Ctrl+A để chọn", "warn");
      return;
    }
    App.confirmDialog(
      `Xóa ${ids.length} profile đã chọn?`,
      "Sẽ đóng cửa sổ đang mở (nếu có), gỡ khỏi danh sách VÀ xóa toàn bộ dữ liệu đã lưu (cookies, đăng nhập) của các profile này. Không thể khôi phục!",
      async () => {
        try {
          const r = await App.api("/api/accounts/bulk-delete", {
            method: "POST",
            body: JSON.stringify({ account_ids: ids }),
          });
          App.toast(`Đã xóa ${r.deleted} profile`, "success");
        } catch (err) {
          App.toast("Xóa profile thất bại: " + err.message, "error");
        }
        App.selectedProfileIds.clear();
        App.refresh();
      },
      "Xóa vĩnh viễn"
    );
  }
  $("btnDeleteSelected").onclick = deleteSelected;
  App.deleteSelected = deleteSelected;

  // --- Mở 1 profile (nút Mở trên bảng) ---
  function openAccountRow(a) {
    App.runApi(
      "/api/browser/open",
      { method: "POST", body: JSON.stringify({ account_ids: [a.id] }) },
      `Đang mở "${a.name}"…`,
      "Mở profile thất bại"
    );
  }
  App.openAccountRow = openAccountRow;

  // --- Đóng 1 profile (khi click Đang mở) ---
  function closeAccountRow(a) {
    const session = (App.state.sessions || []).find(
      (s) => s.account && (s.account.id === a.id || s.account.name === a.name)
    );
    if (!session) return;
    App.runApi(
      "/api/browser/close",
      { method: "POST", body: JSON.stringify({ session_ids: [session.session_id] }) },
      `Đang đóng "${a.name}"…`,
      "Đóng profile thất bại"
    );
  }
  App.closeAccountRow = closeAccountRow;

  // --- Lưu session đăng nhập hiện tại (localStorage/sessionStorage) ---
  async function saveAccountSession(a) {
    try {
      const r = await App.api(`/api/accounts/${a.id}/save-session`, { method: "POST" });
      App.toast(`Đã lưu login cho "${a.name}" (local=${r.local}, session=${r.session})`, "success");
    } catch (err) {
      App.toast("Lưu login thất bại: " + err.message, "error");
    }
  }
  App.saveAccountSession = saveAccountSession;

  // --- Xóa 1 profile (nút Xóa trên bảng) ---
  function deleteAccountRow(a) {
    App.confirmDialog(
      `Xóa profile #${a.index} "${a.name}"?`,
      a.save_session
        ? "Profile này có lưu session. Xóa sẽ đóng cửa sổ đang mở (nếu có), gỡ khỏi danh sách VÀ xóa toàn bộ dữ liệu đã lưu (cookies, đăng nhập) của profile này. Không thể khôi phục!"
        : "Xóa sẽ đóng cửa sổ đang mở (nếu có) và gỡ profile khỏi danh sách. Dữ liệu không lưu session nên không có gì trên đĩa để xóa.",
      async () => {
        await App.runApi(
          "/api/accounts/" + a.id,
          { method: "DELETE" },
          `Đã xóa profile #${a.index} "${a.name}"`,
          "Xóa profile thất bại"
        );
        App.refresh();
      },
      "Xóa vĩnh viễn"
    );
  }
  App.deleteAccountRow = deleteAccountRow;

  // --- Xếp lưới ---
  function applyLayout() {
    App.runApi("/api/browser/layout", { method: "POST" }, "Đã xếp lại lưới cửa sổ", "Xếp lưới thất bại");
  }
  if ($("btnLayout")) $("btnLayout").onclick = applyLayout;
  if ($("btnLayout2")) $("btnLayout2").onclick = applyLayout;

  // --- Đóng tất cả / Đóng Chrome đã chọn ---
  function closeAllBrowsers() {
    if (!state.sessions.length) {
      App.toast("Không có cửa sổ nào đang mở", "warn");
      return;
    }
    App.confirmDialog(
      "Đóng tất cả cửa sổ?",
      `Có ${state.sessions.length} cửa sổ đang mở. Nếu profile có lưu session, đăng nhập vẫn được giữ lại và lần sau mở lại không cần login.`,
      () => App.runApi("/api/browser/close", { method: "POST", body: JSON.stringify({}) }, "Đã đóng tất cả cửa sổ", "Đóng cửa sổ thất bại"),
      "Đóng tất cả"
    );
  }
  if ($("btnCloseAll")) $("btnCloseAll").onclick = closeAllBrowsers;
  if ($("btnCloseChrome")) {
    $("btnCloseChrome").onclick = () => {
      const ids = Array.from(App.selectedProfileIds);
      if (ids.length > 0) {
        const sessionIds = (App.state.sessions || [])
          .filter((s) => s.account && ids.includes(s.account.id))
          .map((s) => s.session_id);
        if (sessionIds.length > 0) {
          App.runApi(
            "/api/browser/close",
            { method: "POST", body: JSON.stringify({ session_ids: sessionIds }) },
            `Đang đóng ${sessionIds.length} cửa sổ đã chọn…`,
            "Đóng thất bại"
          );
          return;
        }
      }
      closeAllBrowsers();
    };
  }

  // --- URL mặc định cho profile (từ cấu hình, fallback hardcode) ---
  function defaultUrl() {
    return (state.config && state.config.default_url) || "https://v.hitclub.latino/?a=hitclub";
  }

  // --- Lưu cấu hình ---
  async function saveConfig() {
    try {
      await App.api("/api/config", {
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
            locale: $("cfgLocale").value,
          },
          default_count: +$("cfgCount").value,
          auto_layout: $("cfgAutoLayout").checked,
          mute_all_sites: $("cfgMuteAll").checked,
          default_url: $("cfgDefaultUrl").value.trim(),
        }),
      });
      App.toast("Đã lưu cấu hình", "success");
      App.refresh();
    } catch (e) {
      App.toast("Lưu cấu hình thất bại: " + e.message, "error");
    }
  }
  $("btnSaveConfig").onclick = saveConfig;

  // Mute/unmute áp dụng NGAY khi tick/bỏ tick (không cần bấm Lưu).
  $("cfgMuteAll").addEventListener("change", async () => {
    const muted = $("cfgMuteAll").checked;
    try {
      await App.api("/api/config", {
        method: "POST",
        body: JSON.stringify({ mute_all_sites: muted }),
      });
      App.toast(muted ? "Đã tắt âm thanh các tab" : "Đã bật lại âm thanh", "success");
      App.refresh();
    } catch (e) {
      App.toast("Cập nhật âm thanh thất bại: " + e.message, "error");
    }
  });

  // --- Modal thêm profile (tab: Thêm 1 / Thêm nhanh) ---
  const apModal = $("addProfileModal");
  let addMode = "single";

  function setAddMode(mode) {
    addMode = mode;
    document.querySelectorAll(".mtab").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === mode)
    );
    $("apCountField").classList.toggle("hidden", mode === "single");
    $("apNameLabel").textContent = mode === "single" ? "Tên" : "Tiền tố tên";
    $("addProfileTitle").textContent =
      mode === "single" ? "Thêm profile" : "Thêm nhanh profile";
    $("apProxyResult").textContent =
      mode === "single"
        ? "Định dạng IP:Port:User:Pass. Để trống = dùng IP máy."
        : "Định dạng IP:Port:User:Pass. Khi thêm nhanh, mỗi dòng là proxy cho 1 profile (thiếu sẽ dùng lại từ đầu).";
    updateAddPreview();
  }

  document.querySelectorAll(".mtab").forEach((btn) => {
    btn.onclick = () => setAddMode(btn.dataset.mode);
  });

  function closeAddProfile() {
    apModal.classList.add("hidden");
    $("apName").value = "";
    $("apCount").value = "1";
    $("apUrl").value = "";
    $("apProxy").value = "";
  }

  function openAddProfile() {
    setAddMode("single");
    $("apName").value = "";
    $("apCount").value = "1";
    $("apUrl").value = "";
    $("apProxy").value = "";
    apModal.classList.remove("hidden");
    $("apName").focus();
  }

  function updateAddPreview() {
    const prefix = $("apName").value.trim();
    if (!prefix) {
      $("apPreview").textContent = "Nhập tên để xem trước…";
      return;
    }
    if (addMode === "single") {
      $("apPreview").textContent = `Sẽ thêm: ${prefix}`;
      return;
    }
    const count = Math.max(1, parseInt($("apCount").value, 10) || 1);
    const width = Math.max(2, String(count).length);
    const names = [];
    const total = Math.min(count, 3);
    for (let i = 1; i <= total; i++) names.push(`${prefix}${String(i).padStart(width, "0")}`);
    const suffix = count > 3 ? ` … ${prefix}${String(count).padStart(width, "0")}` : "";
    $("apPreview").textContent = `Sẽ thêm: ${names.join(", ")}${suffix} (${count} profile)`;
  }

  if ($("apName")) $("apName").addEventListener("input", updateAddPreview);
  if ($("apCount")) $("apCount").addEventListener("input", updateAddPreview);
  if ($("apCancel")) $("apCancel").onclick = closeAddProfile;
  if (apModal) {
    apModal.onclick = (e) => {
      if (e.target === apModal) closeAddProfile();
    };
  }

  if ($("apSubmit")) {
    $("apSubmit").onclick = async () => {
      const prefix = $("apName").value.trim();
      if (!prefix) {
        App.toast("Nhập tên / tiền tố profile", "warn");
        return;
      }
      const url = $("apUrl").value.trim() || defaultUrl();
      const proxy = $("apProxy").value.trim();
      const btn = $("apSubmit");
      btn.disabled = true;
      try {
        if (addMode === "single") {
          const r = await App.api("/api/accounts", {
            method: "POST",
            body: JSON.stringify({ name: prefix, url, proxy, save_session: true }),
          });
          App.toast(`Đã thêm profile #${r.index} "${r.name}"`, "success");
        } else {
          const count = Math.max(1, parseInt($("apCount").value, 10) || 1);
          const r = await App.api("/api/accounts/bulk", {
            method: "POST",
            body: JSON.stringify({ prefix, count, url, proxy, save_session: true }),
          });
          App.toast(`Đã thêm ${r.count} profile (${r.accounts[0].name} → ${r.accounts[r.accounts.length - 1].name})`, "success");
        }
        closeAddProfile();
        App.refresh();
      } catch (err) {
        App.toast("Thêm profile thất bại: " + err.message, "error");
      } finally {
        btn.disabled = false;
      }
    };
  }

  if ($("btnAddProfile")) $("btnAddProfile").onclick = openAddProfile;
  App.openAddProfile = openAddProfile;

  // --- Kiểm tra proxy (nút Kiểm tra trong dialog) ---
  async function checkProxy(proxyInput, resultEl) {
    const proxy = proxyInput.value.trim();
    if (!proxy) {
      resultEl.textContent = "Nhập proxy trước khi kiểm tra";
      resultEl.className = "hint";
      return;
    }
    resultEl.textContent = "Đang kiểm tra…";
    resultEl.className = "hint";
    try {
      const r = await App.api("/api/check-proxy", {
        method: "POST",
        body: JSON.stringify({ proxy }),
      });
      if (r.ok) {
        resultEl.textContent = `✓ Hoạt động — IP: ${r.ip} (${r.latency_ms}ms)`;
        resultEl.className = "hint success";
      } else {
        resultEl.textContent = `✗ Không hoạt động: ${r.error}`;
        resultEl.className = "hint error";
      }
    } catch (e) {
      resultEl.textContent = `✗ Lỗi: ${e.message}`;
      resultEl.className = "hint error";
    }
  }
  if ($("apCheckProxy")) $("apCheckProxy").onclick = () => checkProxy($("apProxy"), $("apProxyResult"));

  // --- Sửa profile (tên, Username, Mật khẩu, URL, UA, proxy) ---
  let editingAccount = null;
  const epModal = $("editProfileModal");

  const SAMPLE_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.205 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  ];

  function openEditProfile(a) {
    if (!a) return;
    editingAccount = a;
    const idx = a.index !== undefined ? a.index : "";
    if ($("epName")) $("epName").textContent = idx ? `#${idx} ${a.name}` : (a.name || "");
    if ($("epProfileName")) $("epProfileName").value = a.name || "";
    if ($("epUsername")) $("epUsername").value = a.username || "";
    if ($("epPassword")) $("epPassword").value = a.password || "";
    if ($("epUrl")) $("epUrl").value = a.url || "";
    if ($("epProxy")) $("epProxy").value = a.proxy || "";
    if ($("epUserAgent")) $("epUserAgent").value = a.user_agent || "";
    if ($("epProxyResult")) {
      $("epProxyResult").textContent = "Định dạng IP:Port:User:Pass. Để trống = dùng IP máy.";
      $("epProxyResult").className = "hint";
    }
    epModal.classList.remove("hidden");
    if ($("epProfileName")) $("epProfileName").focus();
  }
  App.openEditProfile = openEditProfile;

  if ($("epRandomUa")) {
    $("epRandomUa").onclick = () => {
      const ua = SAMPLE_USER_AGENTS[Math.floor(Math.random() * SAMPLE_USER_AGENTS.length)];
      if ($("epUserAgent")) $("epUserAgent").value = ua;
      App.toast("Đã đổi User-Agent ngẫu nhiên", "info");
    };
  }

  function closeEditProfile() {
    epModal.classList.add("hidden");
    editingAccount = null;
  }
  if ($("epCancel")) $("epCancel").onclick = closeEditProfile;
  epModal.onclick = (e) => {
    if (e.target === epModal) closeEditProfile();
  };
  if ($("epCheckProxy")) $("epCheckProxy").onclick = () => checkProxy($("epProxy"), $("epProxyResult"));
  if ($("epSave")) {
    $("epSave").onclick = async () => {
      if (!editingAccount) return;
      const btn = $("epSave");
      btn.disabled = true;
      try {
        const payload = {
          name: $("epProfileName") ? $("epProfileName").value.trim() : editingAccount.name,
          username: $("epUsername") ? $("epUsername").value.trim() : "",
          password: $("epPassword") ? $("epPassword").value.trim() : "",
          url: $("epUrl") ? ($("epUrl").value.trim() || defaultUrl()) : defaultUrl(),
          proxy: $("epProxy") ? $("epProxy").value.trim() : "",
          user_agent: $("epUserAgent") ? $("epUserAgent").value.trim() : "",
        };
        const r = await App.api("/api/accounts/" + editingAccount.id, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        App.toast(`Đã cập nhật thông tin tài khoản "${r.name}"!`, "success");
        closeEditProfile();
        App.refresh();
      } catch (err) {
        App.toast("Cập nhật thông tin thất bại: " + err.message, "error");
      } finally {
        btn.disabled = false;
      }
    };
  }

  // Nút Sửa trên Toolbar
  if ($("btnEditSelected")) {
    $("btnEditSelected").onclick = () => {
      const ids = Array.from(App.selectedProfileIds);
      if (!ids.length) {
        App.toast("Vui lòng chọn 1 tài khoản trong bảng để sửa!", "warn");
        return;
      }
      const acc = (App.state.accounts || []).find((a) => a.id === ids[0]);
      if (acc) {
        openEditProfile(acc);
      } else {
        App.toast("Không tìm thấy thông tin tài khoản đã chọn!", "error");
      }
    };
  }

  // =========================================================================
  // ALL-IN-ONE PRO DASHBOARD ACTIONS
  // =========================================================================

  // 1. Thêm nhanh danh sách tài khoản từ textarea
  if ($("btnQuickAddAccounts")) {
    $("btnQuickAddAccounts").onclick = async () => {
      const raw = $("txtQuickAccounts") ? $("txtQuickAccounts").value.trim() : "";
      if (!raw) {
        App.toast("Vui lòng nhập danh sách tài khoản (mỗi dòng: username|pass hoặc username|pass|proxy)!", "warn");
        return;
      }
      try {
        const r = await App.api("/api/accounts/import", {
          method: "POST",
          body: JSON.stringify({ raw_text: raw }),
        });
        App.toast(`Đã thêm thành công ${r.imported || 0} tài khoản!`, "success");
        if ($("txtQuickAccounts")) $("txtQuickAccounts").value = "";
        App.refresh();
      } catch (err) {
        App.toast("Thêm tài khoản lỗi: " + err.message, "error");
      }
    };
  }

  // 2. Lấy mã máy (Machine / Device ID) & Copy
  function getMachineGuid() {
    let guid = localStorage.getItem("app_device_id");
    if (!guid) {
      guid = (crypto.randomUUID ? crypto.randomUUID() : (Math.random().toString(36).substring(2) + Date.now().toString(36))).toUpperCase();
      localStorage.setItem("app_device_id", guid);
    }
    return guid;
  }

  if ($("txtDeviceId") && !$("txtDeviceId").value) {
    $("txtDeviceId").value = getMachineGuid();
  }

  if ($("btnGetDeviceId")) {
    $("btnGetDeviceId").onclick = () => {
      const id = getMachineGuid();
      if ($("txtDeviceId")) $("txtDeviceId").value = id;
      navigator.clipboard?.writeText(id).catch(() => {});
      App.toast(`Mã máy: ${id} (đã copy vào clipboard)`, "success");
    };
  }

  if ($("btnCopyDeviceId")) {
    $("btnCopyDeviceId").onclick = () => {
      const id = $("txtDeviceId") ? $("txtDeviceId").value || getMachineGuid() : getMachineGuid();
      if ($("txtDeviceId")) $("txtDeviceId").value = id;
      navigator.clipboard?.writeText(id).catch(() => {});
      App.toast(`Đã copy mã máy: ${id}`, "success");
    };
  }

  // 3. Game Control actions (Tạo phòng, Tìm ID, Thoát hết, Dừng)
  if ($("btnGcCreateRoom")) {
    $("btnGcCreateRoom").onclick = async () => {
      const game = $("gcGameSelect") ? $("gcGameSelect").value : "TLDL";
      const bet = $("gcBetSelect") ? $("gcBetSelect").value : "100";
      const slot = $("gcSlotCount") ? $("gcSlotCount").value : "2";
      const pwd = $("gcRoomCode") ? $("gcRoomCode").value : "2222";

      const selected = Array.from(document.querySelectorAll("#accTbody tr.selected"));
      const mainProfile = $("gcProfileMain") ? $("gcProfileMain").value : "";
      const profile_name = (selected.length > 0 ? selected[0].dataset.name : "") || mainProfile || (App.profiles && App.profiles[0] ? App.profiles[0].name : "Account 1");

      App.toast(`Đang tạo bàn ${game} cược ${bet} (Bàn ${slot} người, Pass: ${pwd}) cho ${profile_name}...`, "info");
      try {
        const res = await App.api("/api/autoplay/create-table", {
          method: "POST",
          body: JSON.stringify({
            profile_name,
            game,
            bet: Number(bet),
            mu: Number(slot),
            pwd: String(pwd)
          }),
        });
        const room_id = res.room_id || bet;
        if ($("gcTargetRoomId")) $("gcTargetRoomId").value = room_id;
        App.toast(`✅ Tạo/vào bàn thành công: Phòng #${room_id} (Cược ${bet})!`, "success");

        // Cập nhật tức thì dòng tài khoản trên bảng
        const row = document.querySelector(`#accTbody tr[data-name="${profile_name}"]`);
        if (row) {
          const tdRoom = row.querySelector(".td-room");
          if (tdRoom) tdRoom.textContent = room_id;
          const tdLog = row.querySelector(".td-log");
          if (tdLog) tdLog.textContent = `Bàn #${room_id} (${bet})`;
        }
        if (window.App && window.App.refreshAccounts) window.App.refreshAccounts();
      } catch (err) {
        App.toast("Tạo phòng lỗi: " + err.message, "error");
      }
    };
  }

  if ($("btnGcFindId")) {
    $("btnGcFindId").onclick = async () => {
      const rid = $("gcTargetRoomId") ? $("gcTargetRoomId").value.trim() : "";
      if (!rid) {
        App.toast("Vui lòng nhập ID phòng cần tìm!", "warn");
        return;
      }
      App.toast(`Đang tìm và vào phòng ${rid}...`, "info");
      try {
        await App.api("/api/autoplay/join-rid", {
          method: "POST",
          body: JSON.stringify({ room_id: rid }),
        });
        App.toast(`Đã gửi lệnh vào phòng ${rid}!`, "success");
      } catch (err) {
        App.toast("Vào phòng lỗi: " + err.message, "error");
      }
    };
  }

  if ($("btnGcLeaveAll")) {
    $("btnGcLeaveAll").onclick = async () => {
      App.toast("Đang gửi lệnh thoát tất cả phòng ra sảnh...", "info");
      try {
        const res = await App.api("/api/autoplay/leave-all", { method: "POST", body: "{}" });
        // Cập nhật giao diện tức thì trên bảng danh sách tài khoản
        document.querySelectorAll("#accTbody tr").forEach(row => {
          const tdRoom = row.querySelector(".td-room");
          if (tdRoom) tdRoom.textContent = "-";
          const tdLog = row.querySelector(".td-log");
          if (tdLog) tdLog.textContent = "Đã thoát phòng";
        });
        if (window.App && window.App.refreshAccounts) window.App.refreshAccounts();
        App.toast(res.detail || "Đã thoát tất cả phòng về sảnh thành công!", "success");
      } catch (err) {
        App.toast("Thoát phòng lỗi: " + err.message, "error");
      }
    };
  }

  if ($("btnGcStop") || $("btnGcStopLeave")) {
    const handleStop = async () => {
      App.toast("Đang dừng toàn bộ auto...", "warn");
      try {
        await App.api("/api/autoplay/stop", { method: "POST", body: "{}" });
        App.toast("Đã dừng auto!", "success");
      } catch (err) {
        App.toast("Dừng lỗi: " + err.message, "error");
      }
    };
    if ($("btnGcStop")) $("btnGcStop").onclick = handleStop;
    if ($("btnGcStopLeave")) $("btnGcStopLeave").onclick = handleStop;
  }

  if ($("btnGcRandomJoin")) {
    $("btnGcRandomJoin").onclick = async () => {
      const game = $("gcGameSelect") ? $("gcGameSelect").value : "TLDL";
      const bet = $("gcBetSelect") ? $("gcBetSelect").value : "100";
      const slot = $("gcSlotCount") ? $("gcSlotCount").value : "2";
      const selected = Array.from(document.querySelectorAll("#accTbody tr.selected"));
      const mainProfile = $("gcProfileMain") ? $("gcProfileMain").value : "";
      const profile_name = (selected.length > 0 ? selected[0].dataset.name : "") || mainProfile || (App.profiles && App.profiles[0] ? App.profiles[0].name : "Account 1");

      App.toast(`Random vào phòng ${game} cược ${bet} cho ${profile_name}...`, "info");
      try {
        await App.api("/api/autoplay/join-quick", {
          method: "POST",
          body: JSON.stringify({
            profile_name,
            game,
            bet: Number(bet),
            mu: Number(slot)
          }),
        });
        App.toast("Đã gửi lệnh random vào phòng!", "success");
      } catch (err) {
        App.toast("Vào phòng lỗi: " + err.message, "error");
      }
    };
  }

  // 4. Middle Toolbar Actions
  if ($("btnRefreshList")) {
    $("btnRefreshList").onclick = () => {
      App.refresh();
      App.toast("Đã làm mới danh sách tài khoản", "info");
    };
  }

  if ($("btnSaveAll")) {
    $("btnSaveAll").onclick = async () => {
      App.toast("Đang lưu cài đặt...", "info");
      try {
        await App.api("/api/config", {
          method: "POST",
          body: JSON.stringify(App.state.config || {}),
        });
        App.toast("Đã lưu cài đặt thành công!", "success");
      } catch (err) {
        App.toast("Lưu lỗi: " + err.message, "error");
      }
    };
  }

  if ($("btnReconnect")) {
    $("btnReconnect").onclick = async () => {
      App.toast("Đang kết nối lại WS cho các profiles...", "info");
      try {
        await App.api("/api/autoplay/reconnect-ws", { method: "POST", body: "{}" });
        App.toast("Đã gửi yêu cầu kết nối lại WS", "success");
      } catch (err) {
        App.toast("Kết nối lại WS lỗi: " + err.message, "error");
      }
    };
  }

  if ($("btnModePhom")) {
    $("btnModePhom").onclick = () => {
      if ($("gcGameSelect")) $("gcGameSelect").value = "PHOM";
      App.toast("Đã chuyển chế độ sang PHOM", "info");
    };
  }

  if ($("btnModeMauBinh")) {
    $("btnModeMauBinh").onclick = () => {
      if ($("gcGameSelect")) $("gcGameSelect").value = "MAUBINH";
      App.toast("Đã chuyển chế độ sang MAUBINH", "info");
    };
  }
})();
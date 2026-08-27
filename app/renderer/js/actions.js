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
  $("btnOpenSelected").onclick = openSelected;
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
  $("btnLayout").onclick = applyLayout;
  $("btnLayout2").onclick = applyLayout;

  // --- Đóng tất cả ---
  $("btnCloseAll").onclick = () => {
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
  };

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
            os: $("cfgOs").value,
            locale: $("cfgLocale").value,
          },
          default_count: +$("cfgCount").value,
          auto_layout: $("cfgAutoLayout").checked,
          mute_all_sites: $("cfgMuteAll").checked,
        }),
      });
      App.toast("Đã lưu cấu hình", "success");
      App.refresh();
    } catch (e) {
      App.toast("Lưu cấu hình thất bại: " + e.message, "error");
    }
  }
  $("btnSaveConfig").onclick = saveConfig;

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
    $("apUa").value = "";
    $("apProxy").value = "";
    $("apSaveSession").checked = true;
  }

  function openAddProfile() {
    setAddMode("single");
    $("apName").value = "";
    $("apCount").value = "1";
    $("apUrl").value = "";
    $("apUa").value = "";
    $("apProxy").value = "";
    $("apSaveSession").checked = true;
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

  $("apName").addEventListener("input", updateAddPreview);
  $("apCount").addEventListener("input", updateAddPreview);
  $("apCancel").onclick = closeAddProfile;
  apModal.onclick = (e) => {
    if (e.target === apModal) closeAddProfile();
  };

  $("apSubmit").onclick = async () => {
    const prefix = $("apName").value.trim();
    if (!prefix) {
      App.toast("Nhập tên / tiền tố profile", "warn");
      return;
    }
    const url = $("apUrl").value.trim() || "https://v.hitclub.latino/?a=hitclub";
    const userAgent = $("apUa").value.trim();
    const proxy = $("apProxy").value.trim();
    const saveSession = $("apSaveSession").checked;
    const btn = $("apSubmit");
    btn.disabled = true;
    try {
      if (addMode === "single") {
        const r = await App.api("/api/accounts", {
          method: "POST",
          body: JSON.stringify({ name: prefix, url, user_agent: userAgent, proxy, save_session: saveSession }),
        });
        App.toast(`Đã thêm profile #${r.index} "${r.name}"`, "success");
      } else {
        const count = Math.max(1, parseInt($("apCount").value, 10) || 1);
        const r = await App.api("/api/accounts/bulk", {
          method: "POST",
          body: JSON.stringify({ prefix, count, url, user_agent: userAgent, proxy, save_session: saveSession }),
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

  $("btnAddProfile").onclick = openAddProfile;
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
  $("apCheckProxy").onclick = () => checkProxy($("apProxy"), $("apProxyResult"));

  // --- Sửa profile (tên, URL, UA, proxy) ---
  let editingAccount = null;
  const epModal = $("editProfileModal");

  function openEditProfile(a) {
    editingAccount = a;
    $("epName").textContent = `#${a.index} ${a.name}`;
    $("epProfileName").value = a.name || "";
    $("epUrl").value = a.url || "";
    $("epUa").value = a.user_agent || a.profile_ua || "";
    $("epProxy").value = a.proxy || "";
    $("epProxyResult").textContent = "Định dạng IP:Port:User:Pass. Để trống = dùng IP máy.";
    $("epProxyResult").className = "hint";
    epModal.classList.remove("hidden");
    $("epProfileName").focus();
  }
  App.openEditProfile = openEditProfile;

  function closeEditProfile() {
    epModal.classList.add("hidden");
    editingAccount = null;
  }
  $("epCancel").onclick = closeEditProfile;
  epModal.onclick = (e) => {
    if (e.target === epModal) closeEditProfile();
  };
  $("epCheckProxy").onclick = () => checkProxy($("epProxy"), $("epProxyResult"));
  $("epSave").onclick = async () => {
    if (!editingAccount) return;
    const btn = $("epSave");
    btn.disabled = true;
    try {
      const r = await App.api("/api/accounts/" + editingAccount.id, {
        method: "PATCH",
        body: JSON.stringify({
          name: $("epProfileName").value.trim(),
          url: $("epUrl").value.trim() || "https://v.hitclub.latino/?a=hitclub",
          user_agent: $("epUa").value.trim(),
          proxy: $("epProxy").value.trim(),
        }),
      });
      App.toast(`Đã cập nhật profile "${r.name}"`, "success");
      closeEditProfile();
      App.refresh();
    } catch (err) {
      App.toast("Cập nhật profile thất bại: " + err.message, "error");
    } finally {
      btn.disabled = false;
    }
  };
})();
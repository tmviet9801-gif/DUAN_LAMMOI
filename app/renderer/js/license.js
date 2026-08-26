(function () {
  // License gate — chặn app nếu chưa kích hoạt / hết hạn
  const App = (window.App = window.App || {});
  const $ = App.$;
  let status = { activated: false, valid: false };

  async function refresh() {
    try {
      status = await App.api("/api/license/status");
    } catch (_) {
      status = { activated: false, valid: false };
    }
    App.licenseStatus = status;
    const gate = $("licenseGate");
    if (status.valid) {
      if (gate) gate.classList.add("hidden");
      const left = $("footerLeft");
      if (left) left.textContent = `${App.platformName || "AutoTool"} — ${status.max_tabs} tab`;
    } else {
      if (gate) {
        gate.classList.remove("hidden");
        $("licMachine").textContent = `Máy: ${status.machine_id || "…"}`;
        $("licMsg").textContent = status.activated
          ? "Giấy phép đã hết hạn hoặc không khớp máy. Nhập key mới."
          : "Nhập license key để sử dụng.";
      }
    }
    return status;
  }

  async function activate() {
    const key = $("licKey").value.trim();
    if (!key) {
      $("licMsg").textContent = "Nhập license key";
      return;
    }
    $("licMsg").textContent = "Đang kích hoạt…";
    try {
      const r = await App.api("/api/license/activate", { method: "POST", body: JSON.stringify({ key }) });
      $("licMsg").textContent = "✓ Đã kích hoạt";
      await refresh();
      App.toast("Đã kích hoạt giấy phép", "success");
    } catch (e) {
      $("licMsg").textContent = "✗ " + e.message;
    }
  }

  $("licActivate").onclick = activate;
  App.licenseRefresh = refresh;
  refresh();

  // hiển thị tên platform
  App.api("/api/platform").then((p) => { App.platformName = p.name || "AutoTool"; }).catch(() => {});
})();
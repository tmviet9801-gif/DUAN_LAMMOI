(function () {
  // License gate — chặn app nếu chưa kích hoạt / hết hạn
  // + Owner panel: sinh license cho khách
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

  App.api("/api/platform").then((p) => { App.platformName = p.name || "AutoTool"; }).catch(() => {});

  // ---- Owner panel: sinh license ----
  function openMakeLicense() {
    $("makeLicenseModal").classList.remove("hidden");
    $("mkResult").textContent = "";
    $("mkKeyResult").style.display = "none";
    $("mkOwnerToken").value = "";
    $("mkMachineId").value = "";
    $("mkDays").value = "30";
    $("mkTabs").value = "10";
    $("mkOwnerToken").focus();
  }

  function closeMakeLicense() {
    $("makeLicenseModal").classList.add("hidden");
  }

  $("mkCancel").onclick = closeMakeLicense;
  $("makeLicenseModal").onclick = (e) => {
    if (e.target === $("makeLicenseModal")) closeMakeLicense();
  };

  $("mkGenerate").onclick = async () => {
    const token = $("mkOwnerToken").value.trim();
    const machineId = $("mkMachineId").value.trim();
    const days = parseInt($("mkDays").value, 10) || 30;
    const tabs = parseInt($("mkTabs").value, 10) || 10;
    if (!token) {
      $("mkResult").textContent = "Nhập token chủ sở hữu";
      return;
    }
    if (!machineId) {
      $("mkResult").textContent = "Nhập mã máy khách";
      return;
    }
    $("mkResult").textContent = "Đang sinh…";
    $("mkKeyResult").style.display = "none";
    try {
      const r = await App.api("/api/license/make", {
        method: "POST",
        body: JSON.stringify({ owner_token: token, machine_id: machineId, days, max_tabs: tabs }),
      });
      $("mkKey").textContent = r.key;
      $("mkResult").textContent = `✓ Key cho máy ${r.machine_id.slice(0, 12)}… — ${r.days} ngày, ${r.max_tabs} tab`;
      $("mkResult").className = "hint success";
      $("mkKeyResult").style.display = "block";
      $("mkCopy").onclick = () => {
        navigator.clipboard.writeText(r.key).then(() => App.toast("Đã copy key", "success")).catch(() => {});
      };
    } catch (e) {
      $("mkResult").textContent = "✗ " + e.message;
      $("mkResult").className = "hint error";
    }
  };

  App.openMakeLicense = openMakeLicense;
})();
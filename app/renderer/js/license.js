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
    // CẬP NHẬT TAB CẤU HÌNH (PANEL BẢN QUYỀN & GIẤY PHÉP)
    renderConfigLicense(status);

    return status;
  }

  function renderConfigLicense(st) {
    const inputMachine = $("cfgMachineId");
    const inputKey = $("cfgLicenseKey");
    const badge = $("cfgLicBadge");
    const expiry = $("cfgLicExpiry");
    const tabs = $("cfgLicTabs");

    if (inputMachine) inputMachine.value = st.machine_id || "";
    if (inputKey) {
      if (document.activeElement !== inputKey) {
        inputKey.value = st.key || "";
      }
    }

    if (badge) {
      if (st.valid) {
        badge.textContent = "✓ Đang hoạt động";
        badge.style.color = "var(--ok, #22c55e)";
        badge.style.borderColor = "var(--ok, #22c55e)";
      } else if (st.activated) {
        badge.textContent = "✗ Hết hạn hoặc sai máy";
        badge.style.color = "var(--danger, #ef4444)";
        badge.style.borderColor = "var(--danger, #ef4444)";
      } else {
        badge.textContent = "○ Chưa kích hoạt key";
        badge.style.color = "var(--warn, #f59e0b)";
        badge.style.borderColor = "var(--warn, #f59e0b)";
      }
    }

    if (expiry) {
      if (st.expires_at) {
        const expDate = new Date(st.expires_at * 1000);
        const daysLeft = Math.max(0, Math.ceil((st.expires_at - Date.now() / 1000) / 86400));
        expiry.textContent = `Hạn dùng: ${expDate.toLocaleDateString("vi-VN")} (${daysLeft} ngày còn lại)`;
      } else {
        expiry.textContent = "Hạn dùng: Chưa có license";
      }
    }

    if (tabs) {
      tabs.textContent = `${st.max_tabs || 0} tab tối đa`;
    }
  }

  async function activate(customKey) {
    const key = (customKey || $("licKey").value || "").trim();
    if (!key) {
      if ($("licMsg")) $("licMsg").textContent = "Nhập license key";
      App.toast("Vui lòng nhập license key", "error");
      return;
    }
    if ($("licMsg")) $("licMsg").textContent = "Đang kích hoạt…";
    try {
      const r = await App.api("/api/license/activate", { method: "POST", body: JSON.stringify({ key }) });
      if ($("licMsg")) $("licMsg").textContent = "✓ Đã kích hoạt";
      await refresh();
      App.toast("✓ Đã kích hoạt giấy phép thành công!", "success");
    } catch (e) {
      if ($("licMsg")) $("licMsg").textContent = "✗ " + e.message;
      App.toast("Kích hoạt thất bại: " + e.message, "error");
    }
  }

  if ($("licActivate")) $("licActivate").onclick = () => activate();

  // NÚT LƯU / KÍCH HOẠT TRONG TAB CẤU HÌNH
  if ($("btnSaveLicenseKey")) {
    $("btnSaveLicenseKey").onclick = () => {
      const key = ($("cfgLicenseKey").value || "").trim();
      activate(key);
    };
  }

  // NÚT REFRESH KEY (XÓA KEY VÀ BẮT BUỘC NHẬP KEY MỚI)
  if ($("btnRefreshLicenseKey")) {
    $("btnRefreshLicenseKey").onclick = async () => {
      const confirmed = confirm("Bạn có chắc chắn muốn REFRESH (XÓA) license key hiện tại không?\n\nỨng dụng sẽ xóa key này khỏi máy và hiển thị màn hình yêu cầu nhập key mới.");
      if (!confirmed) return;
      try {
        await App.api("/api/license/deactivate", { method: "POST" });
        if ($("cfgLicenseKey")) $("cfgLicenseKey").value = "";
        if ($("licKey")) $("licKey").value = "";
        App.toast("Đã refresh key (xóa key)! Vui lòng nhập license key mới.", "warn");
        await refresh();
      } catch (e) {
        App.toast("Lỗi khi refresh key: " + e.message, "error");
      }
    };
  }

  // NÚT COPY MÃ MÁY TRONG TAB CẤU HÌNH
  if ($("btnCopyMachineId")) {
    $("btnCopyMachineId").onclick = () => {
      const mid = ($("cfgMachineId").value || "").trim();
      if (!mid) return;
      navigator.clipboard.writeText(mid).then(() => {
        App.toast("Đã sao chép mã máy (Device ID)!", "success");
      }).catch(() => {
        App.toast("Không thể copy tự động, vui lòng bôi đen và copy", "warn");
      });
    };
  }

  // Phím Enter trên ô nhập key
  if ($("cfgLicenseKey")) {
    $("cfgLicenseKey").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        if ($("btnSaveLicenseKey")) $("btnSaveLicenseKey").click();
      }
    });
  }

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
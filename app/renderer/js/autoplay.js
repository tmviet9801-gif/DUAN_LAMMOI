(function () {
  // Auto gom bàn & xả bài — Quản lý Profile Chính (A) & Profile Phụ (B) đồng bộ
  const App = (window.App = window.App || {});
  const $ = App.$;

  function populateSelect(selectEl, accounts, defaultIndex) {
    if (!selectEl) return;
    const prev = selectEl.value;
    selectEl.innerHTML = "";
    if (!accounts.length) {
      selectEl.innerHTML = '<option value="">-- Chưa có nick --</option>';
      return;
    }
    accounts.forEach((a, idx) => {
      const name = a.name || a.username;
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = `${name} (${a.username || "Chưa login"})`;
      if (prev ? prev === name : idx === defaultIndex) opt.selected = true;
      selectEl.appendChild(opt);
    });
  }

  function renderProfiles() {
    const accs = App.state.accounts || [];
    const gameAccs = accs.filter((a) => a.username || a.name);

    // Old gamesim dropdowns (if existing)
    populateSelect($("afProfileMain"), gameAccs, 0);
    populateSelect($("afProfileSub"), gameAccs, gameAccs.length > 1 ? 1 : 0);

    // New Dashboard dropdowns
    populateSelect($("gcProfileMain"), gameAccs, 0);
    populateSelect($("gcProfileSub"), gameAccs, gameAccs.length > 1 ? 1 : 0);
  }

  function setStatus(text, type = "info") {
    // 1. Status trong view-gamesim cũ
    const box = $("afStatusBox");
    const label = $("afStatus");
    if (box && label) {
      box.style.display = "block";
      label.textContent = text;
      if (type === "success") {
        box.style.background = "rgba(46, 204, 113, 0.15)";
        box.style.borderColor = "rgba(46, 204, 113, 0.4)";
        label.style.color = "#2ecc71";
      } else if (type === "error") {
        box.style.background = "rgba(231, 76, 60, 0.15)";
        box.style.borderColor = "rgba(231, 76, 60, 0.4)";
        label.style.color = "#e74c3c";
      } else {
        box.style.background = "rgba(245, 176, 65, 0.15)";
        box.style.borderColor = "rgba(245, 176, 65, 0.4)";
        label.style.color = "#f5b041";
      }
    }

    // 2. Status trong All-in-One Dashboard mới
    const gcBox = $("gcSyncStatusBox");
    const gcText = $("gcSyncStatusText");
    const gcIcon = $("gcSyncStatusIcon");
    if (gcBox && gcText) {
      gcBox.classList.remove("hidden", "success", "error");
      gcText.textContent = text;
      if (type === "success") {
        gcBox.classList.add("success");
        if (gcIcon) gcIcon.textContent = "✅";
      } else if (type === "error") {
        gcBox.classList.add("error");
        if (gcIcon) gcIcon.textContent = "❌";
      } else {
        if (gcIcon) gcIcon.textContent = "⏳";
      }
    }
  }

  async function start(isFromDashboard = false) {
    // 1. Thu thập danh sách tài khoản được chọn (hỗ trợ tick 2-5 tài khoản trên bảng danh sách)
    const selectedRows = Array.from(document.querySelectorAll("#accTbody tr.selected"));
    let selectedProfiles = selectedRows.map(r => r.dataset.name).filter(Boolean);

    const mainSelect = isFromDashboard ? $("gcProfileMain") : ($("afProfileMain") || $("gcProfileMain"));
    const subSelect = isFromDashboard ? $("gcProfileSub") : ($("afProfileSub") || $("gcProfileSub"));

    const mainName = mainSelect ? mainSelect.value : "";
    const subName = subSelect ? subSelect.value : "";

    // Nếu trên bảng chưa tick chọn đủ 2 tài khoản -> sử dụng tài khoản từ 2 ô Chọn Chính/Phụ
    if (selectedProfiles.length < 2) {
      if (mainName && subName && mainName !== subName) {
        selectedProfiles = [mainName, subName];
      }
    }

    if (selectedProfiles.length < 2) {
      App.toast("Vui lòng tick chọn từ 2 đến 5 tài khoản trên bảng danh sách (hoặc chọn 2 tài khoản Chính & Phụ)!", "warn");
      return;
    }

    // Giới hạn tối đa 5 tài khoản
    if (selectedProfiles.length > 5) {
      selectedProfiles = selectedProfiles.slice(0, 5);
    }

    const hostName = selectedProfiles[0];
    const clientProfiles = selectedProfiles.slice(1);

    // Lấy cấu hình cược
    let targetBet = 100;
    if ($("gcBetSelect")) {
      targetBet = parseInt($("gcBetSelect").value || 100, 10);
    } else if ($("afTargetBet")) {
      targetBet = parseInt($("afTargetBet").value || 100, 10);
    }

    const targetMu = $("gcSlotCount") ? parseInt($("gcSlotCount").value || 2) : ($("afTargetMu") ? parseInt($("afTargetMu").value || 2) : 2);
    const chongPha = $("afChongPha") ? $("afChongPha").checked : true;
    const outGuest = $("afOutGuest") ? $("afOutGuest").checked : true;
    const xaDelayMs = $("gcDelay") ? (parseInt($("gcDelay").value || 2) * 1000) : 1000;
    const maxTries = $("afMaxTries") ? parseInt($("afMaxTries").value || 0) : 0;

    // Các tuỳ chọn mới từ người dùng
    const autoXa = $("gcAutoXaBai") ? $("gcAutoXaBai").checked : true;
    const autoStartGuestSS = $("gcAutoStartGuestSS") ? $("gcAutoStartGuestSS").checked : true;
    const autoLeaveAfter = $("gcAutoLeaveAfter") ? $("gcAutoLeaveAfter").checked : true;

    const btnSync = $("btnGcSyncMatch");
    const btnAfStart = $("afStart");
    if (btnSync) {
      btnSync.disabled = true;
      btnSync.textContent = "⏳ ĐANG DÒ TÌM PHÒNG...";
    }
    if (btnAfStart) {
      btnAfStart.disabled = true;
      btnAfStart.textContent = "⏳ Đang dò tìm phòng...";
    }

    setStatus(`[1/3] Đang điều phối ${selectedProfiles.length} tài khoản (${selectedProfiles.join(", ")}) cùng quét tìm/tạo bàn trống mức $${targetBet.toLocaleString()}...`);
    App.toast(`Bắt đầu gom bàn ${selectedProfiles.length} tài khoản: ${selectedProfiles.join(", ")}`, "info");

    try {
      const res = await App.api("/api/autoplay/find-and-match-ws", {
        method: "POST",
        body: JSON.stringify({
          profiles: selectedProfiles,
          profile_a: hostName,
          profile_b: clientProfiles[0] || "",
          target_bet: targetBet,
          mu: targetMu,
          gid: 1, // Tiến Lên Đếm Lá
          chong_pha: chongPha,
          out_guest: outGuest,
          xa_delay_ms: xaDelayMs,
          max_tries: maxTries,
          auto_xa: autoXa,
          auto_start_guest_ss: autoStartGuestSS,
          auto_leave_after: autoLeaveAfter,
        }),
      });

      if (res && res.ok) {
        if (autoXa) {
          setStatus(`✅ THÀNH CÔNG! Đã ghép ${selectedProfiles.join(", ")} vào chung bàn ${res.room_name || ""} ($${(res.bet || targetBet).toLocaleString()})! Đang xả bài...`, "success");
        } else {
          setStatus(`✅ ĐÃ TÌM THẤY BÀN! Các nick ${selectedProfiles.join(", ")} đã ngồi chung bàn ${res.room_name || ""}. Tự động xả bài đang TẮT, dừng chờ thao tác tay.`, "success");
        }
        App.toast("Gom bàn và ghép cặp thành công!", "success");
        if (window.App && window.App.refreshAccounts) window.App.refreshAccounts();
      } else {
        setStatus(`⚠️ ${res.error || "Không tìm được bàn trống phù hợp, vui lòng thử lại"}`, "error");
        App.toast(res.error || "Gom bàn thất bại", "warn");
      }
    } catch (e) {
      setStatus(`❌ Lỗi gom bàn: ${e.message}`, "error");
      App.toast("Lỗi: " + e.message, "error");
    } finally {
      if (btnSync) {
        btnSync.disabled = false;
        btnSync.textContent = "🚀 GOM BÀN & XẢ";
      }
      if (btnAfStart) {
        btnAfStart.disabled = false;
        btnAfStart.textContent = "🚀 Bắt đầu gom bàn";
      }
    }
  }

  async function stop() {
    try {
      await App.api("/api/autoplay/stop", { method: "POST" });
      setStatus("Đã dừng chu trình gom bàn.");
      App.toast("Đã dừng gom bàn", "warn");
    } catch (e) {
      App.toast("Stop lỗi: " + e.message, "error");
    }
  }

  // Bind Buttons
  if ($("afStart")) $("afStart").onclick = () => start(false);
  if ($("afStop")) $("afStop").onclick = stop;
  if ($("btnGcSyncMatch")) $("btnGcSyncMatch").onclick = () => start(true);
  if ($("btnGcStopSync")) $("btnGcStopSync").onclick = stop;

  // Cập nhật cặp ghép từ danh sách chọn
  App.setSyncPair = function (mainName, subName) {
    const selMain = $("gcProfileMain");
    const selSub = $("gcProfileSub");
    if (selMain && mainName) selMain.value = mainName;
    if (selSub && subName) selSub.value = subName;
  };

  App.autoplayRenderProfiles = renderProfiles;
  renderProfiles();
})();
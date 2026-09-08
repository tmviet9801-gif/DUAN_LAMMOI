(function () {
  // Auto gom bàn & xả bài — Quản lý Profile Chính (A) & Profile Phụ (B) đồng bộ
  const App = (window.App = window.App || {});
  const $ = App.$;
  if (!App.state.gcRunId) App.state.gcRunId = 0;

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

    // Dashboard dropdowns (Chính / Phụ)
    populateSelect($("gcProfileMain"), gameAccs, 0);
    populateSelect($("gcProfileSub"), gameAccs, gameAccs.length > 1 ? 1 : 0);
  }

  function setStatus(text, type = "info") {
    // Status trong All-in-One Dashboard
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
    // 1. Thu thập danh sách tài khoản được chọn (đa tầng dự phòng đảm bảo luôn có tài khoản hoạt động)
    let selectedProfiles = [];

    // Với 4/6 profile được tick, ghép theo thứ tự hiển thị: 1-2, 3-4, 5-6.
    // Dropdown chỉ biểu diễn được một cặp, nên không được ghi đè lựa chọn này.
    if (isFromDashboard && window.App && App.selectedProfileIds && App.selectedProfileIds.size >= 4) {
      const accs = App.state && App.state.accounts ? App.state.accounts : [];
      selectedProfiles = accs
        .filter((a) => App.selectedProfileIds.has(a.id) || App.selectedProfileIds.has(String(a.id)) || App.selectedProfileIds.has(Number(a.id)))
        .map((a) => a.name || a.username)
        .filter(Boolean);
    }

    // Ưu tiên 1 (khi bấm từ Dashboard): Lấy trực tiếp từ 2 dropdown Chính & Phụ trên thanh Gom Bàn
    if (isFromDashboard && selectedProfiles.length < 4) {
      const mainSelect = $("gcProfileMain");
      const subSelect = $("gcProfileSub");
      const mainName = mainSelect ? mainSelect.value : "";
      const subName = subSelect ? subSelect.value : "";
      if (mainName && subName && mainName !== subName) {
        selectedProfiles = [mainName, subName];
      }
    }

    // Ưu tiên 2: Lấy từ App.selectedProfileIds (các profile được tích checkbox trên bảng)
    if (selectedProfiles.length < 2 && window.App && App.selectedProfileIds && App.selectedProfileIds.size >= 2) {
      const accs = App.state && App.state.accounts ? App.state.accounts : [];
      selectedProfiles = accs
        .filter((a) => App.selectedProfileIds.has(a.id) || App.selectedProfileIds.has(String(a.id)) || App.selectedProfileIds.has(Number(a.id)))
        .map((a) => a.name || a.username)
        .filter(Boolean);
    }

    // Ưu tiên 3: Lấy từ các dòng có class row-selected hoặc selected trên #profileTbody
    if (selectedProfiles.length < 2) {
      const selectedRows = Array.from(document.querySelectorAll("#profileTbody tr.row-selected, #profileTbody tr.selected, #accTbody tr.selected"));
      const fromRows = selectedRows.map((r) => r.dataset.name).filter(Boolean);
      if (fromRows.length >= 2) {
        selectedProfiles = fromRows;
      }
    }

    // Ưu tiên 4: Lấy từ 2 dropdown trên thanh Gom Bàn
    if (selectedProfiles.length < 2) {
      const mainSelect = $("gcProfileMain");
      const subSelect = $("gcProfileSub");
      const mainName = mainSelect ? mainSelect.value : "";
      const subName = subSelect ? subSelect.value : "";
      if (mainName && subName && mainName !== subName) {
        selectedProfiles = [mainName, subName];
      }
    }

    // Ưu tiên 5: Tự động lấy các profile ĐANG MỞ (có session Chrome đang chạy trong App.state.sessions)
    if (selectedProfiles.length < 2 && window.App && App.state && App.state.sessions) {
      const openSessions = (App.state.sessions || []).filter(
        (s) => s.account && (s.state === "ready" || s.state === "busy" || s.page || s.pid)
      );
      const openNames = openSessions
        .map((s) => s.account.name || s.account.username)
        .filter(Boolean);
      const uniqueOpen = Array.from(new Set(openNames));
      if (uniqueOpen.length >= 2) {
        selectedProfiles = uniqueOpen;
      }
    }

    // Ưu tiên 6: Lấy trực tiếp từ các dòng hiển thị trên bảng DOM (#profileTbody tr)
    if (selectedProfiles.length < 2) {
      const allRows = Array.from(document.querySelectorAll("#profileTbody tr"));
      const domNames = allRows.map((r) => r.dataset.name).filter(Boolean);
      if (domNames.length >= 2) {
        selectedProfiles = [domNames[0], domNames[1]];
      }
    }

    // Ưu tiên 7: Fallback lấy 2 tài khoản đầu tiên trong danh sách accounts
    if (selectedProfiles.length < 2 && window.App && App.state && App.state.accounts && App.state.accounts.length >= 2) {
      selectedProfiles = [
        App.state.accounts[0].name || App.state.accounts[0].username,
        App.state.accounts[1].name || App.state.accounts[1].username,
      ];
    }

    if (selectedProfiles.length < 2) {
      setStatus("⚠️ Vui lòng mở ít nhất 2 profile hoặc chọn 2 tài khoản trên bảng danh sách!", "error");
      App.toast("Vui lòng mở ít nhất 2 profile hoặc chọn 2 tài khoản trên bảng danh sách!", "warn");
      return;
    }

    // Đa cặp nhận 4 hoặc 6 profile; tối đa 3 cặp.
    if (selectedProfiles.length > 6) {
      selectedProfiles = selectedProfiles.slice(0, 6);
    }
    const multiPairMode = selectedProfiles.length >= 4;
    if (multiPairMode && selectedProfiles.length % 2 !== 0) {
      setStatus("⚠️ Chạy nhiều cặp cần chọn số profile chẵn: 4 hoặc 6.", "error");
      App.toast("Chọn 4 hoặc 6 profile theo thứ tự từng cặp (1–2, 3–4).", "warn");
      return;
    }
    const pairs = multiPairMode
      ? Array.from({ length: selectedProfiles.length / 2 }, (_, i) => selectedProfiles.slice(i * 2, i * 2 + 2))
      : [];

    const hostName = selectedProfiles[0];
    const clientProfiles = selectedProfiles.slice(1);

    // Lấy cấu hình cược chính xác từ thanh Gom Bàn
    let targetBet = 100;
    if ($("gcBetSelect") && $("gcBetSelect").value) {
      targetBet = parseInt($("gcBetSelect").value || 100, 10);
    }
    if (isNaN(targetBet) || targetBet <= 0) targetBet = 100;

    const targetMu = parseInt(($("gcSlotCount") && $("gcSlotCount").value) || "2", 10) || 2;
    const chongPha = true;
    const outGuest = true;
    const xaDelayMs = $("gcDelay") ? (parseInt($("gcDelay").value || 2) * 1000) : 1000;
    const maxTries = 0; // 0 = Thử lại vô hạn cho tới khi gom được bàn

    // Các tuỳ chọn mới từ người dùng
    const autoXa = $("gcAutoXaBai") ? $("gcAutoXaBai").checked : true;
    const autoStartGuestSS = $("gcAutoStartGuestSS") ? $("gcAutoStartGuestSS").checked : true;
    const autoLeaveAfter = $("gcAutoLeaveAfter") ? $("gcAutoLeaveAfter").checked : true;

    const btnSync = $("btnGcSyncMatch");
    // Token chống kẹt nút: chỉ phiên chạy MỚI NHẤT được phép đổi trạng thái nút
    const runId = ++App.state.gcRunId;
    if (btnSync) {
      btnSync.disabled = true;
      btnSync.textContent = "⏳ ĐANG DÒ TÌM PHÒNG...";
    }

    const pairLabel = multiPairMode ? pairs.map((p) => `${p[0]} → ${p[1]}`).join(" | ") : `${hostName} → ${clientProfiles[0]}`;
    setStatus(`[1/3] Đang điều phối ${multiPairMode ? `${pairs.length} cặp` : "1 cặp"}: ${pairLabel}; cược $${targetBet.toLocaleString()}...`);
    App.toast(`Bắt đầu ${multiPairMode ? `${pairs.length} cặp` : "gom bàn"}: ${pairLabel}`, "info");

    try {
      const res = await App.api(multiPairMode ? "/api/autoplay/find-and-match-pairs-ws" : "/api/autoplay/find-and-match-ws", {
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
          ...(multiPairMode ? { pairs } : {}),
        }),
      });

      if (res && res.ok) {
        if (autoXa) {
          const roomInfo = multiPairMode
            ? (res.pairs || []).map((p) => `Cặp ${p.pair}: ${p.room_name || "hoàn tất"}`).join(" | ")
            : `${res.room_name || ""} ($${(res.bet || targetBet).toLocaleString()})`;
          setStatus(`✅ THÀNH CÔNG! ${multiPairMode ? "Các cặp đã hoàn tất:" : "Đã ghép bàn"} ${roomInfo}`, "success");
        } else {
          setStatus(`✅ ĐÃ TÌM THẤY BÀN! Các nick ${selectedProfiles.join(", ")} đã ngồi chung bàn ${res.room_name || ""}. Tự động xả bài đang TẮT, dừng chờ thao tác tay.`, "success");
        }
        App.toast(multiPairMode ? "Các cặp đã chạy xong!" : "Gom bàn và ghép cặp thành công!", "success");
        if (window.App && window.App.refreshAccounts) window.App.refreshAccounts();
      } else {
        const pairErrors = multiPairMode ? (res.pairs || []).filter((p) => !p.ok).map((p) => `Cặp ${p.pair}: ${p.error || "thất bại"}`).join(" | ") : "";
        setStatus(`⚠️ ${pairErrors || res.error || "Không tìm được bàn trống phù hợp, vui lòng thử lại"}`, "error");
        App.toast(pairErrors || res.error || "Gom bàn thất bại", "warn");
      }
    } catch (e) {
      if (App.state.gcRunId === runId) {
        setStatus(`❌ Lỗi gom bàn: ${e.message}`, "error");
        App.toast("Lỗi: " + e.message, "error");
      }
    } finally {
      // Chỉ reset nút nếu phiên này vẫn là phiên mới nhất (tránh request cũ
      // bị treo/đã Dừng ghi đè trạng thái "đang chạy" của phiên mới)
      if (App.state.gcRunId === runId && btnSync) {
        btnSync.disabled = false;
        btnSync.textContent = "🚀 GOM BÀN & XẢ";
      }
    }
  }

  async function stop() {
    // Vô hiệu hoá phiên chạy hiện tại + trả nút về trạng thái sẵn sàng NGAY
    // (không chờ request find-and-match cũ trả về — tránh nút kẹt "ĐANG DÒ TÌM PHÒNG")
    App.state.gcRunId++;
    const btnSync = $("btnGcSyncMatch");
    if (btnSync) {
      btnSync.disabled = false;
      btnSync.textContent = "🚀 GOM BÀN & XẢ";
    }
    try {
      await App.api("/api/autoplay/stop", { method: "POST" });
      setStatus("Đã dừng toàn bộ quá trình Gom bàn & xả (các tài khoản về sảnh).");
      App.toast("Đã dừng Gom bàn & xả", "warn");
    } catch (e) {
      App.toast("Stop lỗi: " + e.message, "error");
    }
  }

  // Bind Buttons (chỉ còn 1 cặp nút trên Dashboard: GOM BÀN & XẢ / Dừng)
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

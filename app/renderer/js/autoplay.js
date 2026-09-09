(function () {
  // Auto gom bàn & xả bài — chạy đúng các profile được tích trên bảng.
  // Không còn chọn Chính/Phụ: profile tích đầu tiên là account giữ tiền,
  // các profile còn lại cùng dò bàn và vào ghép.
  const App = (window.App = window.App || {});
  const $ = App.$;
  if (!App.state.gcRunId) App.state.gcRunId = 0;

  /** Các profile được TÍCH trên bảng, theo đúng thứ tự người dùng tích.
   *
   * Đây là NGUỒN SỰ THẬT DUY NHẤT cho việc chạy profile nào. Bản trước có 7
   * tầng dự phòng, tầng cuối lấy đại 2 account đầu danh sách — nghĩa là không
   * tích gì cũng chạy, và chạy nhầm người.
   */
  function profilesDaChon() {
    const ids = Array.from(App.selectedProfileIds || []);
    const accs = (App.state && App.state.accounts) || [];
    const theoId = new Map();
    for (const a of accs) theoId.set(String(a.id), a);
    return ids.map((id) => theoId.get(String(id))).filter(Boolean);
  }

  // Số dư tối thiểu để ngồi được bàn — ĐO từ trường `mM` của khung cmd 300,
  // không phải phỏng đoán. Bàn $100 chỉ cần 5x; từ $500 trở lên là 10x.
  // Bảng này phải khớp backend (controllers/auto_flow_controller/preflight.py).
  function soDuToiThieu(bet) {
    const b = Number(bet) || 0;
    if (b <= 0) return 0;
    return b === 100 ? 500 : b * 10;
  }

  function mucCuocDangChon() {
    const el = $("gcBetSelect");
    const v = parseInt((el && el.value) || "100", 10);
    return Number.isFinite(v) && v > 0 ? v : 100;
  }

  /** Vẽ danh sách profile sẽ chạy. Thứ tự chip = thứ tự gửi xuống backend. */
  function renderProfiles() {
    const hop = $("gcSelectedChips");
    if (!hop) return;
    const chon = profilesDaChon();
    if (!chon.length) {
      hop.innerHTML = '<span class="gc-chip-empty">Chưa tích profile nào</span>';
      return;
    }
    hop.innerHTML = "";
    const bet = mucCuocDangChon();
    const can = soDuToiThieu(bet);
    chon.forEach((a, i) => {
      const ten = a.name || a.username || "(không tên)";
      const tenGame = (a.character_name || "").trim();
      const soDu = typeof a.balance === "number" ? a.balance : null;
      // Backend chặn ngay trước khi mở Chrome; báo trước ở đây để người dùng
      // không phải bấm rồi mới biết.
      const thieuTien = soDu !== null && can > 0 && soDu < can;
      const el = document.createElement("span");
      el.className = "gc-chip" + (i === 0 ? " anchor" : "")
        + (tenGame && !thieuTien ? "" : " khong-dat");
      el.textContent = `${i === 0 ? "💰 " : ""}${ten}`;

      const chu = [];
      if (i === 0) chu.push("Account giữ tiền.");
      chu.push(tenGame
        ? `Tên in-game: ${tenGame}`
        : "Chưa có tên in-game — chạy Check Live, nếu không sẽ không nhận ra đồng đội");
      if (soDu === null) {
        chu.push("Chưa biết số dư — chạy Check Live.");
      } else if (thieuTien) {
        chu.push(`Số dư ${soDu.toLocaleString()} < tối thiểu ${can.toLocaleString()} `
                 + `của bàn $${bet.toLocaleString()} — sẽ KHÔNG được mở.`);
      } else {
        chu.push(`Số dư ${soDu.toLocaleString()} (bàn $${bet.toLocaleString()} `
                 + `cần ${can.toLocaleString()}).`);
      }
      el.title = chu.join(" ");
      const idx = document.createElement("span");
      idx.className = "gc-chip-idx";
      idx.textContent = `${i + 1}.`;
      el.prepend(idx);
      hop.appendChild(el);
    });
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

  async function start() {
    // Chạy ĐÚNG những profile được tích trên bảng, theo thứ tự đã tích.
    //
    // Bản trước dò qua 7 tầng dự phòng (dropdown Chính/Phụ, checkbox, dòng
    // được bôi, session đang mở, DOM, rồi cuối cùng "2 account đầu danh
    // sách"). Hậu quả: không tích gì cũng chạy, và chạy nhầm account. Nay chỉ
    // một nguồn — không đoán, thiếu thì báo.
    const chon = profilesDaChon();
    if (chon.length < 2) {
      const msg = "Hãy tích ít nhất 2 profile trên bảng danh sách bên dưới rồi bấm lại.";
      setStatus("⚠️ " + msg, "error");
      App.toast(msg, "warn");
      return;
    }

    const selectedProfiles = chon.map((a) => a.name || a.username).filter(Boolean);
    if (selectedProfiles.length < 2) {
      setStatus("⚠️ Profile đã tích không có tên hợp lệ.", "error");
      return;
    }

    // Thiếu tên in-game thì extension không nhận ra đồng đội (isPartner trả
    // false) -> đánh như người thường. Báo trước, đừng để người dùng ngồi đoán.
    const thieuTen = chon.filter((a) => !String(a.character_name || "").trim())
                         .map((a) => a.name || a.username);
    if (thieuTen.length) {
      App.toast(
        `Chưa có tên in-game cho: ${thieuTen.join(", ")}. Chạy Check Live trước, `
        + "nếu không các nick sẽ không nhận ra nhau.",
        "warn",
      );
    }

    const hostName = selectedProfiles[0];
    const clientProfiles = selectedProfiles.slice(1);

    // Lấy cấu hình cược chính xác từ thanh Gom Bàn
    let targetBet = 100;
    if ($("gcBetSelect") && $("gcBetSelect").value) {
      targetBet = parseInt($("gcBetSelect").value || 100, 10);
    }
    if (isNaN(targetBet) || targetBet <= 0) targetBet = 100;

    const targetMu = parseInt(($("gcSlotCount") && $("gcSlotCount").value) || "2", 10) || 2;
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

    const nhan = `${hostName} (giữ tiền) + ${clientProfiles.join(", ")}`;
    setStatus(`[1/3] Đang điều phối ${selectedProfiles.length} profile: ${nhan}; cược $${targetBet.toLocaleString()}...`);
    App.toast(`Bắt đầu gom bàn: ${nhan}`, "info");

    try {
      // Một nhóm duy nhất: 1 account giữ tiền + N account cùng dò bàn.
      // Chế độ "ghép cặp 1–2, 3–4, 5–6" đã bỏ cùng với dropdown Chính/Phụ.
      const res = await App.api("/api/autoplay/find-and-match-ws", {
        method: "POST",
        body: JSON.stringify({
          profiles: selectedProfiles,
          profile_a: hostName,
          profile_b: clientProfiles[0] || "",
          target_bet: targetBet,
          mu: targetMu,
          gid: 1, // Tiến Lên Đếm Lá
          max_tries: maxTries,
          auto_xa: autoXa,
          auto_start_guest_ss: autoStartGuestSS,
          auto_leave_after: autoLeaveAfter,
        }),
      });

      // Phản hồi của lượt chạy CŨ không được ghi đè thông báo. Bấm Dừng
      // xong, ~1 giây sau request cũ trả về và ô trạng thái nhảy sang XANH
      // "THÀNH CÔNG! Đã ghép bàn" ngay sau khi người dùng vừa bảo dừng.
      if (App.state.gcRunId !== runId) return;

      if (res && res.ok) {
        if (autoXa) {
          const roomInfo = `${res.room_name || ""} ($${(res.bet || targetBet).toLocaleString()})`;
          setStatus(`✅ THÀNH CÔNG! Đã ghép bàn ${roomInfo}`, "success");
        } else {
          setStatus(`✅ ĐÃ TÌM THẤY BÀN! Các nick ${selectedProfiles.join(", ")} đã ngồi chung bàn ${res.room_name || ""}. Tự động xả bài đang TẮT, dừng chờ thao tác tay.`, "success");
        }
        App.toast("Gom bàn và ghép thành công!", "success");
        if (window.App && window.App.refreshAccounts) window.App.refreshAccounts();
      } else {
        setStatus(`⚠️ ${res.error || "Không tìm được bàn trống phù hợp, vui lòng thử lại"}`, "error");
        App.toast(res.error || "Gom bàn thất bại", "warn");
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
  if ($("btnGcSyncMatch")) $("btnGcSyncMatch").onclick = () => start();
  if ($("btnGcStopSync")) $("btnGcStopSync").onclick = stop;

  // Đổi mức cược thì ngưỡng số dư đổi theo -> vẽ lại cảnh báo.
  if ($("gcBetSelect")) {
    $("gcBetSelect").addEventListener("change", () => renderProfiles());
  }

  App.autoplayRenderProfiles = renderProfiles;
  App.profilesDaChon = profilesDaChon;
  /** Tên profile được tích đầu tiên — dùng cho các thao tác đơn lẻ
   *  (Tạo bàn, Random vào phòng). Rỗng nếu chưa tích gì: người gọi phải BÁO,
   *  không được tự chọn thay người dùng. */
  App.profileDaTichDauTien = function () {
    const ds = profilesDaChon();
    return ds.length ? (ds[0].name || ds[0].username || "") : "";
  };
  renderProfiles();
})();

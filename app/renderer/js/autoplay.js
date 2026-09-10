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
    veNutTuDanh();
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
    // Mặc định FALSE: Account chính ở lại giữ bàn sau khi xả (nick phụ luôn
    // out). Thiếu ô trên giao diện thì cũng không được ngầm cho cả hai out.
    const autoLeaveAfter = $("gcAutoLeaveAfter") ? $("gcAutoLeaveAfter").checked : false;

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

  // ---- TỰ ĐÁNH: bật bộ xả cho 1 profile mà KHÔNG chạy gom bàn ----
  //
  // Người dùng tự vào bàn (có khách sẵn, hoặc ngồi chờ khách); tool tự Sẵn
  // sàng / Bắt đầu và xả như sau ván gom bàn (chế độ GIỮ BÀN). Trạng thái
  // BẬT/TẮT đọc từ backend, và backend đọc từ TRANG: trang tải lại là mất
  // chế độ, nút phải trả về TẮT chứ không tin lần bấm trước.
  if (!App.state.tuDanhOn) App.state.tuDanhOn = new Set();

  function veNutTuDanh() {
    const btn = $("btnGcTuDanh");
    if (!btn) return;
    const ten = App.profileDaTichDauTien ? App.profileDaTichDauTien() : "";
    const bat = !!ten && App.state.tuDanhOn.has(ten);
    btn.textContent = bat ? `🟢 TỰ ĐÁNH: BẬT (${ten}) — bấm để tắt` : "🤖 Tự đánh";
    btn.classList.toggle("lime", bat);
    btn.classList.toggle("blue", !bat);
  }

  async function docTrangThaiTuDanh() {
    try {
      const r = await App.api("/api/autoplay/tu-danh/status");
      const truoc = new Set(App.state.tuDanhOn);
      App.state.tuDanhOn = new Set(r.profiles || []);
      for (const ten of (r.da_roi || [])) {
        if (!truoc.has(ten)) continue;
        setStatus(`⚠️ Tự đánh trên ${ten} đã TẮT (trang tải lại / đã Dừng / Chrome đóng). Vào bàn lại rồi bấm Tự đánh.`, "error");
        App.toast(`Tự đánh trên ${ten} đã tắt`, "warn");
      }
    } catch (_) {
      // backend chưa lên: giữ trạng thái cũ, lần đọc sau sẽ sửa
    }
    veNutTuDanh();
  }

  async function batTatTuDanh() {
    // Profile tích ĐẦU TIÊN — cùng luật với "Random vào phòng". Không tích gì
    // thì BÁO, không tự chọn thay người dùng.
    const ten = App.profileDaTichDauTien ? App.profileDaTichDauTien() : "";
    if (!ten) {
      App.toast("Tích 1 profile trên bảng danh sách trước (profile tích ĐẦU TIÊN sẽ tự đánh).", "warn");
      return;
    }
    const btn = $("btnGcTuDanh");
    if (btn) btn.disabled = true;
    try {
      if (App.state.tuDanhOn.has(ten)) {
        await App.api("/api/autoplay/tu-danh/tat", {
          method: "POST",
          body: JSON.stringify({ profile_name: ten }),
        });
        App.state.tuDanhOn.delete(ten);
        setStatus(`⏹ Đã tắt Tự đánh cho ${ten}: vẫn ngồi nguyên bàn, bạn tự chơi tiếp.`);
        App.toast(`Đã tắt Tự đánh: ${ten}`, "info");
      } else {
        const autoXa = $("gcAutoXaBai") ? $("gcAutoXaBai").checked : true;
        const r = await App.api("/api/autoplay/tu-danh/bat", {
          method: "POST",
          body: JSON.stringify({ profile_name: ten, auto_xa: autoXa }),
        });
        const tenThat = r.profile || ten;
        App.state.tuDanhOn.add(tenThat);
        const oDau = r.trong_ban
          ? `đang trong bàn (${r.so_nguoi} người)`
          : "chưa vào bàn — tự vào bàn nào cũng được";
        // Extension đã kiểm ngay bàn đang ngồi lúc bật — nói rõ nó vừa làm gì.
        const vuaLam = {
          san_sang: " Đồng đội đang giữ bàn: ĐÃ GỬI Sẵn sàng.",
          bat_dau: " Đồng đội đã Sẵn sàng: ĐÃ Bắt đầu.",
          dang_van: " Ván đang chạy: tool đánh từ lượt tới của mình.",
        }[r.hanh_dong_ngay] || "";
        setStatus(
          `🤖 TỰ ĐÁNH BẬT cho ${tenThat} — ${oDau}.${vuaLam} CHỈ xả với ĐỒNG ĐỘI: bàn có người ngoài thì tool im, bạn tự chơi. Xả xong ở lại bàn.`,
          "success",
        );
        App.toast(`Tự đánh BẬT: ${tenThat}`, "success");
      }
    } catch (e) {
      setStatus(`❌ Tự đánh: ${e.message}`, "error");
      App.toast("Tự đánh lỗi: " + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
      veNutTuDanh();
    }
  }

  // ---- XÉ LẺ QUY TRÌNH: Tìm bàn (giữ bàn trống) / Vào bàn (theo bàn chung) ----
  //
  // Lấy cách làm của công cụ Sunwin: một máy giữ bàn, các máy khác bấm vào
  // thẳng bàn đó. Khác luồng GOM BÀN cũ ở chỗ không phải tích sẵn cả cặp và
  // chạy đồng thời — bấm nick nào, lúc nào cũng được.

  async function veBanChung() {
    const hop = $("gcBanChung");
    const chu = $("gcBanChungText");
    if (!hop || !chu) return;
    try {
      const r = await App.api("/api/autoplay/ban-chung");
      if (r && r.co) {
        hop.style.display = "";
        // Nhiều nick giữ bàn song song được — liệt kê hết, nick nào bấm "Vào
        // bàn" sẽ được ghép vào bàn giữ lâu nhất còn ghế.
        chu.textContent = `Đang giữ ${r.so_ban} bàn: ` + (r.ban || [])
          .map((b) => `#${b.rid} ($${Number(b.bet).toLocaleString()}) — ${b.chu}`)
          .join(" | ");
      } else {
        hop.style.display = "none";
      }
    } catch (_) {
      hop.style.display = "none";
    }
  }

  App.timBan = async function timBan(ten) {
    if (!ten) return;
    const bet = mucCuocDangChon();
    const mu = parseInt(($("gcSlotCount") && $("gcSlotCount").value) || "2", 10) || 2;
    const autoXa = $("gcAutoXaBai") ? $("gcAutoXaBai").checked : true;
    setStatus(`⏳ ${ten} đang dò bàn trống $${bet.toLocaleString()}...`);
    App.toast(`${ten}: bắt đầu dò bàn trống`, "info");
    try {
      const r = await App.api("/api/autoplay/tim-ban", {
        method: "POST",
        body: JSON.stringify({ profile_name: ten, bet, mu, auto_xa: autoXa }),
      });
      if (r && r.ok) {
        setStatus(`🎯 ${r.profile} đang GIỮ bàn #${r.rid} ($${Number(r.bet).toLocaleString()}) sau ${r.so_lan_do} lần dò. Bấm "Vào bàn" ở nick khác.`, "success");
        App.toast(`Đã giữ bàn #${r.rid}`, "success");
      } else {
        setStatus(`⚠️ ${(r && r.error) || "Chưa gặp bàn trống"}`, "error");
      }
    } catch (e) {
      setStatus(`❌ Tìm bàn lỗi: ${e.message}`, "error");
      App.toast("Tìm bàn lỗi: " + e.message, "error");
    }
    veBanChung();
  };

  App.vaoBan = async function vaoBan(ten) {
    if (!ten) return;
    const autoXa = $("gcAutoXaBai") ? $("gcAutoXaBai").checked : true;
    setStatus(`⏳ ${ten} đang vào bàn chung...`);
    try {
      const r = await App.api("/api/autoplay/vao-ban", {
        method: "POST",
        body: JSON.stringify({ profile_name: ten, auto_xa: autoXa }),
      });
      if (r && r.ok) {
        const canhBao = r.co_khach_la
          ? " ⚠️ Bàn có người ngoài — tool sẽ KHÔNG tự đánh."
          : "";
        setStatus(`✅ ${r.profile} đã vào bàn #${r.rid} cùng ${r.chu_ban} (${r.so_nguoi} người).${canhBao}`,
                  r.co_khach_la ? "error" : "success");
        App.toast(`${r.profile} đã vào bàn #${r.rid}`, "success");
      } else {
        setStatus(`⚠️ ${(r && r.error) || "Không vào được bàn chung"}`, "error");
      }
    } catch (e) {
      setStatus(`❌ Vào bàn lỗi: ${e.message}`, "error");
      App.toast("Vào bàn lỗi: " + e.message, "error");
    }
    veBanChung();
  };

  // ---- Cổng kết nối extension ----
  async function datKetNoi(bat) {
    const duong = bat ? "/api/extension/noi" : "/api/extension/ngat";
    try {
      const r = await App.api(duong, { method: "POST", body: JSON.stringify({}) });
      const n = (r && r.profiles || []).length;
      setStatus(bat
        ? `🔌 Đã yêu cầu ${n} profile NỐI LẠI với app.`
        : `⛔ Đã NGẮT kết nối ${n} profile — Chrome chạy như bình thường, tool không gửi lệnh nào nữa.`,
        bat ? "success" : "info");
      App.toast(bat ? `Kết nối lại ${n} profile` : `Ngắt kết nối ${n} profile`, bat ? "success" : "warn");
    } catch (e) {
      setStatus(`❌ ${bat ? "Kết nối" : "Ngắt kết nối"} lỗi: ${e.message}`, "error");
      App.toast(e.message, "error");
    }
  }

  if ($("btnExtNoi")) $("btnExtNoi").onclick = () => datKetNoi(true);
  if ($("btnExtNgat")) $("btnExtNgat").onclick = () => datKetNoi(false);
  if ($("btnBanChungXoa")) {
    $("btnBanChungXoa").onclick = async () => {
      try {
        await App.api("/api/autoplay/ban-chung/xoa", { method: "POST", body: JSON.stringify({}) });
        App.toast("Đã xoá bàn chung", "info");
      } catch (e) {
        App.toast("Xoá bàn chung lỗi: " + e.message, "error");
      }
      veBanChung();
    };
  }
  veBanChung();
  setInterval(veBanChung, 10000);

  // Bind Buttons (GOM BÀN & XẢ / Dừng / Tự đánh)
  if ($("btnGcSyncMatch")) $("btnGcSyncMatch").onclick = () => start();
  if ($("btnGcStopSync")) $("btnGcStopSync").onclick = stop;
  if ($("btnGcTuDanh")) $("btnGcTuDanh").onclick = batTatTuDanh;
  // Đọc trạng thái thật lúc mở app, rồi cứ 8s một lần khi đang có profile BẬT.
  docTrangThaiTuDanh();
  setInterval(() => { if (App.state.tuDanhOn.size) docTrangThaiTuDanh(); }, 8000);

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

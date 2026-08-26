(function () {
  // GameSim dashboard
  const App = (window.App = window.App || {});
  const $ = App.$;
  let pollTimer = null;

  const STATE_LABELS = {
    IDLE: "Sẵn sàng",
    JOINING: "Đang join",
    WAITING_FOR_TABLE: "Chờ bàn",
    BOOTSTRAP_ROUND: "Khởi tạo ván",
    PLAYING: "Đang chơi",
    VERIFYING_RESULT: "Xác minh",
    LEAVING: "Rời bàn",
    WAITING_NEXT_PLAYER: "Chờ người mới",
    RESETTING: "Reset bàn",
    RETRY: "Thử lại",
    ERROR: "Lỗi",
    FINISHED: "Hoàn tất",
  };

  async function start() {
    try {
      const cfg = await App.api("/api/gamesim/default-config");
      cfg.rounds = Math.max(1, parseInt($("gsRounds").value, 10) || 5);
      cfg.scenario = $("gsScenario").value;
      await App.api("/api/gamesim/start", { method: "POST", body: JSON.stringify(cfg) });
      App.toast("Đã bắt đầu mô phỏng", "success");
    } catch (e) {
      App.toast("Start lỗi: " + e.message, "error");
    }
    poll();
  }

  async function stop() {
    try {
      await App.api("/api/gamesim/stop", { method: "POST" });
      App.toast("Đã dừng", "warn");
    } catch (e) {
      App.toast("Stop lỗi: " + e.message, "error");
    }
    poll();
  }

  async function poll() {
    clearTimeout(pollTimer);
    try {
      const st = await App.api("/api/gamesim/status");
      const m = await App.api("/api/gamesim/metrics");
      const ev = await App.api("/api/gamesim/events?limit=30");
      renderStatus(st);
      renderMetrics(m);
      renderEvents(ev);
      $("gsInfo").textContent = st.running
        ? `Đang chạy: ${st.run_id} — adapter ${st.adapter}, scenario "${st.scenario}", ${st.rounds} ván`
        : "Đã dừng. Nhấn Start để chạy lại.";
      if (st.running) pollTimer = setTimeout(poll, 1200);
    } catch (_) {
      if (!pollTimer) pollTimer = setTimeout(poll, 3000);
    }
  }

  function renderStatus(st) {
    const el = $("gsGroups");
    el.innerHTML = "";
    const groups = st.groups || {};
    const keys = Object.keys(groups);
    if (!keys.length) {
      el.innerHTML = '<div class="hint">Chưa có nhóm nào chạy.</div>';
      return;
    }
    for (const g of keys) {
      const s = groups[g];
      const cls = s.state === "ERROR" ? "error" : s.state;
      const div = document.createElement("div");
      div.className = "gs-group";
      div.innerHTML = `
        <div class="t"><b>Nhóm ${App.esc(g)}</b> <span class="badge ${cls}">${STATE_LABELS[s.state] || s.state}</span></div>
        <div class="meta">Session: ${App.esc(s.session_id || "-")}</div>
        <div class="meta">Main: ${App.esc(s.main || "-")} · Support: ${App.esc(s.support || "-")}</div>
        <div class="meta">Ván: ${s.round || 0} · Retry: ${s.retries || 0}</div>
      `;
      el.appendChild(div);
    }
  }

  function renderMetrics(m) {
    const el = $("gsMetrics");
    el.innerHTML = "";
    const keys = Object.keys(m);
    if (!keys.length) {
      el.innerHTML = '<div class="hint">Chưa có metrics.</div>';
      return;
    }
    for (const g of keys) {
      const d = m[g];
      const div = document.createElement("div");
      div.className = "gs-group";
      div.innerHTML = `
        <div class="t"><b>Nhóm ${App.esc(g)}</b></div>
        <table class="gs-mtable">
          <tr><td>Tổng ván</td><td>${d.total_rounds}</td></tr>
          <tr><td>MAIN đi trước</td><td>${d.main_first}</td></tr>
          <tr><td>MAIN không đi trước</td><td>${d.main_not_first}</td></tr>
          <tr><td>Tỷ lệ giữ lượt</td><td><b>${(d.first_move_accuracy * 100).toFixed(1)}%</b></td></tr>
          <tr><td>Join OK / Fail</td><td>${d.join_ok} / ${d.join_fail}</td></tr>
          <tr><td>Timeout / Reconnect</td><td>${d.timeouts} / ${d.reconnects}</td></tr>
          <tr><td>Pass / Fail</td><td>${d.pass_count} / ${d.fail_count}</td></tr>
          <tr><td>TB chu kỳ</td><td>${d.avg_cycle_ms}ms</td></tr>
        </table>
      `;
      el.appendChild(div);
    }
  }

  function renderEvents(events) {
    const el = $("gsEvents");
    el.innerHTML = "";
    if (!events.length) {
      el.innerHTML = '<div class="hint">Chưa có sự kiện.</div>';
      return;
    }
    const list = document.createElement("div");
    list.className = "gs-events-list";
    for (const e of events.slice(0, 30)) {
      const row = document.createElement("div");
      row.className = "gs-event";
      row.innerHTML = `
        <span class="badge ${e.state_to === "ERROR" ? "error" : ""}">${App.esc(e.state_from)} → ${App.esc(e.state_to)}</span>
        <span class="meta">${App.esc((e.message || "").slice(0, 80))}</span>
      `;
      list.appendChild(row);
    }
    el.appendChild(list);
  }

  $("gsStart").onclick = start;
  $("gsStop").onclick = stop;
  App.gsStart = start;
  App.gsStop = stop;
  App.gamesimPoll = poll;
  poll();
})();
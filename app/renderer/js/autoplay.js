(function () {
  // Auto xả bài — tìm nhau
  const App = (window.App = window.App || {});
  const $ = App.$;
  const selected = new Set();
  let pollTimer = null;

  function renderProfiles() {
    const el = $("afProfiles");
    el.innerHTML = "";
    const accs = App.state.accounts || [];
    const gameAccs = accs.filter((a) => a.username || a.name);
    if (!gameAccs.length) {
      el.innerHTML = '<span class="hint">Chưa có profile có tài khoản. Import tài khoản trước.</span>';
      return;
    }
    for (const a of gameAccs) {
      const label = a.username || a.name;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip" + (selected.has(label) ? " on" : "");
      chip.textContent = label;
      chip.onclick = () => {
        if (selected.has(label)) selected.delete(label);
        else selected.add(label);
        renderProfiles();
      };
      el.appendChild(chip);
    }
  }

  async function start() {
    const names = Array.from(selected);
    if (!names.length) {
      App.toast("Chọn ít nhất 2 profile để tìm nhau", "warn");
      return;
    }
    const cfg = await App.api("/api/gamesim/default-config");
    const body = {
      profile_names: names,
      auto_out: $("afAutoOut").checked,
      auto_start: $("afAutoStart").checked,
      game: {
        adapter: "hitclub",
        url: "https://v.hitclub.latino/?a=hitclub",
        clicks: (cfg.game && cfg.game.clicks) || {},
        ws_patterns: (cfg.game && cfg.game.ws_patterns) || {},
      },
    };
    try {
      await App.api("/api/autoplay/start", { method: "POST", body: JSON.stringify(body) });
      App.toast("Đã bắt đầu chu trình auto", "success");
    } catch (e) {
      App.toast("Start lỗi: " + e.message, "error");
    }
    poll();
  }

  async function stop() {
    try {
      await App.api("/api/autoplay/stop", { method: "POST" });
      App.toast("Đã dừng", "warn");
    } catch (e) {
      App.toast("Stop lỗi: " + e.message, "error");
    }
    poll();
  }

  async function poll() {
    clearTimeout(pollTimer);
    try {
      const st = await App.api("/api/autoplay/status");
      renderStatus(st);
      if (st.running) pollTimer = setTimeout(poll, 1200);
    } catch (_) {
      if (!pollTimer) pollTimer = setTimeout(poll, 3000);
    }
  }

  function renderStatus(st) {
    $("afStatus").textContent = st.running
      ? `Đang chạy: ${st.phase_label} — anchor: ${st.anchor || "-"}, room: ${st.room_id || "-"}`
      : `Dừng — ${st.phase_label || "IDLE"}`;
  }

  $("afStart").onclick = start;
  $("afStop").onclick = stop;
  App.autoplayPoll = poll;
  App.autoplayRenderProfiles = renderProfiles;
  renderProfiles();
  poll();
})();
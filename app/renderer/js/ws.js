(function () {
  // WebSocket client - nhận sự kiện UI realtime từ backend
  const App = (window.App = window.App || {});
  const $ = App.$;

  function connectWs() {
    const wsUrl = window.desktop && window.desktop.backendUrl
      ? window.desktop.backendUrl.replace(/^http/, "ws") + "/ws"
      : "ws://127.0.0.1:17832/ws";
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => App.setBackend(true);
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "browser_installing") {
        const pct = ev.percent || 0;
        $("installModal").classList.remove("hidden");
        $("installProgressBar").style.width = pct + "%";
        $("installPercent").textContent = pct + "%";
        return;
      }
      if (ev.type === "browser_installed") {
        $("installModal").classList.add("hidden");
        App.toast("Trình duyệt đã sẵn sàng", "success");
        return;
      }
    if (ev.type === "browser_install_error") {
      $("installModal").classList.add("hidden");
      App.toast("Cập nhật trình duyệt thất bại: " + (ev.error || "lỗi"), "error");
      return;
    }
    if (ev.type === "game_sim_event") {
      if (window.App.gamesimPoll) window.App.gamesimPoll();
      return;
    }
      if (ev.sessions) {
        App.state.sessions = ev.sessions;
        if (typeof App.renderProfilesTable === "function") {
          App.renderProfilesTable();
        }
      }
      if (ev.type === "opened" || ev.type === "closed" || ev.type === "layout") {
        if (typeof App.renderProfilesTable === "function") {
          App.renderProfilesTable();
        }
      }
      if (ev.type === "accounts_updated" || ev.type === "room_info_updated" || ev.type === "balance_updated" || ev.type === "log_updated" || ev.type === "room_left") {
        if (ev.profile_name && Array.isArray(App.state.accounts)) {
          const acc = App.state.accounts.find(a => a.name === ev.profile_name || a.username === ev.profile_name || a.id === ev.profile_name);
          if (acc) {
            if (ev.balance !== undefined) acc.balance = ev.balance;
            if (ev.room !== undefined) acc.room = ev.room;
            if (ev.log !== undefined) acc.log = ev.log;
          }
        }
        if (typeof App.renderProfilesTable === "function") {
          App.renderProfilesTable();
        }
        if (typeof App.refresh === "function") {
          App.refresh();
        }
      }
    };
    ws.onclose = () => {
      App.setBackend(false);
      setTimeout(connectWs, 2000);
    };
    App.state.ws = ws;
  }

  App.connectWs = connectWs;
})();

(function () {
  // WebSocket client - nhận sự kiện UI realtime từ backend
  const App = (window.App = window.App || {});
  const $ = App.$;

  function connectWs() {
    const ws = new WebSocket(`ws://127.0.0.1:8000/ws`);
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

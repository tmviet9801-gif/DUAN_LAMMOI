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
      if (ev.type === "accounts_updated" || ev.type === "cards_updated" || ev.type === "room_info_updated" || ev.type === "balance_updated" || ev.type === "log_updated" || ev.type === "room_left") {
        if (ev.profile_name && Array.isArray(App.state.accounts)) {
          const p = (ev.profile_name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
          const acc = App.state.accounts.find(a => {
            if (!a) return false;
            const n = (a.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
            const u = (a.username || "").toLowerCase().replace(/[^a-z0-9]/g, "");
            const c = (a.character_name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
            const i = String(a.index || a.id || "").toLowerCase();
            return p === n || p === u || p === c || p === i;
            // ĐÃ BỎ hai nhánh đoán theo CHỮ SỐ CUỐI tên. Nhóm có
            // nicktestxabai1, nicktestxxabai1, nicktestxabai11 — cả ba đều kết
            // thúc bằng "1", nên khi khớp chính xác trượt thì `endsWith("1")`
            // gán ngay cho account ĐẦU TIÊN có tên tận cùng "1". Kết quả: bài
            // trên tay, số dư và số phòng của nick này hiện trên dòng nick
            // khác. Cùng mô-típ đã bị loại khỏi `isPartner`.
          });
          if (acc) {
            if (ev.balance !== undefined) acc.balance = ev.balance;
            if (ev.room !== undefined) acc.room = ev.room;
            if (ev.log !== undefined) acc.log = ev.log;
            if (ev.cards !== undefined) acc.cards = ev.cards;
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

(function () {
  // App - entry point: refresh dữ liệu, kết nối WS, khởi chạy view
  const App = (window.App = window.App || {});
  const state = App.state;

  async function refresh() {
    try {
      state.config = await App.api("/api/config");
      state.accounts = await App.api("/api/accounts");
      state.sessions = await App.api("/api/sessions");
      if (!state.antiDetect) state.antiDetect = await App.api("/api/antidetect");
      if (!state.info) state.info = await App.api("/api/info");
      if (!state.version) state.version = await App.api("/api/version");
      App.setBackend(true);
      App.renderConfig();
      App.renderProfilesTable();
      App.renderInfo();
      if (App.autoplayRenderProfiles) App.autoplayRenderProfiles();
    } catch (e) {
      App.setBackend(false);
      App.log.warn("refresh failed:", e.message);
    }
  }

  App.refresh = refresh;

refresh();
App.connectWs();
App.switchView("gamesim");
App.initProfilesTableControls();
App.setupUpdater();
})();
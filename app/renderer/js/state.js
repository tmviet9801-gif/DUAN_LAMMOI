(function () {
  // Central state - dữ liệu toàn ứng dụng
  window.App = window.App || {};
  window.App.state = {
    config: null,
    accounts: [],
    sessions: [],
    antiDetect: null,
    info: null,
    ws: null,
    version: null,
  };
})();

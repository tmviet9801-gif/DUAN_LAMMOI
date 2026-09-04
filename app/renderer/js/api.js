(function () {
  // API client - gọi REST backend
  window.App = window.App || {};

  const API_BASE = window.desktop ? window.desktop.backendUrl : "http://127.0.0.1:8000";

  window.App.api = async function api(path, options = {}) {
    const res = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) throw new Error((await res.text()) || res.statusText);
    return res.json();
  };

  window.App.runApi = async function runApi(path, options, okMsg, errMsg) {
    try {
      const res = await window.App.api(path, options);
      if (okMsg) window.App.toast(okMsg, "success");
      if (typeof window.App.refresh === "function") {
        window.App.refresh();
      }
      return res;
    } catch (e) {
      window.App.toast(errMsg || `Lỗi: ${e.message}`, "error");
    }
  };
})();

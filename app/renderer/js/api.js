(function () {
  // API client - gọi REST backend
  window.App = window.App || {};

  const API_BASE = window.desktop ? window.desktop.backendUrl : "http://127.0.0.1:17832";

  window.App.api = async function api(path, options = {}) {
    const res = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      // FastAPI trả {"detail": "..."} — ném nguyên JSON ra thì người dùng đọc
      // được cái vỏ chứ không đọc được lý do.
      const raw = await res.text();
      let msg = raw || res.statusText;
      try {
        const j = JSON.parse(raw);
        if (j && typeof j.detail === "string") msg = j.detail;
        else if (j && Array.isArray(j.detail)) {
          msg = j.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
        }
      } catch (_) {}
      throw new Error(msg);
    }
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

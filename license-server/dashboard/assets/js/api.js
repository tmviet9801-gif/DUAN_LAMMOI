window.AdminAPI = (function () {
  function token() { return localStorage.getItem("at_lic_token") || ""; }
  function setToken(t) { localStorage.setItem("at_lic_token", t); }
  function clearToken() { localStorage.removeItem("at_lic_token"); }

  async function req(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    const t = token();
    if (t) headers["Authorization"] = "Bearer " + t;
    const res = await fetch(path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) {
      clearToken();
      location.reload();
      throw new Error("Het phien dang nhap");
    }
    if (!res.ok) {
      let msg = res.statusText;
      try { const d = await res.json(); msg = d.detail || d.message || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  }

  return {
    get: (p) => req("GET", p),
    post: (p, b) => req("POST", p, b),
    patch: (p, b) => req("PATCH", p, b),
    del: (p) => req("DELETE", p),
    token,
    setToken,
    clearToken,
  };
})();
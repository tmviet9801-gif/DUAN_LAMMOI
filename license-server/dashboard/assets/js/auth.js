window.Auth = (function () {
  async function login(pass) {
    const r = await AdminAPI.post("/api/admin/login", { password: pass });
    AdminAPI.setToken(r.token);
    return r;
  }
  function logout() {
    AdminAPI.clearToken();
    location.reload();
  }
  function isLoggedIn() { return !!AdminAPI.token(); }
  return { login, logout, isLoggedIn };
})();
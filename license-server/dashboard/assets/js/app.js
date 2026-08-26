(function () {
  const UI = window.UI;
  const views = ["dashboard", "licenses", "issue", "plans"];
  const titles = {
    dashboard: "Dashboard",
    licenses: "Licenses",
    issue: "Cap license",
    plans: "Goi thue",
  };

  function show(v) {
    views.forEach((x) => {
      UI.$("#view-" + x).classList.toggle("hidden", x !== v);
    });
    document.querySelectorAll(".nav-item").forEach((n) =>
      n.classList.toggle("active", n.dataset.view === v));
    UI.$("#pageTitle").textContent = titles[v];
    if (v === "dashboard") Dashboard.load().catch((e) => UI.toast(e.message, "error"));
    if (v === "licenses") Licenses.load().catch((e) => UI.toast(e.message, "error"));
    if (v === "issue") Licenses.loadPlans().catch((e) => UI.toast(e.message, "error"));
    if (v === "plans") Plans.load().catch((e) => UI.toast(e.message, "error"));
  }

  function initApp() {
    UI.$("#loginView").classList.add("hidden");
    UI.$("#appView").classList.remove("hidden");
    UI.$("#logoutBtn").onclick = () => Auth.logout();
    document.querySelectorAll(".nav-item").forEach((n) => (n.onclick = () => show(n.dataset.view)));
    Licenses.wire();
    Plans.wire();
    show("dashboard");
  }

  function initLogin() {
    UI.$("#appView").classList.add("hidden");
    UI.$("#loginView").classList.remove("hidden");
    UI.$("#loginForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      UI.$("#loginMsg").textContent = "Dang kiem tra...";
      try {
        await Auth.login(UI.$("#loginPass").value);
        initApp();
      } catch (err) {
        UI.$("#loginMsg").textContent = "X " + err.message;
      }
    });
  }

  if (Auth.isLoggedIn()) initApp();
  else initLogin();
})();
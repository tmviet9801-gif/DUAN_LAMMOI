(function () {
  // Menu bar kiểu VS Code: Game | Trang chủ | Cấu hình | Nhóm | Hệ thống
  const App = (window.App = window.App || {});
  const $ = App.$;
  const state = App.state;

  function closeAllMenus() {
    document.querySelectorAll(".mmenu").forEach((m) => m.classList.add("hidden"));
    document.querySelectorAll(".mroot").forEach((b) => b.classList.remove("open"));
  }

  function switchView(view) {
    document.querySelectorAll(".view").forEach((v) =>
      v.classList.toggle("hidden", v.id !== "view-" + view)
    );
    document.querySelectorAll(".menu-item[data-view]").forEach((b) =>
      b.classList.toggle("active", b.dataset.view === view)
    );
    if (view === "groups" && window.App.groupsLoad) window.App.groupsLoad();
    if (view === "proxy" && window.App.proxyLoad) window.App.proxyLoad();
    if (view === "config" && window.App.licenseRefresh) window.App.licenseRefresh();
    closeAllMenus();
  }
  App.switchView = switchView;

  // ---- mở/đóng dropdown menu bar ----
  document.querySelectorAll(".mroot").forEach((root) => {
    root.onclick = (e) => {
      e.stopPropagation();
      const menuId = root.dataset.menu;
      const menu = document.getElementById(menuId);
      const isOpen = !menu.classList.contains("hidden");
      closeAllMenus();
      if (!isOpen) {
        menu.classList.remove("hidden");
        root.classList.add("open");
      }
    };
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".menubar")) closeAllMenus();
  });

  // ---- hành động menu-item ----
  async function openProfilesFolder() {
    if (state.info && state.info.profiles_dir) {
      try { await window.desktop.openFolder(state.info.profiles_dir); } catch (_) {}
    }
  }

  document.querySelectorAll(".menubar .menu-item").forEach((item) => {
    item.onclick = (e) => {
      e.stopPropagation();
      const view = item.dataset.view;
      const action = item.dataset.action;
      if (view) {
        switchView(view);
        return;
      }
      switch (action) {
        case "add-profile":
          if (window.App.openAddProfile) window.App.openAddProfile();
          break;
        case "import-accounts":
          if (window.App.openImport) window.App.openImport();
          break;
        case "open-selected":
          if (window.App.openSelected) window.App.openSelected();
          break;
        case "delete-selected":
          if (window.App.deleteSelected) window.App.deleteSelected();
          break;
        case "open-profiles-folder":
          openProfilesFolder();
          break;
        case "check-update":
          if (window.__checkUpdate) window.__checkUpdate();
          break;
        case "license-info":
          if (window.App.licenseRefresh) window.App.licenseRefresh();
          break;
        case "make-license":
          if (window.App.openMakeLicense) window.App.openMakeLicense();
          break;
        case "toggle-theme":
          if (window.App.toggleTheme) window.App.toggleTheme();
          break;
        case "af-start":
          const btnAf = document.getElementById("afStart");
          if (btnAf) btnAf.click();
          break;
        case "af-stop":
          const btnStop = document.getElementById("afStop");
          if (btnStop) btnStop.click();
          break;
        case "exit":
          window.close();
          break;
      }
      closeAllMenus();
    };
  });

  // Click brand "Auto Tool" -> về Quản lý profile (Home) thay vì gamesim
  $("brandHome").onclick = () => switchView("home");
})();

(function () {
  // Updater - widget auto-update electron-updater
  const App = (window.App = window.App || {});
  const $ = App.$;

  function setupUpdater() {
    if (!window.updater) return;
    const text = $("updateText");
    const progWrap = $("updateProgressWrap");
    const progBar = $("updateProgressBar");
    const btnInstall = $("btnUpdateInstall");
    const btnDownload = $("btnUpdateDownload");

    const show = (stateName, message, cls) => {
      text.textContent = message;
      text.className = "update-text" + (cls ? " " + cls : "");
      progWrap.classList.toggle("hidden", stateName !== "downloading");
      btnInstall.classList.toggle("hidden", stateName !== "ready");
      btnDownload.classList.toggle("hidden", stateName !== "available");
      if (stateName === "available") {
        btnDownload.textContent = "Cài đặt bản mới";
      }
    };

    window.updater.onStatus((s) => {
      switch (s.state) {
        case "checking":
          show("checking", "Đang kiểm tra cập nhật…");
          break;
        case "available":
          show("available", `Bản mới v${s.version} có sẵn!`, "new-version");
          break;
        case "up-to-date":
          show("up-to-date", "Bạn đang dùng bản mới nhất", "latest");
          break;
        case "downloading":
          progBar.style.width = s.percent + "%";
          show("downloading", `Đang tải… ${s.percent}%`, "downloading");
          break;
        case "ready":
          show("ready", "Đã tải xong bản cập nhật", "new-version");
          btnInstall.textContent = "Cài đặt & khởi động lại";
          break;
        case "error":
          show("error", "");
          break;
      }
    });

    btnDownload.onclick = () => window.updater.downloadUpdate();
    btnInstall.onclick = () => window.updater.installUpdate();
    window.__checkUpdate = () => {
      text.textContent = "Đang kiểm tra cập nhật…";
      text.className = "update-text";
      window.updater.checkForUpdate();
    };

    setTimeout(() => window.updater.checkForUpdate(), 5000);
  }

  App.setupUpdater = setupUpdater;
})();

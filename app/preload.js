const { contextBridge, ipcRenderer } = require("electron");

const isPackaged = (() => {
  try {
    return process.env.NODE_ENV === "production" || require("electron").app?.isPackaged === true;
  } catch (_) {
    return process.env.NODE_ENV === "production";
  }
})();

contextBridge.exposeInMainWorld("desktop", {
  platform: process.platform,
  backendUrl: "http://127.0.0.1:8000",
  isPackaged,
  selectFolder: (defaultPath) => ipcRenderer.invoke("select-folder", defaultPath),
  openFolder: (folder) => ipcRenderer.invoke("open-folder", folder),
});

contextBridge.exposeInMainWorld("updater", {
  onStatus: (cb) => ipcRenderer.on("update-status", (_e, data) => cb(data)),
  checkForUpdate: () => ipcRenderer.send("check-for-update"),
  downloadUpdate: () => ipcRenderer.send("download-update"),
  installUpdate: () => ipcRenderer.send("install-update"),
});

const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { spawn, execSync } = require("child_process");
const path = require("path");
const http = require("http");
const fs = require("fs");

const isPackaged = app.isPackaged;
const BACKEND_DIR = path.join(__dirname, "..", "backend");
const PORT = 8000;
const HEALTH_URL = `http://127.0.0.1:${PORT}/health`;

let backend = null;
let mainWindow = null;

function findBackend() {
  if (isPackaged) {
    return path.join(process.resourcesPath, "backend", "tab-manager-backend.exe");
  }
  const venv = path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe");
  return fs.existsSync(venv) ? venv : "python";
}

function backendArgs() {
  return isPackaged ? [] : ["main.py"];
}

function waitForBackend(timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve) => {
    const check = () => {
      if (Date.now() > deadline) return resolve(false);
      http
        .get(HEALTH_URL, (res) => {
          res.resume();
          if (res.statusCode === 200) return resolve(true);
          setTimeout(check, 500);
        })
        .on("error", () => setTimeout(check, 500));
    };
    check();
  });
}

function startBackend() {
  const python = findBackend();
  const args = backendArgs();
  backend = spawn(python, args, {
    cwd: isPackaged ? path.dirname(python) : BACKEND_DIR,
    stdio: "pipe",
  });
  backend.stdout.on("data", (d) => console.log("[backend]", d.toString().trim()));
  backend.stderr.on("data", (d) => console.error("[backend]", d.toString().trim()));
  backend.on("exit", (code) => {
    console.log("[backend] exited", code);
    backend = null;
  });
  return backend;
}

function killBackend() {
  if (!backend || backend.killed) return;
  try {
    execSync(`taskkill /pid ${backend.pid} /t /f`, { stdio: "ignore" });
  } catch (_) {}
}

async function backendAlreadyRunning() {
  try {
    const res = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch (_) {
    return false;
  }
}

async function getBackendVersion() {
  try {
    const res = await fetch(`http://127.0.0.1:${PORT}/api/version`, {
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.version || null;
  } catch (_) {
    return null;
  }
}

function killPortOwner(port) {
  try {
    const out = execSync(`netstat -ano | findstr :${port} | findstr LISTENING`, {
      encoding: "utf8",
    });
    for (const line of out.trim().split("\n")) {
      const parts = line.trim().split(/\s+/);
      const pid = parts[parts.length - 1];
      if (pid && pid !== String(process.pid)) {
        try {
          execSync(`taskkill /pid ${pid} /t /f`, { stdio: "ignore" });
          console.log("[backend] da kill process cu giu port", pid);
        } catch (_) {}
      }
    }
  } catch (_) {}
}

function setupAutoUpdater() {
  if (!isPackaged) return;
  const { autoUpdater } = require("electron-updater");
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;

  const send = (channel, data) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(channel, data);
    }
  };

  autoUpdater.on("checking-for-update", () => send("update-status", { state: "checking" }));
  autoUpdater.on("update-available", (info) =>
    send("update-status", { state: "available", version: info.version })
  );
  autoUpdater.on("update-not-available", () => send("update-status", { state: "up-to-date" }));
  autoUpdater.on("download-progress", (p) =>
    send("update-status", { state: "downloading", percent: Math.round(p.percent) })
  );
  autoUpdater.on("update-downloaded", (info) =>
    send("update-status", { state: "ready", version: info.version })
  );
  autoUpdater.on("error", (err) =>
    send("update-status", { state: "error", message: err.message })
  );

  ipcMain.on("check-for-update", () => {
    autoUpdater.checkForUpdates().catch(() => {});
  });
  ipcMain.on("download-update", () => {
    autoUpdater.downloadUpdate().catch(() => {});
  });
  ipcMain.on("install-update", () => {
    autoUpdater.quitAndInstall();
  });
}

app.whenReady().then(async () => {
  const appVersion = app.getVersion();
  const runningVersion = await getBackendVersion();
  if (runningVersion === appVersion) {
    console.log("[backend] da chay san, version khop, dung chung");
  } else {
    if (await backendAlreadyRunning()) {
      console.log("[backend] version khac (app=%s backend=%s), kill + spawn lai", appVersion, runningVersion);
      killPortOwner(PORT);
    }
    startBackend();
  }
  const ok = await waitForBackend();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  if (!ok) {
    dialog.showErrorBox(
      "Không kết nối được backend",
      "Không thể khởi động backend. Kiểm tra bản cài đặt hoặc tường lửa."
    );
  }
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow.on("closed", () => (mainWindow = null));
  setupAutoUpdater();
});

app.on("window-all-closed", () => {
  killBackend();
  app.quit();
});

app.on("before-quit", killBackend);

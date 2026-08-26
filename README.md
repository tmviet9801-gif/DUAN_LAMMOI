# Tab Manager - Quản lý đa profile trình duyệt

Ứng dụng desktop quản lý nhiều tài khoản/profile trên các nền tảng: mở nhiều cửa sổ Camoufox cùng lúc, xếp lưới trên màn hình, mỗi profile có fingerprint riêng (UA Chrome, OS, locale) và lưu session đăng nhập riêng.

## Tính năng

- Mở đồng thời nhiều cửa sổ trình duyệt, xếp lưới tự động (cấu hình cột, khoảng cách, lề)
- Kích thước cửa sổ cố định hoặc tự chia đều màn hình; hướng sắp xếp theo hàng/cột
- Mỗi profile có fingerprint riêng: User-Agent Chrome desktop ngẫu nhiên (Windows/macOS/Linux), locale
- Lưu session riêng cho từng profile (cookies, localStorage) — đăng nhập 1 lần, lần sau mở lại không cần login
- Hiển thị tên profile ngay trên tab trình duyệt để nhận biết
- Auto-update: tự kiểm tra bản mới, thông báo và cài đặt 1 nút bấm

## Cài đặt

Tải installer từ GitHub Releases: `Tab Manager-Setup-x.x.x.exe`

## Phát triển

Yêu cầu: Python 3.11+, Node.js 18+.

### Lần đầu (hoặc đổi máy mới)

```powershell
install.bat    # tự động: tạo venv + pip install + camoufox fetch + npm install
```

### Hàng ngày

```powershell
start.bat      # chạy dev (backend + Electron, hot reload code Python/JS)
```

### Chạy tests (sau mỗi lần sửa code)

```powershell
test.bat       # tự cài pytest + httpx nếu chưa có, chạy toàn bộ test suite
```

Tests bao gồm: config (load/save, profiles_dir), fingerprint (UA, OS), window_layout (lưới), API endpoints (health, config, accounts, bulk accounts, profiles-dir, browser-status), game_sim (state machine, account pool, mock scenario). 67 tests hiện tại.

### Cập nhật Camoufox browser (khi muốn bundle bản mới vào installer)

```powershell
fetch-browser.bat   # tải lại Camoufox browser (~500MB)
```

## Build installer

```powershell
build.bat    # tạo Auto-Tool-Setup-X.X.X.exe trong app\release\ (có bundle browser nếu đã fetch)
```

## Phát hành bản mới

1. Sửa `version` trong `app/package.json` và `APP_VERSION` trong `backend/models/config_model.py`
2. Chạy `build.bat`
3. Tạo GitHub Release (tag `vX.X.X`), upload `Auto-Tool-Setup-X.X.X.exe` + `latest.yml`
4. Hoặc dùng `publish.ps1 -Version 1.0.3` để tự động bump version + build + upload + xóa release cũ

Sau khi publish, **máy user đã cài bản cũ sẽ tự thấy thông báo cập nhật** trong app (electron-updater), bấm "Cài đặt bản mới" → tải về → "Cài đặt & khởi động lại" → tự cập nhật.

## Game Room Simulator (kiểm thử quyền đi trước)

Menu 🎮 **Game Test** — hệ thống State Machine mô phỏng vòng đời phòng game, kiểm tra cơ chế "người thắng ván trước được đi trước ván sau". Chi tiết thiết kế: `docs/GAME_SIM_PLAN.md`.

- **11 trạng thái**: IDLE, JOINING, WAITING_FOR_TABLE, BOOTSTRAP_ROUND, PLAYING, VERIFYING_RESULT, LEAVING, WAITING_NEXT_PLAYER, RESETTING, RETRY, ERROR
- **Account pool round-robin**: support quay vòng, bỏ qua busy/cooldown
- **Adapter**: `mock` (mặc định, chạy được ngay) / `selector` (điều khiển trang thật qua Playwright + selectors)
- **Metrics**: tổng ván, MAIN đi trước/không, tỷ lệ giữ lượt, join OK/Fail, timeout, reconnect, pass/fail, chu kỳ TB
- **SQLite**: `%APPDATA%\AutoTool\data\game_sim.db` (runs/events/rounds)
- API: `/api/gamesim/*` (start, stop, status, metrics, events, default-config)

Backend: `backend/game_sim/` (state_machine, states, account_pool, game_adapter, metrics, storage, scheduler, manager). Frontend: `js/gamesim.js`.

## Cấu trúc

```
backend/                          FastAPI + Camoufox (đóng gói thành backend.exe)
  main.py                         entry point: app factory + lifespan + mount routers
  core/                           helper: logging, time, events (UI), utils
    logging_setup.py              cấu hình log tập trung
    time_utils.py                 timestamp, Stopwatch, format_duration
    events.py                     EventHub + UIEventEmitter (push sự kiện UI qua WS)
    utils.py                      slugify, expand_user_path
  models/                         dữ liệu + logic thuần (MVC Model)
    config_model.py               config.json / accounts.json / profiles_dir
    fingerprint_model.py          sinh UA/OS fingerprint
    window_layout_model.py        tính lưới cửa sổ
    bundled_model.py              copy browser bundled vào INSTALL_DIR
  services/                       nghiệp vụ (MVC Service / MVP Presenter)
    browser_service.py            BrowserManager, TabSession, cài/tải browser
    account_service.py            tự gán fingerprint cho account
  controllers/                    route handler (MVC Controller)
    info_controller.py            health, info, version, profiles-dir, browser-status
    config_controller.py          GET/POST /api/config, antidetect
    account_controller.py         accounts CRUD
    browser_controller.py         open/close/layout/sessions
    ws_controller.py              /ws
  tests/                          pytest suite (38 tests)

app/                              Electron desktop app
  main.js                         khởi động backend.exe + cửa sổ + IPC (chọn thư mục)
  preload.js                      bridge renderer → main
  renderer/
    index.html                    layout: menu hamburger + 2 view
    styles.css
    js/                           chia nhỏ theo module (namespace window.App)
      api.js                      REST client
      state.js                    state tập trung
      ui.js                       toast, confirm, esc, logger
      render.js                   render config/accounts/sessions/info
      ws.js                       WebSocket nhận sự kiện UI
      menu.js                     hamburger menu, chuyển view, chọn thư mục profile
      actions.js                  sự kiện người dùng (nút, form)
      updater.js                  widget auto-update
      app.js                      entry point

install.bat          setup môi trường dev (venv + deps + camoufox + npm)
fetch-browser.bat    tải lại Camoufox browser để bundle vào installer
start.bat            chạy dev
test.bat             chạy test suite (pytest)
build.bat            build installer
publish.ps1          build + publish GitHub Release
```

Luồng dữ liệu backend: `controllers` nhận request → gọi `services` (BrowserManager) → đọc/ghi `models` (config/accounts) → sự kiện UI phát qua `core/events.py` (EventHub → WebSocket → frontend `js/ws.js`).

## Lưu ý

- Profile/data được lưu tại `%APPDATA%\AutoTool\data` (bản cài đặt)
- Camoufox browser: nếu `build_backend.ps1` phát hiện đã fetch trước đó, browser sẽ được **đóng gói vào installer** (mở app lần đầu không cần tải lại). Nếu chưa fetch, app sẽ tự tải về (~500MB) trong lần chạy đầu tiên.

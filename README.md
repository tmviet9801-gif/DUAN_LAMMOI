# AutoTool — Tool đa profile cho game bài

Ứng dụng desktop (Electron + FastAPI + Camoufox) quản lý nhiều profile/tài khoản game, mỗi profile có **fingerprint chống phát hiện riêng**, **proxy riêng**, **session đăng nhập riêng**. Cốt lõi là **Auto-flow tìm nhau & xả bài** cho các cổng game bài (HITCLUB, B52…) với hệ thống **license cho thuê** và **giới hạn tab**.

> Phiên bản hiện tại: **v1.0.3** — bản HITCLUB (`platform_config.py`).

---

## 1. Tổng quan kiến trúc

```
┌───────────────────────────────────────────────────────────────┐
│  Electron (app/)                                              │
│  main.js (spawn backend.exe, auto-update, IPC chọn thư mục)   │
│  renderer/  index.html + styles.css + js/* (namespace App)    │
│    menubar kiểu VS Code · light/dark · đồng hồ · dashboard    │
└──────────────┬────────────────────────────────────────────────┘
               │ REST /api/*  +  WebSocket /ws (realtime)
┌──────────────▼────────────────────────────────────────────────┐
│  FastAPI (backend/) — MVC/MVP                                  │
│  controllers/  route handler                                  │
│    info · config · account · browser · proxy · license        │
│    game_sim · auto_flow · ws                                  │
│  services/     nghiệp vụ                                      │
│    browser_service (BrowserManager/TabSession) · page_pool    │
│    account_service                                            │
│  models/       dữ liệu + logic thuần                          │
│    config_model · fingerprint_model · window_layout_model     │
│    bundled_model · proxy_model                                │
│  core/         logging · time_utils · events(WS hub) · utils  │
│  game_sim/     hệ thống mô phỏng + adapter game thật          │
│  license.py · platform_config.py                              │
└────────────────────────────────────────────────────────────────┘
```

- **Dữ liệu tách theo cổng game**: bản HITCLUB → `%APPDATA%\AutoTool_HITCLUB\data`, bản B52 → `%APPDATA%\AutoTool_B52\data`. Đổi `PLATFORM_ID` trong `backend/platform_config.py` để build bản khác.
- **Backend** chạy 1 event loop async; I/O blocking (download, proxy check) nằm trong thread pool.

---

## 2. Những gì đã làm (v1.0.3)

### 2.1. Quản lý profile / tài khoản
- Bảng profile: STT, Tên, User-Agent, Proxy + nút **Mở / Sửa / Xóa**
- Search, sort (A-Z, ngày tạo), pagination (10/trang)
- Click dòng / **Ctrl+A** chọn nhiều → **Mở đã chọn**, **Xóa đã chọn** (xóa cả dữ liệu trên đĩa)
- Thêm profile đơn / **thêm nhanh** (prefix + count → `A01…A10`)
- **Import tài khoản từ file .txt** (`nick|pass`) → tự gán cho profile chưa có account, tạo profile mới nếu hết
- Gán **username/password** cho profile (dùng khi login game)
- Lưu session riêng từng profile (cookies, localStorage)

### 2.2. Fingerprint & Proxy
- **Camoufox** chống phát hiện: UA Chrome, OS (Windows/macOS/Linux) ngẫu nhiên + xoay vòng, locale
- **Proxy gắn theo profile** (định dạng `IP:Port:User:Pass`, trống = IP máy)
- **Tab quản lý proxy**: nhập/lưu danh sách → **Kiểm tra 1 hoặc tất cả** (song song) → proxy sống hiển thị `✓ IP (ms)`, proxy chết `✗ error` → **Áp dụng proxy sống** cho profile chưa có proxy

### 2.3. Browser
- Mở nhiều cửa sổ Camoufox, **xếp lưới** tự động (cột, gap, margin, hướng row/col, kích thước cố định)
- Tên profile hiển thị trên tab browser
- **Bundle browser vào installer** (lần đầu không tải ~500MB) — nếu chưa fetch, tự tải có progress bar

### 2.4. License cho thuê + giới hạn tab
- **License key** ký HMAC-SHA256, format `AUTO-<sig>-<base64>`
- Payload: `machine_id|expiry_ts|max_tabs|features`
- **Bind máy** (MachineGuid registry), có hạn sử dụng, giới hạn số tab
- App chặn nếu chưa kích hoạt/hết hạn (overlay nhập key); hiển thị số tab ở footer
- **Mỗi bản giới hạn 10 tab** — vượt giới hạn báo `429`
- Owner sinh key: `make_license.bat` / `python backend/tools/make_license.py --machine-id <guid> --days 30 --max-tabs 10`

### 2.5. Game Room Simulator (kiểm thử quyền đi trước)
- **State Machine 11 trạng thái**: IDLE, JOINING, WAITING_FOR_TABLE, BOOTSTRAP_ROUND, PLAYING, VERIFYING_RESULT, LEAVING, WAITING_NEXT_PLAYER, RESETTING, RETRY, ERROR
- **Account Pool** round-robin (support quay vòng, bỏ qua busy/cooldown)
- **Adapter**: `mock` (chạy ngay) / `configurable` (game web có DOM) / `hitclub` (canvas — click tọa độ + WS)
- **Metrics**: tổng ván, MAIN đi trước/không, tỷ lệ giữ lượt, join OK/Fail, timeout, reconnect, pass/fail, chu kỳ TB
- **SQLite** `game_sim.db` (runs/events/rounds) + dashboard realtime qua WS
- Chi tiết: `docs/GAME_SIM_PLAN.md`

### 2.6. Auto-flow tìm nhau & xả bài (HITCLUB)
Panel **"Auto xả bài — tìm nhau"** trong Game view:
1. **Tick acc** tham gia (4–5 acc cho nhanh)
2. Mở trang + login cho tất cả
3. **Tìm bàn trống**: acc đầu thấy bàn = **anchor** → bắt **room id + join template** qua WS sniffer
4. Các acc còn lại **join theo room id** (gửi lại đúng message join đã bắt)
5. **Xả bài** (click/message cấu hình)
6. **Tự rời** sau xả (bật) hoặc **chờ khách** → tự bắt đầu khi khách sẵn sàng (WS event)
- Backend: `game_sim/auto_flow.py` + `controllers/auto_flow_controller.py`
- **WS sniffer** (`game_sim/ws_sniffer.py`): hook `WebSocket` trong page, ghi mọi send/recv ra `ws_capture.jsonl`, expose `__ws_send()` để gửi lại message
- **Capture workflow**: `POST /api/gamesim/capture` → chơi thủ công 1 ván → `GET /api/gamesim/ws-capture` phân tích protocol

### 2.7. UI
- **Menubar kiểu VS Code**: `Game | Trang chủ | Proxy | Cấu hình | Nhóm | Hệ thống`
- **Game là màn hình chính** (mặc định mở Game)
- **Light/Dark theme** (lưu localStorage), font hiện đại, màu tươi
- **Đồng hồ thời gian thực** góc dưới, giao diện tối giản (ít padding, ít ghi chú)
- Auto-update (electron-updater)

### 2.8. Scripts
| Script | Chức năng |
|---|---|
| `install.bat` | setup dev: venv + pip + camoufox + npm |
| `start.bat` | chạy dev (backend + Electron) |
| `test.bat` | chạy pytest (83 tests) |
| `fetch-browser.bat` | tải lại Camoufox để bundle |
| `build.bat` | build installer |
| `publish.ps1 -Version x.y.z` | bump version + build + upload GitHub Release |
| `make_license.bat` | sinh license key (owner) |

---

## 3. Logic chính

### 3.1. Vòng đời request
`controllers` nhận request → gọi `services` (BrowserManager/PagePool) → đọc/ghi `models` (accounts/config/proxies) → sự kiện UI phát qua `core/events.py` (EventHub → WebSocket → `js/ws.js`).

### 3.2. Browser flow (mở tab)
```
POST /api/browser/open
→ kiểm tra license.max_tabs (còn slot?)
→ BrowserManager.open_sessions(accounts)   # pool không mở trùng account
→ mỗi session: AsyncCamoufox(headless=False) + proxy + UA + locale
→ gắn tên profile vào tab → xếp lưới (compute_grid)
→ push events "opened"/"closed" qua WebSocket
```

### 3.3. Auto-flow state machine
```
SELECT ACC → OPEN+LOGIN → SEARCH ROOM (anchor) → CAPTURE ROOM ID (WS)
→ JOIN BY ROOM ID → TABLE_READY → DISCARD (xả bài)
→ AUTO_OUT? [DONE] : WAIT_GUEST → AUTO_START → DONE
```

### 3.4. License check
Mọi điểm vào mở browser / chạy auto-flow đều gọi `license.max_tabs()` — không có license hợp lệ → chặn (403).

---

## 4. Phát triển

Yêu cầu: Python 3.11+, Node.js 18+.

```powershell
install.bat    # lần đầu: venv + pip + camoufox fetch + npm install
start.bat      # chạy dev hàng ngày
test.bat       # chạy test suite
```

**Build installer**
```powershell
build.bat
```

**Phát hành bản mới**
```powershell
# 1. Sửa version trong app/package.json + backend/models/config_model.py (APP_VERSION)
# 2. build.bat
# 3. Tạo GitHub Release (tag vX.X.X) upload Setup.exe + latest.yml
# hoặc:
publish.ps1 -Version 1.0.4
```

**Sinh license cho khách thuê**
```powershell
# trên máy khách lấy mã máy:
python backend\tools\make_license.py --print-id
# owner sinh key:
python backend\tools\make_license.py --machine-id <guid> --days 30 --max-tabs 10
```

> ⚠️ **Đổi SECRET** trong `backend/license.py` trước khi cho thuê (hiện là placeholder). Mỗi lần đổi, key cũ hết hiệu lực.

---

## 5. API chính

| Method | Endpoint | Chức năng |
|---|---|---|
| GET | `/health` | kiểm tra backend |
| GET | `/api/accounts` | danh sách profile |
| POST | `/api/accounts` | thêm profile |
| POST | `/api/accounts/bulk` | thêm nhanh (prefix+count) |
| POST | `/api/accounts/import` | import tài khoản file txt |
| PATCH | `/api/accounts/{id}` | sửa profile |
| DELETE | `/api/accounts/{id}` | xóa profile (+ dữ liệu đĩa) |
| POST | `/api/accounts/bulk-delete` | xóa hàng loạt |
| POST | `/api/browser/open` | mở tab (kiểm tra max_tabs) |
| POST | `/api/browser/close` | đóng tab |
| POST | `/api/browser/layout` | xếp lưới |
| POST | `/api/check-proxy` | kiểm tra 1 proxy |
| GET/POST | `/api/proxies` | đọc/lưu danh sách proxy |
| POST | `/api/proxies/apply` | áp proxy sống cho profile |
| GET/POST | `/api/license/status`·`activate`·`deactivate` | license |
| GET/POST | `/api/gamesim/*` | Game Sim (start/stop/status/metrics/events) |
| POST | `/api/gamesim/capture` | capture WS (chơi thủ công) |
| GET | `/api/gamesim/ws-capture` | đọc WS messages đã bắt |
| POST | `/api/autoplay/start`·`stop` | auto-flow tìm nhau & xả bài |
| GET | `/api/autoplay/status` | trạng thái auto-flow |

---

## 6. Các công việc cần phát triển tiếp

### 6.1. 🔴 Bắt buộc — tinh chỉnh HITCLUB (cần bạn capture WS)
1. **Capture protocol**: đăng nhập + join bàn 1 ván thủ công, gửi `%APPDATA%\AutoTool_HITCLUB\data\game_sim_debug\ws_capture.jsonl` để tôi phân tích:
   - Regex **room_id** (tách id phòng từ message)
   - **join message template** (để các acc join theo room id)
   - **discard_cmd** (message xả bài)
   - **guest_ready** pattern (khách vào sẵn sàng) + **start_cmd**
2. **Xác định tọa độ click** (nút tìm bàn, vào bàn, xả bài, rời bàn) từ screenshot → điền `game.clicks`
3. Tinh chỉnh `ws_patterns` + logic `_parse_role` trong `hitclub.py` để xác định winner/first-player chính xác

### 6.2. 🟠 Cải tiến Auto-flow
- Tạo room trống nếu game cho phép (thử trước khi nhảy dò)
- Nhiều anchor song song (4–5 acc cùng dò, con nào thấy trước đứng lại)
- Xả bài nhiều vòng liên tiếp theo kịch bản
- Log + screenshot từng bước (đã có DebugCapture, cần gắn vào auto_flow)
- Resume/recovery khi 1 acc mất kết nối giữa chu trình

### 6.3. 🟠 Product hóa
- **Đổi SECRET license** + quy trình sinh/cấp key cho khách thuê
- Quản lý license online (nếu cần): server xác thực key, revoke, gia hạn từ xa
- **Bản B52**: tách `platform_config.py` riêng + brand + logo
- Thống kê sử dụng (số ván xả, tỷ lệ thành công) gửi về owner (tùy chọn)

### 6.4. 🟡 Nâng cấp kỹ thuật
- **Recovery nâng cao** theo error type (reconnect → reopen browser → restart scenario)
- **Multi-table** song song (nhiều room cùng lúc)
- Captcha giải quyết (nếu gặp) — reCAPTCHA enterprise trên HITCLUB
- Tối ưu bộ nhớ khi chạy 10 tab
- Hook login/anti-detect theo từng nền tảng (selenium/camoufox tùy cổng game)

### 6.5. 🟡 Test & chất lượng
- Test end-to-end với game thật (sau khi có capture)
- Test auto-flow trên mock (đã có cho game_sim; thêm cho auto_flow)
- CI: chạy pytest trên push (GitHub Actions)

---

## 7. Bảo mật dữ liệu

`.gitignore` loại khỏi repo:
- `backend/data/` — accounts (nick/pass thật), proxies, config, license, ws_capture, game_sim.db, game_sim_debug
- `.venv/`, `__pycache__/`, `node_modules/`, `release/`, `dist/`

> ⚠️ Không bao giờ commit `backend/data/` và SECRET license thật vào GitHub.

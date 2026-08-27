# AutoTool — Tool đa profile cho game bài

Ứng dụng desktop (Electron + FastAPI + Camoufox) quản lý nhiều profile/tài khoản game, mỗi profile có **fingerprint chống phát hiện riêng**, **proxy riêng**, **session đăng nhập riêng**. Cốt lõi là **Auto-flow tìm nhau & xả bài** cho các cổng game bài (HITCLUB, B52…) với hệ thống **license cho thuê** và **giới hạn tab**.

> Phiên bản hiện tại: **v1.2.0** — bản HITCLUB (`platform_config.py`).

---

> **Trạng thái gần nhất (v1.2.0)**: hoàn thiện phần **login/session token** và **join bàn theo room id (join-by-id)** cho HITCLUB. Chi tiết phần làm mới và danh sách lỗi còn lại xem [Mục 6.6](#66-những-gì-mới-v120-và-lỗi-đã-sửa) và [Mục 7 — Lỗi đang cần sửa](#7--lỗi-đang-cần-sửa).

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

## 2. Những gì đã làm (v1.1.0)

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
| `license-server\start.bat` | chạy License Server (Supabase) + admin dashboard |

### 2.9. License Server — quản lý license cho thuê (mới, v1.1.0)

Hệ thống server quản lý thuê license tập trung, **không cần sửa app** (offline HMAC — server sinh key, app tự xác thực bằng chữ ký):

- **DB**: Supabase (Postgres) — bảng `plans` (gói thuê: tab/giá/ngày), `licenses` (key, machine, khách, hạn, trạng thái), `license_events` (audit log)
- **Admin dashboard SPA** (Chart.js): thống kê doanh thu, license theo gói, cấp phát 30 ngày, danh sách sắp hết hạn
- **Cấp license**: chọn gói + nhập MachineGuid khách → sinh key ngay (giống hệt scheme `backend/license.py`, SECRET phải khớp)
- **Gia hạn / Reset / Thu hồi / Treo**: gia hạn + ngày, reset cấp lại key (đổi máy/tab), thu hồi đẩy `expires_at` về hiện tại để key chết ngay
- **Quản lý gói thuê**: tên gói, số tab tối đa (mặc định 10), giá/tháng, số ngày
- Chi tiết: `license-server/README.md`

### 2.10. Session token + Join bàn theo room id (v1.2.0)

Bổ sung cho phần auto-flow HITCLUB, nhằm khắc phục **"profile vẫn không login được"** và **"2 profile chưa vào chung 1 bàn"**:

- **`game_sim/token_store.py` (mới)**: lưu token login mới nhất theo từng profile vào `DATA_DIR/game_sim_token.json`. Game HITCLUB trả **token MỚI mỗi lần login** (`POST /user/login.aspx` → `token: "1-<32hex>"`), token cũ bị expire → profile mở lại không login được. Token store chỉ ghi khi token **thay đổi** (bắt kịp login mới), là nguồn token tươi nhất.
- **Tự lưu token khi login mới**: gắn vào `HitClubAdapter.join()` (sau khi login đọc `localStorage['token']`), `browser_service.save_open_sessions_storage()` (watchdog định kỳ), và `POST /api/autoplay/session-token` (capture thủ công).
- **Mở lại profile dùng token mới nhất**: `browser_service._open_one` inject `web_storage` nhưng **ghi đè** `token`/`user_token` bằng token tươi từ token store (thay vì token cũ hết hạn trong `web_storage`).
- **Khi đóng, xoá token live**: `close_session` đọc+ghi token mới nhất vào store rồi **xóa `token`/`user_token` khỏi localStorage** để app/editor khác không mang theo session cũ hết hạn.
- **Join bàn theo room id (chính xác)**:
  - `GET /api/autoplay/join-capture` — trích xuất `rooms[]`, `last_room_id`, `join_template` (msg `cmd=308` SEND đã bắt) từ `ws_capture.jsonl`.
  - `POST /api/autoplay/join-by-id` — ép 1 profile join đúng bàn `rid` (ưu tiên gửi qua **game socket đã bắt**; fallback **WS phụ** `join_by_id_side` — mở socket riêng từ page, không reload, không logout).
  - `GET /api/autoplay/list-rooms` — liệt kê bàn `cmd=300` qua kênh phụ, tìm bàn trống `uC=0`.
  - `POST /api/autoplay/reconnect-ws` — toggle offline→online để game **mở lại WS** (bắt socket thật, không reload/logout), dùng cho gửi lệnh join qua socket authenticated của chính account.
- **Không còn reload phá session**: `_page()` và `debug-ws-hook` đã bỏ `page.reload()` (game này **không giữ login qua reload** — login gắn với session WebSocket sống). `debug-ws-hook` chỉ reload khi truyền `reload:true`.
- **Sửa bug parse WS SEND frame**: frame SEND là `[6,"Simms","channelPlugin",{payload}]` → payload ở **index 3** (không phải index 1 như RECV). Helper `_find_cmd_payload(arr)` quét đúng index — trước đây `_capture_room` không bao giờ bắt được template join thật (luôn dùng template đoán cứng).
- **Sửa `_verify_same_room`**: trước đây đọc `cmd=22007.dMs` — đây là **chat**, không phải người chơi. Nay check `cmd=202.ps[].dn` và `cmd=100.dn` (danh sách người chơi thật trong bàn).

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
| POST | `/api/autoplay/debug-ws-hook` | bật WS hook (mặc định KHÔNG reload, thêm `reload:true` để capture từ đầu) |
| POST | `/api/autoplay/join-by-id` | ép 1 profile join đúng bàn `rid` (không reload/logout) |
| GET | `/api/autoplay/list-rooms` | liệt kê bàn (`cmd=300`) qua kênh phụ |
| GET | `/api/autoplay/join-capture` | trích xuất `rooms`/`last_room_id`/`join_template` từ capture |
| POST | `/api/autoplay/reconnect-ws` | toggle offline→online để bắt lại game socket (không reload) |
| POST | `/api/autoplay/session-token` | đọc token login + lưu vào token store |
| POST | `/api/autoplay/send-raw`·`join-rid`·`reload`·`capture` | công cụ debug WS |

---

## 6. Các công việc cần phát triển tiếp

### 6.1. 🔴 Bắt buộc — hoàn thiện join bàn HITCLUB (đang làm)
Đã capture được protocol thật (WS channel `Simms`):
- **Room list**: SEND `cmd=300` `[6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":1}]` → RECV `rs:[{rid,rn,b,uC,...}]` (`uC`=số người).
- **Join bàn**: SEND `cmd=308` `{...,"cmd":308,"rid":<rid>}`.
- **Xác nhận**: RECV `cmd=305/308` → `ri.rid` + `fu.u`; **danh sách người chơi thật nằm ở `cmd=202.ps[].dn`** và `cmd=100.dn` (đã sửa `_verify_same_room` dùng đúng chỗ này).

Còn lại:
- **WS auth cho automation**: token trong `localStorage` (`1-<32hex>`) **bị server WS từ chối** khi dùng kênh phụ ("Xác nhận tài khoản thất bại"). Cần dùng **game socket sống** của account (đã làm `reconnect-ws` để bắt) thay vì mở socket riêng.
- Xác định tọa độ click (nút tìm bàn, vào bàn, xả bài, rời bàn) từ screenshot → điền `game.clicks`.

### 6.2. 🟠 Cải tiến Auto-flow
- Tạo room trống nếu game cho phép (thử trước khi nhảy dò)
- Nhiều anchor song song (4–5 acc cùng dò, con nào thấy trước đứng lại)
- Xả bài nhiều vòng liên tiếp theo kịch bản
- Log + screenshot từng bước (đã có DebugCapture, cần gắn vào auto_flow)
- Resume/recovery khi 1 acc mất kết nối giữa chu trình

### 6.3. 🟠 Product hóa
- **Đổi SECRET license** + quy trình sinh/cấp key cho khách thuê
- ✔ **Đã có License Server** (`license-server/`): cấp/gia hạn/reset/thu hồi online + admin dashboard (Supabase). Tùy chọn: cho app gọi `/api/public/verify` để revoke ngay từ xa
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

## 7. Lỗi đang cần sửa (trạng thái mới nhất)

Danh sách lỗi/vướng mắc phát hiện trong quá trình làm **v1.2.0** (HITCLUB):

### 7.1. 🔴 WS auth cho automation (chặn join tự động)
- Kênh WS phụ (`join_by_id_side`) mở socket tới đúng endpoint (`wss://m-f2.wsmt8g.cc/v3/`) nhưng server từ chối token `localStorage.token` → response **"Xác nhận tài khoản thất bại"**.
- Nguyên nhân khả nghi: game dùng **socket-token ngắn hạn** cấp riêng khi mở WS (không phải `localStorage.token` của login), hoặc token bị expire nhanh.
- Hướng xử lý hiện tại: dùng **game socket sống của account** — `POST /api/autoplay/reconnect-ws` toggle offline→online để game tự mở lại WS, bắt socket authenticated đó, rồi gửi `cmd=308` qua `send_raw`. Cần test end-to-end khi có session login thật.

### 7.2. 🔴 Game không giữ login qua reload
- HITCLUB không auto-login lại sau `page.reload()` dù token vẫn còn trong `localStorage` — login gắn với **session WebSocket sống**.
- Đã sửa: `_page()` và `debug-ws-hook` **không còn reload** (chỉ reload khi `reload:true`). Không gọi reload trên profile đang login.

### 7.3. 🟠 reCAPTCHA chặn login tự động
- Trang game nhúng **Google reCAPTCHA enterprise** (frame `recaptcha/enterprise/anchor`) → login tự động bị chặn, phải login thủ công.
- Chưa có giải pháp tự động; login thủ công 1 lần + token store lưu lại (mục 2.10) giúp lần sau mở lại không cần login lại.

### 7.4. 🟠 Restart backend đóng cửa sổ login
- Khi **restart server** (dev), `close_all` đóng hết session browser → user phải mở + login lại từng profile.
- Tránh restart server trong lúc đang test; hoặc triển khai cơ chế "dev reload không đóng browser" (chưa làm).

### 7.5. 🟡 Lỗi nhỏ đã sửa trong v1.2.0
- Parse WS **SEND** frame sai index (payload ở `arr[3]`, đọc `arr[1]`) → `_capture_room` không bắt được template join thật. Đã sửa bằng `_find_cmd_payload()`.
- `_verify_same_room` đọc `cmd=22007.dMs` (là **chat**) thay vì người chơi → sửa dùng `cmd=202.ps[].dn` + `cmd=100.dn`.
- `_page()`/`debug-ws-hook` reload làm mất login → bỏ reload.

---

## 8. Bảo mật dữ liệu

`.gitignore` loại khỏi repo:
- `backend/data/` — accounts (nick/pass thật), proxies, config, license, ws_capture, game_sim.db, game_sim_debug
- `.venv/`, `__pycache__/`, `node_modules/`, `release/`, `dist/`

> ⚠️ Không bao giờ commit `backend/data/` và SECRET license thật vào GitHub.

---
name: account1-controller
description: >-
  Skill điều khiển toàn bộ vòng đời của Profile "Account 1" trong AutoTool (HITCLUB).
  Bao gồm: mở browser, login, tìm phòng, join bàn, xả bài, lưu session, đóng tab.
  Dùng khi cần thao tác tự động hoặc debug profile đầu tiên (anchor profile).
---

# Skill: Account 1 Controller — AutoTool HITCLUB

Skill này hướng dẫn từng bước để đọc, kiểm tra và điều khiển **Profile Account 1** (profile đầu tiên trong danh sách, thường đóng vai "anchor" — tìm bàn trống trước) trong hệ thống AutoTool.

---

## 0. Kiến trúc cần hiểu trước

```
Electron (app/) ─── REST /api/* + WebSocket /ws ───► FastAPI (backend/)
                                                         ├── controllers/account_controller.py   # CRUD profile
                                                         ├── controllers/browser_controller.py   # Mở/đóng tab
                                                         ├── controllers/auto_flow_controller.py # Auto-flow
                                                         ├── services/browser_service.py         # BrowserManager
                                                         └── models/config_model.py              # accounts.json
```

**Dữ liệu profile** lưu tại:
- Dev: `backend/data/accounts.json`
- Prod (frozen): `%APPDATA%\AutoTool_HITCLUB\data\accounts.json`

**Backend base URL** (local dev): `http://127.0.0.1:8000`

---

## 1. Đọc danh sách profile — tìm Account 1

### 1.1 Gọi API lấy danh sách

```bash
curl http://127.0.0.1:8000/api/accounts
```

Response: array JSON, Account 1 = phần tử có `index: 1` (hoặc `accounts[0]`).

```json
{
  "id": "<uuid>",
  "index": 1,
  "name": "Account 1",
  "url": "https://v.hitclub.latino/?a=hitclub",
  "proxy": "",
  "save_session": true,
  "username": "my_nick",
  "password": "my_pass",
  "profile_dir": "backend/data/profiles/account-1-<short_id>",
  "web_storage": {}
}
```

### 1.2 Đọc từ file (Python)

```python
import json
from pathlib import Path

accounts = json.loads(Path("backend/data/accounts.json").read_text(encoding="utf-8"))
acc1 = accounts[0]  # index 0 = Account 1
print(acc1["id"], acc1["name"])
```

---

## 2. Mở browser cho Account 1

```bash
curl -X POST http://127.0.0.1:8000/api/browser/open \
  -H "Content-Type: application/json" \
  -d '{"account_ids": ["<ACC1_ID>"]}'
```

Response: `{"session_ids": ["<session_id>"]}`

Lỗi 403 = license chưa kích hoạt. Lỗi 429 = đã đủ tab.

### Kiểm tra session

```bash
curl http://127.0.0.1:8000/api/sessions
```

---

## 3. Chụp màn hình để kiểm tra trạng thái

```bash
curl -X POST http://127.0.0.1:8000/api/browser/screenshot \
  -H "Content-Type: application/json" \
  -d '{"account_id": "<ACC1_ID>"}'
```

Ảnh lưu tại `backend/data/game_sim_debug/shot_<...>.png`.

---

## 4. Lưu session login sau khi login thủ công

HITCLUB có reCAPTCHA — phải login thủ công lần đầu. Sau đó lưu token:

```bash
# Endpoint lưu web storage
curl -X POST http://127.0.0.1:8000/api/accounts/<ACC1_ID>/save-session

# Hoặc endpoint autoplay (lưu vào token store)
curl -X POST http://127.0.0.1:8000/api/autoplay/session-token \
  -H "Content-Type: application/json" \
  -d '{"profile_name": "Account 1"}'
```

Token lưu vào `backend/data/game_sim_token.json` — dùng lại lần sau.

---

## 5. Bật WS Sniffer (bắt WebSocket)

Cần hook WebSocket trước khi tìm phòng / join bàn:

```bash
# KHÔNG reload — giữ session login
curl -X POST http://127.0.0.1:8000/api/autoplay/debug-ws-hook \
  -H "Content-Type: application/json" \
  -d '{"profile_name": "Account 1", "reload": false}'
```

Chỉ dùng `"reload": true` khi cần capture từ đầu (trước login) — sẽ mất login.

---

## 6. Tìm phòng trống (Account 1 = anchor)

```bash
# Liệt kê bàn qua kênh phụ (cmd=300)
curl http://127.0.0.1:8000/api/autoplay/list-rooms

# Đọc capture đã bắt được
curl http://127.0.0.1:8000/api/autoplay/join-capture
```

Response join-capture:
```json
{
  "rooms": [{"rid": 123, "rn": "Bàn 1", "uC": 0}],
  "last_room_id": 123,
  "join_template": "[6,\"Simms\",\"channelPlugin\",{\"cmd\":308,\"rid\":123,...}]"
}
```

Bàn trống = `uC == 0`.

---

## 7. Join bàn theo room id

```bash
curl -X POST http://127.0.0.1:8000/api/autoplay/join-by-id \
  -H "Content-Type: application/json" \
  -d '{"profile_name": "Account 1", "rid": 123}'
```

Nếu WS auth fail → reconnect trước:

```bash
# Toggle offline→online để game mở lại WS
curl -X POST http://127.0.0.1:8000/api/autoplay/reconnect-ws \
  -H "Content-Type: application/json" \
  -d '{"profile_name": "Account 1"}'
```

---

## 8. Auto-flow đầy đủ (Account 1 + acc phụ)

```bash
# Start
curl -X POST http://127.0.0.1:8000/api/autoplay/start \
  -H "Content-Type: application/json" \
  -d '{"accounts": ["Account 1", "Account 2", "Account 3"], "auto_out": true}'

# Status
curl http://127.0.0.1:8000/api/autoplay/status

# Stop
curl -X POST http://127.0.0.1:8000/api/autoplay/stop
```

State machine: `OPEN+LOGIN → SEARCH ROOM (anchor) → CAPTURE WS → JOIN BY ID → DISCARD → DONE`

---

## 9. Evaluate JavaScript trên page Account 1

```bash
# Đọc token
curl -X POST http://127.0.0.1:8000/api/browser/eval \
  -H "Content-Type: application/json" \
  -d '{"account_id": "<ACC1_ID>", "js": "localStorage.getItem(\"token\")"}'

# Kiểm tra URL hiện tại
curl -X POST http://127.0.0.1:8000/api/browser/eval \
  -H "Content-Type: application/json" \
  -d '{"account_id": "<ACC1_ID>", "js": "location.href"}'

# Toàn bộ localStorage
curl -X POST http://127.0.0.1:8000/api/browser/eval \
  -H "Content-Type: application/json" \
  -d '{"account_id": "<ACC1_ID>", "js": "JSON.stringify(Object.fromEntries(Object.keys(localStorage).map(k=>[k,localStorage[k]])))"}'
```

---

## 10. Cập nhật Account 1

```bash
# Đổi proxy
curl -X PATCH http://127.0.0.1:8000/api/accounts/<ACC1_ID> \
  -H "Content-Type: application/json" \
  -d '{"proxy": "1.2.3.4:8080:user:pass"}'

# Đổi credentials
curl -X PATCH http://127.0.0.1:8000/api/accounts/<ACC1_ID> \
  -H "Content-Type: application/json" \
  -d '{"username": "my_nick", "password": "my_pass"}'
```

---

## 11. Đóng tab Account 1

```bash
curl -X POST http://127.0.0.1:8000/api/browser/close \
  -H "Content-Type: application/json" \
  -d '{"session_ids": ["<SESSION_ID>"]}'
```

Backend tự lưu token + localStorage vào profile_dir trước khi đóng. KHÔNG cần xóa thủ công.

---

## 12. Xóa Account 1

```bash
# Xóa profile + dữ liệu đĩa (cookies, profile_dir)
curl -X DELETE http://127.0.0.1:8000/api/accounts/<ACC1_ID>
```

---

## 13. Debug checklist — khi Account 1 gặp sự cố

Chạy theo thứ tự:

1. `GET /api/sessions` — session có mở không?
2. `POST /api/browser/screenshot` — đang ở trang nào?
3. `POST /api/browser/eval` với `js: "localStorage.getItem('token')"` — token còn không?
4. `POST /api/autoplay/debug-ws-hook` (reload: false) — cắm WS hook
5. `GET /api/autoplay/list-rooms` — thấy bàn không?
6. `GET /api/autoplay/join-capture` — có join_template không?
7. `POST /api/autoplay/reconnect-ws` — nếu WS auth fail
8. `POST /api/autoplay/join-by-id` với rid — thử join lại

---

## 14. File quan trọng

| File | Vai trò |
|------|---------|
| `backend/controllers/account_controller.py` | CRUD profile API |
| `backend/controllers/browser_controller.py` | Mở/đóng browser tab |
| `backend/controllers/auto_flow_controller.py` | Auto-flow + WS + join-by-id |
| `backend/services/browser_service.py` | BrowserManager (Chromium session) |
| `backend/models/config_model.py` | load/save accounts.json, profile_dir |
| `backend/data/accounts.json` | Danh sách profile (runtime) |
| `backend/data/game_sim_token.json` | Token store tươi nhất |
| `backend/data/game_sim_debug/ws_capture.jsonl` | WS capture log |

---

## 15. Gotchas quan trọng

- **KHÔNG reload** sau khi đã login — HITCLUB mất session WS → phải login lại.
- **Token mới mỗi lần login** (`1-<32hex>`) — gọi `save-session` ngay sau login.
- **WS phụ bị từ chối** khi dùng `localStorage.token` → dùng `reconnect-ws` để bắt socket sống.
- **Không restart backend** trong lúc test — `close_all` đóng hết session, mất login.
- **reCAPTCHA**: không bypass tự động được → login thủ công lần đầu, sau đó token store lo.

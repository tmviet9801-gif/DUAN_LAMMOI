# Game Room Lifecycle Simulator - Kế hoạch thiết kế

Hệ thống tự động hóa mô phỏng vòng đời phòng game và kiểm thử **quyền đi trước**
(người thắng ván trước được đi trước ván tiếp theo), chạy trên nền các profile
Camoufox có sẵn của ứng dụng.

## 1. Kiến trúc hệ thống

```
┌────────────────────────────────────────────────────────────────┐
│  Renderer (Electron)                                            │
│  view-game-sim: Start/Stop, trạng thái nhóm, metrics            │
└───────────────┬────────────────────────────────────────────────┘
                │ REST /api/gamesim/*         (FastAPI)
┌───────────────▼────────────────────────────────────────────────┐
│  game_sim/manager.py  (GameSimManager - singleton)              │
│    └─ scheduler.py (Scheduler: 1 task / nhóm, chạy song song)   │
│         └─ states.py (GameRoomMachine - FSM 11 trạng thái)      │
│              └─ state_machine.py (engine FSM generic)           │
│                   └─ game_adapter.py (Mock / Selector adapter)  │
│  account_pool.py (round-robin, busy/cooldown)                   │
│  metrics.py (collector)                                          │
│  storage.py (SQLite: runs/events/rounds)                         │
└────────────────────────────────────────────────────────────────┘
                │ dùng BrowserManager mở tab profile → join bàn
┌───────────────▼────────────────────────────────────────────────┐
│  services/browser_service.py (Camoufox sessions)                │
└────────────────────────────────────────────────────────────────┘
```

## 2. State Machine chi tiết (11 trạng thái)

```
 IDLE ──start──▶ JOINING ──joined──▶ WAITING_FOR_TABLE
                        │                │ table_ready
                        │ join_failed    ▼
                        ▼             BOOTSTRAP_ROUND ──round_ready──▶ PLAYING
                      RETRY ◀─────────────┐              │ round_end
                        │                │              ▼
              retry_ok (quay lại nơi lỗi)│          VERIFYING_RESULT
                        │                │            │ main_won / main_lost
                    retry_exhausted      │            ▼
                        ▼                │          LEAVING ──support_left──▶ WAITING_NEXT_PLAYER
                      ERROR ◀────────────┘            │ main_left              │ player_joined
                        ▲                            ▼                        ▼
                  recover │                       RESETTING ──reset_done──▶ BOOTSTRAP_ROUND
                          └──── RETRY ◀────────── reset_failed             (vòng mới)
```

| Trạng thái | Ý nghĩa | Timeout | Retry tối đa | Event ra |
|---|---|---|---|---|
| IDLE | sẵn sàng | - | - | start |
| JOINING | main + support join bàn | 15s | 3 | joined / join_failed |
| WAITING_FOR_TABLE | chờ đủ người | 15s | 3 | table_ready / timeout |
| BOOTSTRAP_ROUND | set trạng thái bàn cho ván test | 10s | 3 | round_ready / failed |
| PLAYING | chạy 1 ván test | 60s | 3 | round_end |
| VERIFYING_RESULT | xác minh người thắng + first player | 10s | 3 | main_won / main_lost / verify_failed |
| LEAVING | support (main_won) hoặc main (main_lost) rời bàn | 10s | 3 | support_left / main_left |
| WAITING_NEXT_PLAYER | chờ support kế vào thay | 20s | 3 | player_joined / timeout |
| RESETTING | reset trạng thái bàn | 10s | 3 | reset_done / reset_failed |
| RETRY | thử lại sau lỗi/timeout | - | 3 | retry_ok / retry_exhausted |
| ERROR | lỗi không phục hồi | - | - | recover |

Mỗi transition có: điều kiện, timeout, retry tối đa, log chi tiết (event_id,
session_id, group, state_from→state_to), recovery khi disconnect.

## 3. JSON config

```json
{
  "scenario": "winner_keeps_first_move",
  "rounds": 10,
  "table": { "url": "https://game.example.com/room" },
  "game": {
    "adapter": "mock",
    "force": "auto",
    "selectors": {
      "join": "#btn-join",
      "leave": "#btn-leave",
      "ready": ".table-ready",
      "winner": ".winner-name"
    }
  },
  "groups": {
    "A": { "main": "A", "supports": ["A1", "A2", "A3"] },
    "B": { "main": "B", "supports": ["B1", "B2", "B3"] }
  },
  "timing": {
    "join_timeout": 15, "table_wait": 15, "play_timeout": 60,
    "verify_timeout": 10, "leave_timeout": 10, "next_player_wait": 20,
    "reset_timeout": 10, "cooldown": 5, "retry_max": 3
  }
}
```

`groups` dùng tên profile có sẵn trong app (khớp `accounts.json`). Không
hard-code số lượng support — pool quản lý vòng tròn.

## 4. SQLite schema

```sql
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, group_name TEXT, scenario TEXT, status TEXT,
  started_at TEXT, finished_at TEXT,
  total_rounds INT, main_first INT, main_not_first INT, first_move_accuracy REAL,
  join_ok INT, join_fail INT, timeouts INT, reconnects INT, pass INT, fail INT
);
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, group_name TEXT, session_id TEXT, event_id TEXT,
  state_from TEXT, state_to TEXT, message TEXT, ts TEXT
);
CREATE TABLE rounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, group_name TEXT, round_no INT,
  first_player TEXT, winner TEXT, expected_first TEXT, pass INT, ts TEXT
);
```

## 5. Pseudocode — Scheduler

```
for group in config.groups:
    machine = GameRoomMachine(group, adapter, pool)
    task = create_task(run_group(machine, group, rounds, stop_event))

async run_group(machine, group, rounds, stop_event):
    machine.start()
    while not stop_event and machine.rounds_done < rounds and machine.state != ERROR:
        event = await wait_any(machine.next_event(), timeout=state_timeout)
        machine.trigger(event)
    machine.trigger("stop")
    storage.save_run(machine.metrics)
```

## 6. Pseudocode — Account Pool Manager

```
Pool(groups):
    for each group: deque(supports)  # vòng tròn
next_support(group, exclude=set()):
    for _ in range(len(deque)):
        acc = deque.rotate(1)  # round-robin
        if acc free and not cooldown and acc not in exclude: mark busy; return acc
    raise PoolExhausted
mark_free(acc); mark_cooldown(acc, seconds); skip busy/cooldown
```

## 7. Pseudocode — State Machine

```
trigger(event):
    tr = states[current].transitions[event]
    if tr.condition and not tr.condition(ctx): log; return
    emit_event(event_id, session_id, current, tr.target)
    current = tr.target
    await states[current].on_enter(ctx)   # action có thể emit event tiếp
timeout_watch(state):
    await sleep(state.timeout)
    trigger("timeout")
retry logic: RETRY đếm trong ctx["retry"]; > retry_max → ERROR
recovery: JOINING/PLAYING bắt disconnect → emit reconnect → RETRY/quay lại
```

## 8. Logging & recovery

- Log mỗi transition: `[run:{run_id} group:{group} session:{sid} event:{event_id}] state → state msg`.
- Disconnect: adapter trả `reconnect_failed` → RETRY → ERROR; hoặc `reconnected` → quay lại state cũ (ctx["retry_target"]).
- Mọi sự kiện ghi vào bảng `events` để truy vết.

## 9. Dashboard metrics

Tổng ván, số lần MAIN đi trước, số lần không đi trước, tỷ lệ giữ quyền đi trước,
join thành công/thất bại, thời gian trung bình/chu kỳ, số timeout, số reconnect,
tỷ lệ scenario pass/fail. Hiển thị ở view-game-sim.

## 10. Unit test

- test_state_machine: transition hợp lệ / không hợp lệ / timeout→retry→error /
  retry cạn / recovery.
- test_account_pool: round-robin, bỏ qua busy/cooldown, pool cạn.
- test_scenario_mock: chạy scenario mock 2 nhóm, verify MAIN giữ first move khi thắng,
  reset khi thua.

## Mở rộng

- Nhiều nhóm: mỗi nhóm 1 machine độc lập (scheduler song song).
- Nhiều phòng: `table.url` + group → mỗi group 1 phòng; hoặc `rooms: [{url, groups:[...]}]`.
- Adapter mới: chỉ cần implement `GameAdapter` interface, cấu hình qua `game.adapter`.

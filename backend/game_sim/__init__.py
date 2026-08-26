"""Hệ thống mô phỏng vòng đời phòng game (State Machine).

Kiến trúc:
- state_machine.py: engine FSM generic (timeout/retry/recovery, event queue).
- states.py: 11 trạng thái + transitions của vòng đời phòng game.
- account_pool.py: quản lý tài khoản support round-robin.
- game_adapter.py: interface adapter + Mock + Selector (Playwright).
- metrics.py: thu thập metrics.
- storage.py: lưu SQLite (runs/events/rounds).
- scheduler.py: chạy scenario cho từng nhóm.
- manager.py: GameSimManager điều phối toàn hệ thống.
"""

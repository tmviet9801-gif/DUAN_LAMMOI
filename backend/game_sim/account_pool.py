"""Account Pool Manager — quản lý tài khoản support round-robin.

Không hard-code số lượng tài khoản: đọc từ config JSON.
"""
import time
from collections import deque
from typing import Optional


class AccountPool:
    def __init__(self, groups_config: dict):
        self.groups = {}
        for name, g in (groups_config or {}).items():
            self.groups[name] = {
                "main": g.get("main"),
                "queue": deque(g.get("supports") or []),
            }
        self.busy = {}      # account -> group
        self.cooldown = {}  # account -> unix ts sẵn sàng lại

    def next_support(self, group: str, exclude=None, cooldown_s: float = 0) -> Optional[str]:
        """Trả support kế theo round-robin, bỏ qua busy/cooldown/exclude."""
        entry = self.groups.get(group)
        if not entry:
            return None
        exclude = set(exclude or [])
        q = entry["queue"]
        if not q:
            return None
        for _ in range(len(q)):
            acc = q.popleft()
            q.append(acc)  # xoay vòng
            if acc in exclude:
                continue
            if acc in self.busy:
                continue
            cd = self.cooldown.get(acc, 0)
            if cd and time.time() < cd:
                continue
            self.busy[acc] = group
            return acc
        return None

    def current_support_rotation(self, group: str) -> list:
        entry = self.groups.get(group)
        return list(entry["queue"]) if entry else []

    def mark_busy(self, account: str, group: str):
        self.busy[account] = group

    def release(self, account: str, cooldown_s: float = 0):
        self.busy.pop(account, None)
        if cooldown_s:
            self.cooldown[account] = time.time() + cooldown_s

    def reset(self):
        self.busy.clear()
        self.cooldown.clear()

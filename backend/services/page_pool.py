"""PagePool — kết nối BrowserManager với game_sim adapter.

Mở session cho mỗi account (profile) và trả về Playwright Page để adapter
điều khiển (login, join bàn, chơi ván, verify winner…).
"""
import logging
from typing import Optional

from services.browser_service import BrowserManager

log = logging.getLogger("page_pool")


class PagePool:
    def __init__(self, browser_manager: BrowserManager):
        self.manager = browser_manager

    def _find_session(self, account: dict | str) -> Optional[str]:
        if isinstance(account, str):
            acc_id = account
            acc_name = account.strip().lower().replace(" ", "")
        else:
            acc_id = account.get("id") if isinstance(account, dict) else None
            acc_name = (account.get("name") or "").strip().lower().replace(" ", "") if isinstance(account, dict) else ""

        for sid, s in self.manager.sessions.items():
            if not s.account:
                continue
            if acc_id and s.account.get("id") == acc_id:
                return sid
            s_name = (s.account.get("name") or "").strip().lower().replace(" ", "")
            if acc_name and s_name == acc_name:
                return sid
        return None

    def peek(self, account: dict | str) -> Optional[object]:
        """Trả Page NẾU session đã mở sẵn; KHÔNG mở mới.

        Dùng cho Check Live: mục đích của nó là đọc trạng thái mà không bật
        Chrome lên. `get_or_open` sẽ mở profile — đúng thứ cần tránh.
        """
        sid = self._find_session(account)
        if not sid:
            return None
        s = self.manager.sessions.get(sid)
        return s.page if s else None

    async def get_or_open(self, account: dict) -> Optional[object]:
        """Trả về Playwright Page cho account. Mở session mới nếu chưa có."""
        sid = self._find_session(account)
        if sid:
            return self.manager.sessions[sid].page
        ids = await self.manager.open_sessions(accounts=[account])
        if ids:
            s = self.manager.sessions.get(ids[0])
            if s:
                log.info("page_pool opened session %s for %s", ids[0], account.get("name"))
                return s.page
        return None

    async def close(self, session_id: str):
        if session_id in self.manager.sessions:
            await self.manager.close_session(session_id)

    async def close_all(self):
        for sid in list(self.manager.sessions.keys()):
            await self.manager.close_session(sid)
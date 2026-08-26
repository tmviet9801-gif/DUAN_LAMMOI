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

    def _find_session(self, account_id: str) -> Optional[str]:
        for sid, s in self.manager.sessions.items():
            if s.account and s.account.get("id") == account_id:
                return sid
        return None

    async def get_or_open(self, account: dict) -> Optional[object]:
        """Trả về Playwright Page cho account. Mở session mới nếu chưa có."""
        sid = self._find_session(account.get("id"))
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
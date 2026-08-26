"""Auto Flow — chu trình tự động cho game bài (HITCLUB).

Chu trình:
  1. TICK acc tham gia → mở trang game, login, vào lobby.
  2. TÌM BÀN TRỐNG: mỗi acc nhảy tìm/tạo bàn trống.
     - Acc đầu tiên thấy bàn trống = ANCHOR (đứng lại), bắt room id qua WS.
     - Các acc khác JOIN theo room id (gửi lại message join đã bắt).
  3. TABLE_READY → XẢ BÀI: gửi message/click xả (cấu hình).
     - auto_out: xả xong tự rời bàn.
     - auto_start: chờ khách vào sẵn sàng (WS event) rồi tự bắt đầu.
  4. DONE — chu trình kết thúc; muốn xả tiếp thì tick lại.

WS protocol chưa biết → mọi message/pattern đọc từ config (`game.ws_patterns`,
`game.clicks`). Sau khi capture được ws_capture.jsonl, tinh chỉnh config.
"""
import asyncio
import json
import logging
import uuid

from core.time_utils import utcnow_iso
from game_sim.ws_sniffer import WsSniffer
from models.config_model import DATA_DIR

log = logging.getLogger("auto_flow")

PHASE_LABELS = {
    "IDLE": "Chưa chạy",
    "OPENING": "Mở trang / login",
    "SEARCHING": "Tìm bàn trống",
    "ANCHOR": "Đã thấy bàn (anchor)",
    "JOINING": "Join theo room id",
    "TABLE_READY": "Bàn đã đủ",
    "DISCARDING": "Xả bài",
    "WAITING_GUEST": "Chờ khách",
    "AUTO_START": "Tự bắt đầu",
    "DONE": "Hoàn tất",
    "ERROR": "Lỗi",
}


class AutoFlow:
    """Quản lý chu trình cho 1 nhóm acc (anchor + joiners)."""

    def __init__(self, run_id, adapter, config):
        self.run_id = run_id
        self.adapter = adapter  # HitClubAdapter (có sniffer, page_pool)
        self.config = config
        self.game = config.get("game", {})
        self.patterns = self.game.get("ws_patterns", {})
        self.clicks = self.game.get("clicks", {})
        self.auto_out = bool(config.get("auto_out", True))
        self.auto_start = bool(config.get("auto_start", False))
        self.phase = "IDLE"
        self.anchor = None
        self.members = []  # [{name, phase, error}]
        self.logs = []
        self.stop_event = asyncio.Event()
        self._room_id = None
        self._join_template = None

    # ---- helpers ----
    def _add_log(self, msg):
        entry = {"ts": utcnow_iso(), "msg": msg}
        self.logs.append(entry)
        if len(self.logs) > 200:
            self.logs = self.logs[-200:]
        log.info("[%s] %s", self.run_id, msg)

    def _set_phase(self, phase):
        self.phase = phase
        self._add_log(f"PHASE -> {phase}")

    async def _sniff(self, page):
        await self.adapter.sniffer.drain(page)

    # ---- main flow ----
    async def run(self, profile_names: list[str]):
        self._set_phase("OPENING")
        # 1) mở trang + login cho tất cả
        for name in profile_names:
            if self.stop_event.is_set():
                return
            try:
                ok = await self.adapter.join({"group_name": "auto", "main_account": name}, name)
                self.members.append({"name": name, "phase": "OPENED" if ok else "ERROR"})
            except Exception as e:
                self.members.append({"name": name, "phase": "ERROR", "error": str(e)[:120]})

        # 2) tìm bàn trống: mỗi acc nhảy; acc đầu thấy = anchor
        self._set_phase("SEARCHING")
        anchor = None
        for m in self.members:
            if self.stop_event.is_set():
                return
            if m["phase"] == "ERROR":
                continue
            name = m["name"]
            page = await self.adapter._page(name)
            found = await self.adapter._click(page, "find_table_btn")
            await asyncio.sleep(float(self.game.get("search_wait", 2)))
            if found:
                anchor = name
                m["phase"] = "ANCHOR"
                break
        if not anchor:
            self._set_phase("ERROR")
            self._add_log("Không acc nào tìm thấy bàn trống")
            return
        self.anchor = anchor
        self._set_phase("ANCHOR")
        self._add_log(f"Anchor = {anchor} — bắt room id qua WS")

        # bắt room id + template join từ anchor
        await asyncio.sleep(float(self.game.get("room_wait", 3)))
        await self.adapter._capture_room({"main_account": anchor, "support_account": ""})
        self._room_id = self.adapter._room_id
        self._join_template = self.adapter._join_template
        self._add_log(f"room_id={self._room_id} template={bool(self._join_template)}")

        # 3) các acc còn lại join theo room id
        self._set_phase("JOINING")
        for m in self.members:
            if m["name"] == anchor or m["phase"] == "ERROR":
                continue
            page = await self.adapter._page(m["name"])
            ok = await self.adapter._join_room_by_id(page) if self._join_template else await self.adapter._click(page, "join_btn")
            m["phase"] = "JOINED" if ok else "ERROR"
        self._set_phase("TABLE_READY")
        await asyncio.sleep(float(self.game.get("table_wait", 3)))

        # 4) xả bài
        self._set_phase("DISCARDING")
        for m in self.members:
            if m["phase"] == "ERROR":
                continue
            page = await self.adapter._page(m["name"])
            await self.adapter._click(page, "discard_btn")
            # nếu có ws_patterns.discard_cmd thì gửi message
            cmd = self.patterns.get("discard_cmd")
            if cmd and self._room_id:
                msg = self._join_template.replace("{room_id}", str(self._room_id)) if self._join_template else cmd
                await self.adapter.sniffer.send_raw(page, msg)
        self._add_log("Đã xả bài")

        if self.auto_out:
            self._set_phase("DONE")
            self._add_log("auto_out: tự rời — chu trình kết thúc")
            return

        # 5) chờ khách + tự bắt đầu
        self._set_phase("WAITING_GUEST")
        for _ in range(int(self.game.get("guest_wait_max", 120))):
            if self.stop_event.is_set():
                return
            await asyncio.sleep(1)
            page = await self.adapter._page(self.anchor)
            await self._sniff(page)
            msgs = self.adapter.sniffer.recent(limit=300)
            guest_key = self.patterns.get("guest_ready", ["sansang", "ready"])
            found = any(g in it.get("text", "").lower() for it in msgs for g in guest_key)
            if found:
                self._set_phase("AUTO_START")
                self._add_log("Khách đã sẵn sàng — tự bắt đầu")
                start_cmd = self.patterns.get("start_cmd")
                if start_cmd:
                    await self.adapter.sniffer.send_raw(page, start_cmd)
                else:
                    await self.adapter._click(page, "start_btn")
                break
        if self.phase == "WAITING_GUEST":
            self._add_log("Hết thời gian chờ khách")
        self._set_phase("DONE")

    def stop(self):
        self.stop_event.set()

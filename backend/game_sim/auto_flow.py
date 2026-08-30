"""Auto Flow — chu trình tự động cho game bài (HITCLUB).

Chu trình:
  1. TICK acc tham gia → mở trang game, login, vào lobby.
  2. TÌM BÀN TRỐNG: mỗi acc nhảy tìm/tạo bàn trống.
     - Acc đầu tiên thấy bàn trống = ANCHOR (đứng lại), bắt room id qua WS.
     - Các acc khác JOIN theo room id (gửi lại message join đã bắt).
  3. TABLE_READY → XẢ BÀI: click nút xả (tọa độ) và/hoặc gửi ws discard_cmd.
     - auto_out: xả xong tự rời bàn.
     - auto_start: chờ khách vào sẵn sàng (WS event) rồi tự bắt đầu.
  4. DONE — chu trình kết thúc; muốn xả tiếp thì tick lại.

Chế độ CAPTURE (`game.capture=true`): chỉ mở profile + bật WS sniffer, để user
chơi thủ công 1 ván → phân tích ws_capture.jsonl sau.

Mọi tọa độ click / ws_patterns đọc từ config (`game.clicks`, `game.ws_patterns`)
— lưu qua API `POST /api/autoplay/config` để chỉnh không cần sửa code.
"""
import asyncio
import logging

from core.time_utils import utcnow_iso

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
    "CAPTURE": "Capture protocol (chơi thủ công)",
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
        self.capture = bool(self.game.get("capture", False))
        self.discard_repeat = max(1, int(self.game.get("discard_repeat", 1)))
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

    def _sync_room(self):
        """Đồng bộ room_id + join_template từ flow xuống adapter.

        BUG cũ: flow set `adapter._room_id` nhưng KHÔNG set `adapter._join_template`
        nên `_join_room_by_id` luôn trả False (không gửi được lệnh join).
        """
        self.adapter._room_id = self._room_id
        self.adapter._join_template = self._join_template

    async def _shot_all(self, label):
        """Chụp màn hình tất cả profile ở 1 bước (để debug canvas)."""
        for m in self.members:
            try:
                page = await self.adapter._page(m["name"])
                if page:
                    await self.adapter._screenshot(page, f"{label}_{m['name']}")
            except Exception:
                pass

    # ---- các bước ----
    async def _open_profiles(self, profile_names):
        self._set_phase("OPENING")
        for name in profile_names:
            if self.stop_event.is_set():
                return False
            try:
                ok = await self.adapter.join({"group_name": "auto", "main_account": name}, name, auto_find_table=False)
                self.members.append({"name": name, "phase": "OPENED" if ok else "ERROR"})
            except Exception as e:
                self.members.append({"name": name, "phase": "ERROR", "error": str(e)[:120]})
        await self._shot_all("open")
        ok_count = sum(1 for m in self.members if m["phase"] != "ERROR")
        self._add_log(f"Mở {ok_count}/{len(self.members)} profile")
        if not ok_count:
            self._set_phase("ERROR")
            self._add_log("Không mở được profile nào — kiểm tra tọa độ login/create_room/find_table")
            return False
        return True

    def _build_join_template(self, room: dict):
        """Dựng template join theo protocol THẬT: [3,"Simms",1,"{room_id}"]."""
        return '[3,"Simms",1,"{room_id}"]'

    async def _find_anchor(self):
        """Tìm acc ANCHOR: acc vào 1 bàn TRỐNG (uC=0) qua WS (cmd=305 room list)
        + join cmd=308. Không phụ thuộc click tọa độ (account đã login sẵn).

        Nếu chưa có bàn trống: LẶP LẠI tìm (nhiều vòng, chờ giữa các vòng) cho
        tới khi A vào được bàn trống — sau đó mới đến bước B join.
        """
        self._set_phase("SEARCHING")
        max_cycles = max(1, int(self.game.get("search_max_cycles", 8)))
        for cycle in range(max_cycles):
            if self.stop_event.is_set():
                return None
            for m in self.members:
                if m["phase"] == "ERROR":
                    continue
                name = m["name"]
                page = await self.adapter._page(name)
                if not page:
                    continue
                room = await self.adapter._find_empty_room(page, max_tries=3, wait=2, strict=True)
                if not room:
                    continue  # chưa có bàn trống -> member kế tiếp / vòng sau
                rid = room["rid"]
                self._join_template = self._build_join_template(room)
                self._room_id = rid
                self._sync_room()
                if not await self.adapter._join_room_by_id(page):
                    self._add_log(f"{name}: gửi join bàn {rid} thất bại (vòng {cycle + 1}/{max_cycles})")
                    continue
                # Xác minh A thực sự vào bàn (cmd=305/308 recv ri.rid)
                entered = await self.adapter._page_current_room(page)
                if entered != rid:
                    await asyncio.sleep(float(self.game.get("join_wait", 2)))
                    await self.adapter._join_room_by_id(page)
                    entered = await self.adapter._page_current_room(page)
                if entered != rid:
                    self._add_log(f"{name}: chưa xác nhận vào bàn {rid} (current={entered}, vòng {cycle + 1})")
                    continue
                m["phase"] = "ANCHOR"
                await self.adapter._screenshot(page, "hitclub_anchor")
                self._add_log(f"Anchor = {name} — empty room rid={rid}")
                return name
            self._add_log(f"Vòng {cycle + 1}/{max_cycles}: chưa có bàn trống — chờ và tìm lại")
            await asyncio.sleep(float(self.game.get("search_wait", 3)))
        return None

    async def _capture_room(self):
        await asyncio.sleep(float(self.game.get("room_wait", 3)))
        await self.adapter._capture_room({"main_account": self.anchor, "support_account": ""})
        self._room_id = self.adapter._room_id
        self._join_template = self.adapter._join_template
        self._sync_room()
        self._add_log(f"room_id={self._room_id} template={bool(self._join_template)}")

    async def _join_members(self):
        self._set_phase("JOINING")
        self._sync_room()
        for m in self.members:
            if m["name"] == self.anchor or m["phase"] == "ERROR":
                continue
            page = await self.adapter._page(m["name"])
            if not page:
                m["phase"] = "ERROR"
                continue
            self._sync_room()
            ok = await self.adapter._join_room_by_id(page) if self._join_template else False
            m["phase"] = "JOINED" if ok else "ERROR"
            if not ok:
                self._add_log(f"{m['name']}: join bàn {self._room_id} thất bại — thử lại")
        self._set_phase("TABLE_READY")
        await asyncio.sleep(float(self.game.get("table_wait", 3)))
        # Xác nhận tất cả member đã vào cùng 1 phòng với anchor
        joined = [m["name"] for m in self.members if m["phase"] != "ERROR"]
        same = await self.adapter._verify_same_room(joined) if len(joined) >= 2 else False
        if not same:
            self._add_log("Chưa xác nhận cùng phòng — thử join lại lần nữa")
            retry = 0
            while retry < 3 and not same:
                for m in self.members:
                    if m["name"] == self.anchor or m["phase"] == "ERROR":
                        continue
                    page = await self.adapter._page(m["name"])
                    if page:
                        self._sync_room()
                        await self.adapter._join_room_by_id(page)
                await asyncio.sleep(float(self.game.get("join_wait", 2)))
                same = await self.adapter._verify_same_room(joined)
                retry += 1
            if not same:
                self._add_log("Vẫn chưa cùng phòng sau retry")
        await self._shot_all("table_ready")

    async def _discard(self):
        self._set_phase("DISCARDING")
        for rep in range(self.discard_repeat):
            for m in self.members:
                if m["phase"] == "ERROR":
                    continue
                page = await self.adapter._page(m["name"])
                if not page:
                    continue
                ok = await self.adapter._discard_cards(page, m["name"])
                m["phase"] = "DISCARDED" if ok else m.get("phase", "OPENED")
            self._add_log(f"Xả bài vòng {rep + 1}/{self.discard_repeat}")

    async def _wait_guest(self):
        self._set_phase("WAITING_GUEST")
        for _ in range(int(self.game.get("guest_wait_max", 120))):
            if self.stop_event.is_set():
                return
            await asyncio.sleep(1)
            page = await self.adapter._page(self.anchor)
            if not page:
                continue
            await self._sniff(page)
            from game_sim.ws_sniffer import _PAGE_RECV

            msgs = _PAGE_RECV.get(id(page), []) or []
            guest_keys = self.patterns.get("guest_ready", ["sansang", "ready"])
            found = any(g in it.get("text", "").lower() for it in msgs for g in guest_keys)
            if found:
                self._set_phase("AUTO_START")
                self._add_log("Khách đã sẵn sàng — tự bắt đầu")
                start_cmd = self.patterns.get("start_cmd")
                if start_cmd:
                    await self.adapter.sniffer.send_raw(page, start_cmd)
                else:
                    await self.adapter._click_retry(page, "start_btn", attempts=3)
                return
        self._add_log("Hết thời gian chờ khách")

    # ---- main flow ----
    async def run(self, profile_names: list[str]):
        if not await self._open_profiles(profile_names):
            return

        if self.capture:
            self._set_phase("CAPTURE")
            self._add_log("Chế độ CAPTURE: chơi thủ công để ghi protocol. Dừng khi xong.")
            while not self.stop_event.is_set():
                await asyncio.sleep(2)
                for m in self.members:
                    page = await self.adapter._page(m["name"])
                    if page:
                        await self._sniff(page)
            self._set_phase("DONE")
            return

        # 2) tìm bàn trống: acc đầu thấy = anchor
        self.anchor = await self._find_anchor()
        if not self.anchor:
            self._set_phase("ERROR")
            self._add_log("Không acc nào tìm thấy bàn trống — kiểm tra tọa độ find_table_btn / ws_patterns.table_found")
            await self._shot_all("search_fail")
            return
        self._set_phase("ANCHOR")

        # 3) bắt room id + join
        if not self._room_id:
            await self._capture_room()
        await self._join_members()

        # 4) xả bài
        await self._discard()

        if self.auto_out:
            self._set_phase("DONE")
            self._add_log("auto_out: tự rời — chu trình kết thúc")
            return

        # 5) chờ khách + tự bắt đầu
        await self._wait_guest()
        self._set_phase("DONE")

    def stop(self):
        self.stop_event.set()
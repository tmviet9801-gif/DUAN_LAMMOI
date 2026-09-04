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
    "STRANGER_DETECTED": "Phát hiện khách lạ (thoát bàn)",
    "TABLE_BROKEN": "Bàn bị phá (đổi bàn)",
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
        self.chong_pha = bool(config.get("chong_pha", True))
        self.out_guest = bool(config.get("out_guest", True))
        self.xa_delay_ms = int(config.get("xa_delay_ms", 1000))
        self.known_names = set()
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

    def _build_known_names(self, profile_names):
        """Khởi tạo danh sách tên các account phe mình để phân biệt với khách lạ."""
        self.known_names.clear()
        for name in profile_names:
            self.known_names.add(name.strip().lower())
            acc = self.adapter.account_lookup.get(name) or {}
            u = (acc.get("username") or "").strip()
            if u:
                self.known_names.add(u.lower())
            ws_local = (acc.get("web_storage") or {}).get("local", {}) or {}
            ku = (ws_local.get("KEY_USER_NAME") or "").strip()
            if ku:
                self.known_names.add(ku.lower())
        self._add_log(f"Dàn account phe mình (known_names): {list(self.known_names)}")

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

                # Cấu hình bảo vệ ngay trong page cho Anchor
                await self.adapter._configure_inpage_protection(
                    page, self.known_names, out_guest=self.out_guest, chong_pha=self.chong_pha
                )
                # Kiểm tra ngay xem có khách lạ nào đã ở trong bàn hoặc vừa nhảy vào không
                diag = await self.adapter._check_has_stranger(page, self.known_names)
                if diag.get("has_stranger"):
                    await self.adapter._leave_room(page)
                    self._add_log(f"{name}: Vừa vào bàn {rid} nhưng bị khách lạ {diag['strangers']} chen vào -> Rời bàn ngay!")
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

    async def _check_table_protection(self) -> bool:
        """Kiểm tra bảo vệ bàn:
        1. Thoát khi có khách lạ (out_guest): nếu có người không thuộc known_names -> rời bàn ngay.
        2. Chống phá (chong_pha): nếu phát hiện khách lạ hoặc bàn bị kẹt -> rời bàn ngay.
        Trả về True nếu an toàn, False nếu đã kích hoạt rời bàn bảo vệ.
        """
        if not self.out_guest and not self.chong_pha:
            return True

        for m in self.members:
            if m.get("phase") == "ERROR":
                continue
            name = m["name"]
            page = await self.adapter._page(name)
            if not page:
                continue

            diag = await self.adapter._check_has_stranger(page, self.known_names)
            if diag.get("has_stranger"):
                strangers = diag.get("strangers", [])
                self._add_log(f"CẢNH BÁO: Phát hiện khách lạ {strangers} trong bàn!")

                if self.out_guest:
                    self._set_phase("STRANGER_DETECTED")
                    self._add_log("Kích hoạt bảo vệ (out_guest): tất cả tài khoản tự động rời bàn!")
                    for mem in self.members:
                        pg = await self.adapter._page(mem["name"])
                        if pg:
                            await self.adapter._leave_room(pg)
                    return False

                if self.chong_pha:
                    gs = await self.adapter._get_game_state(page)
                    if gs == 0:  # Đang chờ mà có khách phá
                        self._set_phase("TABLE_BROKEN")
                        self._add_log("Kích hoạt chống phá (chong_pha): bàn bị kẹt/phá, rời bàn đổi bàn mới!")
                        for mem in self.members:
                            pg = await self.adapter._page(mem["name"])
                            if pg:
                                await self.adapter._leave_room(pg)
                        return False

        return True

    async def _join_members(self) -> bool:
        """Gom bàn: Cho tất cả các tài khoản phụ (Joiners) vào cùng bàn của Anchor."""
        self._set_phase("JOINING")
        self._sync_room()

        # Kiểm tra trước: Anchor có bị khách lạ chen chân trong lúc chờ Joiner không?
        anchor_page = await self.adapter._page(self.anchor)
        if anchor_page:
            diag_anchor = await self.adapter._check_has_stranger(anchor_page, self.known_names)
            if diag_anchor.get("has_stranger"):
                self._add_log(f"Bàn {self._room_id} bị khách lạ {diag_anchor['strangers']} chen chân trước khi Joiner kịp vào -> Thoát bàn để gom bàn khác!")
                await self.adapter._leave_room(anchor_page)
                return False

        for m in self.members:
            if m["name"] == self.anchor or m["phase"] == "ERROR":
                continue
            page = await self.adapter._page(m["name"])
            if not page:
                m["phase"] = "ERROR"
                continue

            # Cấu hình bảo vệ thời gian thực cho Joiner
            await self.adapter._configure_inpage_protection(
                page, self.known_names, out_guest=self.out_guest, chong_pha=self.chong_pha
            )

            self._sync_room()
            ok = await self.adapter._join_room_by_id(page) if self._join_template else False
            m["phase"] = "JOINED" if ok else "ERROR"
            if not ok:
                self._add_log(f"{m['name']}: join bàn {self._room_id} thất bại (bàn có thể đã full do khách lạ) — thoát và thử lại")
                # Hủy bàn cho tất cả nick
                for mem in self.members:
                    pg = await self.adapter._page(mem["name"])
                    if pg:
                        await self.adapter._leave_room(pg)
                return False

        self._set_phase("TABLE_READY")
        await asyncio.sleep(float(self.game.get("table_wait", 2.0)))

        # Xác nhận tất cả member đã vào cùng 1 phòng với anchor
        joined = [m["name"] for m in self.members if m["phase"] != "ERROR"]
        if len(joined) >= 2:
            same = await self.adapter._verify_same_room(joined)
            if not same:
                self._add_log("Không hội tụ đủ vào cùng bàn (có thể bàn full do khách lạ) -> Thoát bàn!")
                for mem in self.members:
                    pg = await self.adapter._page(mem["name"])
                    if pg:
                        await self.adapter._leave_room(pg)
                return False

        await self._shot_all("table_ready")

        # Kiểm tra bảo vệ bàn ngay sau khi cả dàn đã vào phòng
        safe = await self._check_table_protection()
        return safe

    async def _discard(self):
        """Xả bài tự động cho từng tài khoản với độ trễ xa_delay_ms."""
        self._set_phase("DISCARDING")
        for rep in range(self.discard_repeat):
            for m in self.members:
                if m["phase"] == "ERROR":
                    continue
                page = await self.adapter._page(m["name"])
                if not page:
                    continue
                ok = await self.adapter._discard_cards(page, m["name"], delay_ms=self.xa_delay_ms)
                m["phase"] = "DISCARDED" if ok else m.get("phase", "OPENED")
            self._add_log(f"Xả bài vòng {rep + 1}/{self.discard_repeat} (độ trễ {self.xa_delay_ms}ms)")

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

        self._build_known_names(profile_names)

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

        max_table_cycles = max(1, int(self.game.get("max_table_cycles", 5)))
        for table_cycle in range(max_table_cycles):
            if self.stop_event.is_set():
                return

            self._room_id = None
            self._join_template = None
            self._sync_room()

            # 2) tìm bàn trống: acc đầu thấy = anchor
            self.anchor = await self._find_anchor()
            if not self.anchor:
                self._set_phase("ERROR")
                self._add_log("Không acc nào tìm thấy bàn trống — kiểm tra lại mạng / kết nối")
                await self._shot_all("search_fail")
                return
            self._set_phase("ANCHOR")

            # 3) bắt room id + gom các nick còn lại vào chung bàn
            if not self._room_id:
                await self._capture_room()

            joined_ok = await self._join_members()
            if not joined_ok:
                self._add_log(f"Gom bàn vòng {table_cycle + 1}: Có khách lạ hoặc bị phá, đã thoát bàn an toàn. Chờ 3s tìm bàn mới...")
                await asyncio.sleep(3.0)
                continue

            # 4) tự động xả bài (có delay)
            await self._discard()

            if self.auto_out:
                # Tự rời bàn sau khi xả
                for m in self.members:
                    page = await self.adapter._page(m["name"])
                    if page:
                        await self.adapter._leave_room(page)
                self._set_phase("DONE")
                self._add_log("auto_out: đã tự rời bàn — chu trình hoàn tất an toàn.")
                return

            # 5) chờ khách + tự bắt đầu (nếu không auto_out)
            await self._wait_guest()
            self._set_phase("DONE")
            return

        self._set_phase("DONE")
        self._add_log("Đã kết thúc chu trình gom bàn.")

    def stop(self):
        self.stop_event.set()
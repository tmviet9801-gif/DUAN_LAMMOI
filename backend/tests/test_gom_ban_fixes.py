"""Test các fix trong quy trình "gom bàn" (hunt/matchmaking):

1. Khớp account theo mọi alias (name/username/character_name/uid...) — giúp
   balance/log/cards từ Extension (gửi theo tên in-game dn) cập nhật đúng tài
   khoản, xoá được log/bài cũ (fix "số dư không realtime", "log cũ không xoá").
2. Parse balance an toàn (số nguyên / dấu phân tách hàng nghìn VN).
3. ExtensionHub: khi socket đăng ký bằng tên in-game, cập nhật balance/log vẫn
   tìm đúng account trong accounts.json và emit event theo tên chuẩn (name).
"""
import asyncio
import copy
import inspect
import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock

from controllers.account_controller import _match_account, _parse_balance


def _controller_source() -> str:
    """Toàn bộ source của package `controllers/auto_flow_controller`.

    Trước đây luồng gom bàn nằm trong MỘT file nên test đọc thẳng file đó. Nay
    đã tách thành package (constants/deps/lobby/routes_basic/matching/
    routes_debug), nên nối tất cả module lại để các assert theo chuỗi vẫn kiểm
    đúng phạm vi cũ mà không phụ thuộc code nằm ở file nào.
    """
    pkg = Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
    return "\n".join(
        f.read_text(encoding="utf-8") for f in sorted(pkg.glob("*.py"))
    )


SAMPLE_ACCOUNTS = [
    {
        "id": "acc-1",
        "index": 1,
        "name": "Account01",
        "username": "nicktestxabai1",
        "character_name": "nicktestxxabai1",
        "game_username": "nicktestxabai1",
        "uid": "10001",
        "balance": 100,
        "room": -1,
        "log": "Đang ở sảnh",
        "cards": [],
    },
    {
        "id": "acc-2",
        "index": 2,
        "name": "Account02",
        "username": "nicktestxabai2",
        "character_name": "nicktestxxabai2",
        "game_username": "nicktestxabai2",
        "uid": "10002",
        "balance": 200,
        "room": -1,
        "log": "Đang ở sảnh",
        "cards": [],
    },
]


def _acc(name):
    for a in SAMPLE_ACCOUNTS:
        if a["name"] == name:
            return a
    return None


# ---------- _match_account ----------

def test_match_by_name_and_username():
    assert _match_account(_acc("Account01"), "Account01")
    assert _match_account(_acc("Account01"), "account01")
    assert _match_account(_acc("Account02"), "nicktestxabai2")
    assert not _match_account(_acc("Account01"), "nicktestxabai2")


def test_match_by_in_game_character_name():
    # Extension gửi theo tên in-game (dn) — phải tìm đúng account
    assert _match_account(_acc("Account01"), "nicktestxxabai1")
    assert _match_account(_acc("Account02"), "nicktestxxabai2")
    assert not _match_account(_acc("Account02"), "nicktestxxabai1")


def test_match_by_uid_and_suffix():
    assert _match_account(_acc("Account02"), "10002")
    # hậu tố số 1/2 dùng để phân biệt cặp profile song hành
    assert _match_account(_acc("Account01"), "Account 1")
    assert not _match_account(_acc("Account01"), "something2")


# ---------- _parse_balance ----------

def test_parse_balance_plain_int():
    assert _parse_balance("54068") == 54068
    assert _parse_balance(54068) == 54068


def test_parse_balance_thousand_separators():
    # Dấu chấm phân tách hàng nghìn kiểu VN
    assert _parse_balance("57.377") == 57377
    assert _parse_balance("1.234.567") == 1234567
    assert _parse_balance("10.000") == 10000
    # Dấu phẩy phân tách
    assert _parse_balance("12,345") == 12345


def test_parse_balance_decimal_stays_number():
    # Nếu thực sự là số thập phân thì giữ nguyên giá trị (không nhân lên 100)
    assert _parse_balance("1234.5") == 1234.5


def test_parse_balance_invalid():
    assert _parse_balance("--") == "--"
    assert _parse_balance("") == ""


# ---------- Lưu "số dư lần cuối" khi đóng Chrome ----------

def test_extract_balance_from_local():
    from services.browser_service import extract_balance_from_local

    assert extract_balance_from_local({"AUTOTOOL_BALANCE": "57377"}) == 57377
    assert extract_balance_from_local({"AUTOTOOL_BALANCE": 57377}) == 57377
    assert extract_balance_from_local({"AUTOTOOL_BALANCE": "57377.0"}) == 57377
    assert extract_balance_from_local({"AUTOTOOL_BALANCE": "17013"}) == 17013
    assert extract_balance_from_local({"AUTOTOOL_BALANCE": "12.5"}) == 12.5
    assert extract_balance_from_local({"AUTOTOOL_BALANCE": ""}) is None
    assert extract_balance_from_local({}) is None
    assert extract_balance_from_local(None) is None
    assert extract_balance_from_local({"AUTOTOOL_BALANCE": "không-phải-số"}) is None


# ---------- ExtensionHub alias-based update ----------

class FakeHubWs:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self):
        pass


@pytest.mark.anyio
async def test_hub_room_share_disabled_blocks_zombie_join_after_stop():
    """Sau khi bấm Dừng (set_room_share(False)), anchor báo "bàn trống" KHÔNG được
    phép phát JOIN_ROOM cho profile phụ nữa — chặn zombie gom bàn lặp lại."""
    from services.extension_hub import ExtensionHubManager

    hub = ExtensionHubManager()
    ws_a = FakeHubWs()
    ws_b = FakeHubWs()
    hub.active_sockets["ProfileA"] = ws_a
    hub.active_sockets["ProfileB"] = ws_b
    hub.profile_states["ProfileA"] = {"profile_name": "ProfileA", "connected": True}
    hub.profile_states["ProfileB"] = {"profile_name": "ProfileB", "connected": True}

    anchor_msg = {
        "type": "ANCHOR_ROOM_VERIFIED_EMPTY",
        "room_info": {"rid": 12345, "rn": "Bàn Solo $100", "b": 100, "Mu": 2, "is_verified_empty": True, "player_count": 1},
    }

    # 1. Đang khoá (sau Dừng) -> B KHÔNG nhận JOIN_ROOM
    hub.set_room_share(False)
    hub.handle_message("ProfileA", anchor_msg)
    await asyncio.sleep(0.01)
    b_actions = [c.get("action") for c in ws_b.sent]
    assert "JOIN_ROOM" not in b_actions

    # 2. Bật lại room_share không khôi phục auto-forward; controller phải cấp
    # vé join sau khi xác minh Anchor để tránh B vào trước A.
    hub.set_room_share(True)
    ws_b.sent.clear()
    hub.handle_message("ProfileA", anchor_msg)
    await asyncio.sleep(0.01)
    b_actions = [c.get("action") for c in ws_b.sent]
    assert "JOIN_ROOM" not in b_actions


@pytest.mark.anyio
async def test_hub_balance_update_matches_account_by_in_game_name(tmp_config, monkeypatch):
    """Socket đăng ký bằng tên in-game (nicktestxxabai1) vẫn phải cập nhật
    đúng account 'Account01' (balance + emit theo tên chuẩn name)."""
    from models import config_model as cfg
    from services.extension_hub import ExtensionHubManager

    state = {"accounts": copy.deepcopy(SAMPLE_ACCOUNTS)}
    saved = {"value": None}

    monkeypatch.setattr(cfg, "load_accounts", lambda: state["accounts"])
    monkeypatch.setattr(cfg, "save_accounts", lambda accs: saved.__setitem__("value", accs))

    hub = ExtensionHubManager()
    events = []
    hub.set_event_sink(lambda ev: events.append(ev))

    in_game_name = "nicktestxxabai1"
    hub.active_sockets[in_game_name] = FakeHubWs()
    hub.profile_states[in_game_name] = {"profile_name": in_game_name, "connected": True}

    hub.handle_message(in_game_name, {
        "type": "BALANCE_UPDATE",
        "balance": "57377",
    })

    st = hub.get_profile_state(in_game_name)
    assert st["balance"] == 57377

    assert saved["value"] is not None
    acc1 = next(a for a in saved["value"] if a["name"] == "Account01")
    assert acc1["balance"] == 57377
    # Account02 không bị đụng vào
    acc2 = next(a for a in saved["value"] if a["name"] == "Account02")
    assert acc2["balance"] == 200

    # Event emit theo tên chuẩn (name) để UI cập nhật đúng dòng account
    ev_names = [e.get("profile_name") for e in events if e.get("type") == "accounts_updated"]
    assert "Account01" in ev_names


@pytest.mark.anyio
async def test_hub_log_update_matches_account_and_clears(tmp_config, monkeypatch):
    """Log từ Extension (gửi theo tên in-game) phải ghi đè đúng account —
    đảm bảo log/bài cũ được xoá thay vì bị bỏ qua do lệch tên profile."""
    from models import config_model as cfg
    from services.extension_hub import ExtensionHubManager

    state = {"accounts": copy.deepcopy(SAMPLE_ACCOUNTS)}
    saved = {"value": None}

    monkeypatch.setattr(cfg, "load_accounts", lambda: state["accounts"])
    monkeypatch.setattr(cfg, "save_accounts", lambda accs: saved.__setitem__("value", accs))

    hub = ExtensionHubManager()
    events = []
    hub.set_event_sink(lambda ev: events.append(ev))

    in_game_name = "nicktestxxabai1"
    hub.active_sockets[in_game_name] = FakeHubWs()
    hub.profile_states[in_game_name] = {"profile_name": in_game_name, "connected": True}

    hub.handle_message(in_game_name, {
        "type": "LOG_UPDATE",
        "log": "Đang ở sảnh (Đã xoá log cũ)",
    })

    assert hub.get_profile_state(in_game_name)["log"] == "Đang ở sảnh (Đã xoá log cũ)"
    assert saved["value"] is not None
    acc1 = next(a for a in saved["value"] if a["name"] == "Account01")
    assert acc1["log"] == "Đang ở sảnh (Đã xoá log cũ)"

    ev_names = [e.get("profile_name") for e in events if e.get("type") == "accounts_updated"]
    assert "Account01" in ev_names


# ---------- Part A: chặn "phụ đứng nguyên ở sảnh chính" ----------

def test_is_in_tldl_lobby_dropped_simms_fallback():
    """Regression: fallback `simms.readyState === 1` đã bị gỡ. Khi extension chưa
    inject `__autotool_is_in_tldl_lobby`, hàm PHẢI trả False (ép điều hướng vào
    sảnh bàn Đếm Lá) thay vì nhầm 'có socket' là 'đã ở sảnh'."""
    import inspect
    import re

    from controllers.auto_flow_controller import _is_in_tldl_lobby_util

    src = inspect.getsource(_is_in_tldl_lobby_util)
    # Khớp khối JS trong ngoặc ba nháy, không phụ thuộc hàm gọi là
    # `page.evaluate(...)` hay `eval_page(page, ...)`. JS chạy ở world nào là
    # chuyện khác; nội dung khối JS mới là thứ test này canh.
    m = re.search(r'"""(\(\) => \{.*?\})"""', src, re.DOTALL)
    assert m, "Không tìm thấy khối JS trong _is_in_tldl_lobby_util"
    js = m.group(1)
    assert "simms" not in js
    assert "readyState" not in js
    assert "__autotool_is_in_tldl_lobby" in js
    assert "return false;" in js


class _FakeLobbyPage:
    def __init__(self, evaluate_result=None, closed=False):
        self._result = evaluate_result
        self.closed = closed
        self.eval_calls = []

    def is_closed(self):
        return self.closed

    async def evaluate(self, js):
        self.eval_calls.append(js)
        return self._result


@pytest.mark.anyio
async def test_is_in_tldl_lobby_passthrough():
    from controllers.auto_flow_controller import _is_in_tldl_lobby_util

    assert await _is_in_tldl_lobby_util(_FakeLobbyPage(False)) is False
    assert await _is_in_tldl_lobby_util(_FakeLobbyPage(True)) is True


@pytest.mark.anyio
async def test_clear_hunt_state_disables_auto_hunt():
    from controllers.auto_flow_controller import _clear_hunt_state

    page = _FakeLobbyPage(True)
    await _clear_hunt_state(page)
    assert page.eval_calls
    js = page.eval_calls[0]
    assert "__AUTOTOOL_AUTO_HUNT = false" in js
    assert "__is_hunt_initiator = false" in js
    assert "__hunt_retry_timer" in js
    assert "__start_retry_timer" in js
    assert "__auto_turn_timer" in js


def test_extension_requires_controller_assigned_match_roles():
    """Không được tự suy ra chiều main/sub khi tab vừa load.

    Controller gán anchor/sub theo profile đã chọn; extension chỉ dùng heuristic
    cũ như fallback cho thao tác tay ngoài một lượt gom bàn.
    """
    from pathlib import Path

    source = (Path(__file__).parents[1] / "extension" / "content_main.js").read_text(encoding="utf-8")
    assert "function isSubMatchProfile()" in source
    assert "function isAnchorMatchProfile()" in source
    assert 'G.__AUTOTOOL_AUTO_HUNT = false;' in source
    controller = _controller_source()
    # Anchor lấy từ lựa chọn của UI, không suy từ tên nick. Hàm chuẩn hoá đã
    # chuyển sang context.py và nhận thêm `accounts` khi tách module.
    assert 'requested_anchor = resolve_profile_name(body.get("profile_a"), accounts)' in controller
    assert "first_name = profile_a" in controller
    assert 'window.__AUTOTOOL_MATCH_ROLE = \'anchor\';' in controller
    assert 'window.__AUTOTOOL_MATCH_ROLE = \'sub\';' in controller


def test_leave_command_never_rejoins_default_bet_table():
    """Rời bàn không được gửi cmd 308 vì đó là lệnh join.

    Một payload 308 thiếu `b`/`Mu` bị game đưa về bàn mặc định $500.
    """
    from pathlib import Path

    source = (Path(__file__).parents[1] / "extension" / "content_main.js").read_text(encoding="utf-8")
    # Cắt theo TÊN hàm, không theo chữ ký: hàm đã nhận thêm tham số
    # `buocNgay` (rời ngay, bỏ qua chốt "đang giữa ván").
    leave_fn = source.split("G.__autotool_exec_leave = function", 1)[1]                      .split("G.__autotool_exec_ready = function", 1)[0]
    assert '"cmd":203' in leave_fn
    assert '"cmd":308' not in leave_fn


def test_stop_is_immediate_and_lobby_preparation_is_parallel():
    """Stop không được tiếp tục điều hướng, và main chỉ join sau khi mọi nick
    đã đồng bộ được sảnh chọn bàn."""
    from pathlib import Path

    from controllers.auto_flow_controller.routes_basic import _dung_auto

    source = _controller_source()
    assert "lobby_results = await asyncio.gather(" in source
    assert "KIÊN TRÌ tới khi MỌI profile đứng ở sảnh chọn bàn" in source
    # Thân xử lý đã tách sang `_dung_auto` để `/stop` (có phạm vi) và
    # `/leave-all` (toàn bộ) là hai endpoint riêng. Lấy source theo function
    # object: không phụ thuộc thứ tự hàm trong file.
    stop_fn = inspect.getsource(_dung_auto)
    assert "Đã dừng tức thì" in stop_fn
    assert "await _ensure_in_tldl_lobby_util(s.page" not in stop_fn


def test_join_always_includes_verified_fixed_rid():
    """Protocol từ cmd=300: Solo $100 là rid=2, Solo $500 là rid=4.
    Không được bỏ các rid nhỏ để game tự chọn mức cược theo state cũ."""
    from pathlib import Path

    source = _controller_source()
    assert '"100_2": 2, "100_4": 1' in source
    assert '"500_2": 4, "500_4": 3' in source
    assert '"100000_2": 18, "100000_4": 17' in source
    assert '"1000000_2": 24, "1000000_4": 23' in source
    assert "Number(rid) > 0" in source
    assert "Number(rid) > 28" not in source
    assert "[3, 'Simms', specificRid, '']" in source
    assert "Bỏ lượt thay vì click mù sang bàn khác" in source


def test_sub_has_explicit_dump_role_and_auto_discard():
    from pathlib import Path

    source = _controller_source()
    assert "window.__AUTOTOOL_ROLE = 'dump';" in source
    assert "window.__AUTOTOOL_AUTO_DISCARD" in source
    assert "window.__AUTOTOOL_PARTNER_PROFILES" in source


def test_fixed_table_join_frame_preserves_small_rid():
    """RID 1..28 là RID bàn cược hợp lệ; [3, Simms, 4] phải vẫn là $500."""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "extension" / "content_main.js").read_text(encoding="utf-8")
    assert "text.includes('[3,\"Simms\",')" in source
    assert 'const isChongVay = !rid || Number(rid) === -1 || String(rid) === "100";' in source
    assert '"500_2": 4, "500_4": 3' in source
    assert "Number(rid) > 0" in source
    assert 'JSON.stringify([3, "Simms", specificRid, ""])' in source
    assert "RID 1..28 cũng là RID bàn cố định hợp lệ" in source
    assert "Sai mức cược: bàn" in source
    assert "expectedBet !== actualBet" in source


def test_dump_policy_avoids_blank_loss_and_sub_leaves_after_verified_round():
    from pathlib import Path

    ext_source = (Path(__file__).parents[1] / "extension" / "content_main.js").read_text(encoding="utf-8")
    assert "Giảm thua trắng" in ext_source
    assert "__autotool_round_play_count" in ext_source
    assert "Không dùng tứ quý" in ext_source
    assert "function chooseDumpOpening" in ext_source
    assert "đôi 10 phải đánh thành đôi 10" in ext_source
    assert 'humanDelay(1150, 1900)' in ext_source
    assert "function chooseVerifiedSingleRelay" in ext_source
    assert "Anchor thấp < Phụ < Anchor cao hơn" in ext_source
    assert "getLooseSingles(myCards, combs)" in ext_source

    controller = _controller_source()
    assert "game_completed = False" in controller
    assert "if game_completed:" in controller
    assert "Account phụ đã rời bàn về sảnh chọn bàn" in controller
    assert "không tự out Account phụ" in controller
    assert "Account phụ đã xả xong -> tự rời bàn về sảnh chọn bàn" in ext_source
    assert "kill engine/timer, giữ Account chính trong phòng" in controller
    assert "window.__AUTOTOOL_AUTO_DISCARD = false;" in controller
    assert "auto_start_guest_ss and not game_completed" in controller


def test_hub_never_auto_forwards_unverified_bet_room():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "services" / "extension_hub.py").read_text(encoding="utf-8")
    assert "self._room_share_enabled = False" in source
    assert "Hub không được tự quyết định RID/mức cược" in source
    assert "chỉ controller được phép mời Account phụ" in source


def test_sub_join_requires_controller_ticket_after_anchor_verification():
    from pathlib import Path

    ext = (Path(__file__).parents[1] / "extension" / "content_main.js").read_text(encoding="utf-8")
    controller = _controller_source()
    assert "__AUTOTOOL_SUB_JOIN_TICKET" in ext
    assert "không có vé xác nhận từ Account chính" in ext
    assert "expires_at: Date.now() + 8000" in controller


def test_multiple_pairs_are_isolated_and_stop_cancels_every_pair_task():
    from pathlib import Path

    controller = _controller_source()
    assert '@router.post("/api/autoplay/find-and-match-pairs-ws")' in controller
    assert "Một profile chỉ được xuất hiện trong một cặp" in controller
    assert "asyncio.gather(*[" in controller
    assert "gom_ban_stop_epoch" in controller
    assert "active_match_tasks" in controller

    # Endpoint ghép cặp VẪN CÒN ở backend (gọi trực tiếp được), nhưng giao
    # diện không còn dùng: mô hình mới là MỘT nhóm (1 account giữ tiền + N
    # account cùng dò bàn), không còn ghép 1–2 / 3–4 / 5–6.
    ui = (Path(__file__).parents[2] / "app" / "renderer" / "js" / "autoplay.js").read_text(encoding="utf-8")
    assert "multiPairMode" not in ui
    assert '"/api/autoplay/find-and-match-pairs-ws"' not in ui
    assert '"/api/autoplay/find-and-match-ws"' in ui


def test_ready_start_and_quick_join_never_use_cross_role_or_blind_clicks():
    from controllers.auto_flow_controller.routes_basic import autoplay_create_table

    controller = _controller_source()
    assert "(wantStart) =>" in controller
    assert "labelMatchesRole" in controller
    assert "Không thấy nút '%s'; chỉ dùng WS helper đúng vai trò" in controller
    # Lấy source theo chính function object: không phụ thuộc thứ tự hàm trong file.
    quick_fn = inspect.getsource(autoplay_create_table)
    assert "FIXED_TABLE_RIDS" in quick_fn
    assert "JSON.stringify([3, 'Simms', Number(rid), ''])" in quick_fn
    assert "page.mouse.click" not in quick_fn

    ext_source = (Path(__file__).parents[1] / "extension" / "content_main.js").read_text(encoding="utf-8")
    assert "executeHandshakeAction" in ext_source
    assert "if (isAnchorMatchProfile())" in ext_source
    assert "const matchingPair = G.__AUTOTOOL_MATCH_ROLE === \"anchor\"" in ext_source
    assert "từ chối Ready/Start và rời bàn" in ext_source


def test_match_preflight_always_leaves_stale_table_before_lobby_check():
    from pathlib import Path

    source = _controller_source()
    assert "PRE-FLIGHT BẮT BUỘC" in source
    assert "window.__AUTOTOOL_AUTO_HUNT = false;" in source
    assert "Gửi leave một lần ngay cả khi extension không nhìn ra table" in source
    assert "const ws = window.__ws_instances.find" in source


def test_extension_toasts_are_replaced_and_rendered_on_one_line():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "extension" / "content.js").read_text(encoding="utf-8")
    assert 'container.querySelectorAll(".sw-toast").forEach((oldToast) => oldToast.remove());' in source
    assert "const oneLine = [title, bodyText]" in source
    assert "white-space: nowrap !important;" in source


def test_anchor_leaves_and_joins_in_one_beat_against_client_auto_rejoin():
    """Chống livelock: game tự rejoin bàn cũ nhanh hơn cổng xác nhận sảnh.

    Bằng chứng ws_capture.jsonl (backend/data/game_sim_debug):
    - 40 frame `[3,"Simms",4,""]` (rid 4 = $500 Solo) đều là dir="send" thuần,
      KHÔNG có bản dir="inject" nào -> không phải extension gửi (extension luôn
      push("inject", ...) sau mỗi lần gửi; rid=2 có đúng 2 bản inject).
    - 5 cặp trong số đó cách nhau <2500ms -> cũng không thể do controller gửi,
      vì server_join_fn chặn cứng ở 2500ms. Suy ra chính client game tự vào lại.
    - Phiên lỗi 09-08 02:40 và 03:34: 0 frame rid=2, tức tool CHƯA TỪNG gửi được
      lệnh join nào — cổng cũ (range(6) + sleep 0.8s) không bao giờ xác nhận nổi
      sảnh nên luôn `continue`.
    - Chuỗi chạy đúng 09-08 01:46:30 (LEAVE -> ack -> JOIN trong 123ms):
        [4,"Simms",-1] + cmd 203 -> [4,true,1,-1,0,""] -> [3,"Simms",2,""] -> b=100

    Vì vậy anchor phải rời bàn và join lại NGAY trong trang khi nhận ack, không
    được quay vòng qua Python rồi mới join.
    """
    source = _controller_source()

    # 1. Phải có hàm leave->join liền mạch, chờ đúng ack rời bàn của server.
    assert "__autotool_leave_then_join" in source
    assert "d.indexOf('[4,true') === 0" in source
    assert "simms.send('[4,\"Simms\",-1]');" in source
    assert "JSON.stringify([3, 'Simms', specificRid, ''])" in source

    # 2. Anchor phải gọi hàm liền mạch đó, không gọi lại exec_join rời rạc.
    assert "window.__autotool_leave_then_join(" in source

    # 3. Cổng cũ gây livelock phải biến mất: không còn vòng 6 lần + sleep 0.8s
    #    rồi bỏ lượt join khi phát hiện đang kẹt bàn cũ.
    assert "nghỉ 3s bỏ qua lượt join này" not in source
    assert "chủ động LEAVE (lần %d/6)" not in source

    # 4. Chống flood khi đã có RID cụ thể phải là 1200ms — 2500ms còn rộng hơn
    #    chu kỳ auto-rejoin của game nên tự khoá chính mình.
    assert "< 1200" in source


def test_game_facing_code_never_uses_isolated_evaluate():
    """Mọi JS chạm state game phải chạy trong world CỦA TRANG.

    Patchright đặt `isolated_context=True` mặc định cho page/frame.evaluate: JS
    chạy trong world riêng, KHÔNG thấy global của trang lẫn của content script
    `world: "MAIN"` (content_main.js). Mà toàn bộ giao tiếp của tool dựa trên
    `window.__autotool_*` / `window.__ws_*` do content_main.js tạo ra.

    Hậu quả khi gọi nhầm world (đã gặp thật):
    - `__autotool_is_in_tldl_lobby` undefined -> _is_in_tldl_lobby_util luôn
      False -> "Không đưa được các profile vào sảnh bàn Đếm Lá".
    - `__ws_get_simms()` trả null -> không gửi được lệnh join nào.
    - `p.evaluate(content_main_code)` chỉ tạo BẢN SAO extension trong world cô
      lập; bản sao đó patch WebSocket của chính nó nên không thấy socket thật.

    Bằng chứng: Hub báo balance/dn sống (chỉ content_main.js đọc được) trong khi
    page.evaluate thấy window.WebSocket vẫn native chưa patch.
    """
    import re
    from pathlib import Path

    backend = Path(__file__).parents[1]
    targets = [
        backend / "controllers" / "auto_flow_controller" / "lobby.py",
        backend / "controllers" / "auto_flow_controller" / "matching.py",
        backend / "controllers" / "auto_flow_controller" / "routes_basic.py",
        backend / "game_sim" / "adapters" / "hitclub.py",
        backend / "game_sim" / "ws_sniffer.py",
    ]
    offenders = []
    for f in targets:
        src = f.read_text(encoding="utf-8")
        assert "from core.page_world import eval_page" in src, f"{f.name} thiếu import eval_page"
        for i, line in enumerate(src.split("\n"), start=1):
            # `x.evaluate(` trần = dùng world cô lập -> sai. Phải qua eval_page().
            if re.search(r"\b[A-Za-z_][\w.]*\.evaluate\(", line):
                offenders.append(f"{f.name}:{i}: {line.strip()[:90]}")
    assert not offenders, "Còn evaluate() chạy world cô lập:\n" + "\n".join(offenders)


def test_eval_page_falls_back_when_isolated_context_unsupported():
    """Playwright thuần / page giả không có tham số isolated_context."""
    import asyncio

    from core.page_world import eval_page

    class OnlyPlainEvaluate:
        def __init__(self):
            self.calls = []

        async def evaluate(self, expression):   # không nhận isolated_context
            self.calls.append(expression)
            return "ok"

    class SupportsIsolated:
        def __init__(self):
            self.isolated = None

        async def evaluate(self, expression, arg=None, isolated_context=True):
            self.isolated = isolated_context
            return "ok"

    plain = OnlyPlainEvaluate()
    assert asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        eval_page(plain, "() => 1")
    ) == "ok"
    assert plain.calls == ["() => 1"]

    rich = SupportsIsolated()
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        eval_page(rich, "() => 1")
    )
    assert rich.isolated is False, "phải yêu cầu world của trang"


def test_khong_kich_hoat_thi_khong_tu_dong_gi():
    """Chưa bấm "GOM BÀN & XẢ" (hoặc đã Dừng) -> tool phải im hoàn toàn.

    Lỗi thật người dùng gặp: mở account chơi tay, vào bàn gặp người khác thì bị
    tự out; bấm Dừng rồi vẫn thấy chạy gom bàn.

    Hai nguyên nhân cộng lại:
    1. Khối tự động trong handler cmd 202 không có cổng kích hoạt tổng. Nhánh
       "Sai mức cược" chỉ canh `__target_hunt_bet > 0`.
    2. STOP_HUNT không xoá `__target_hunt_bet` / `__AUTOTOOL_AUTO_DISCARD` /
       vai trò. Mức cược của lượt chạy trước còn nguyên -> vào bàn khác mức là
       bị out; AUTO_DISCARD còn bật -> vẫn tự đánh bài.
    """
    from pathlib import Path

    ext = Path(__file__).parents[1] / "extension"
    src = (ext / "content_main.js").read_text(encoding="utf-8")

    # Cổng kích hoạt tồn tại và tôn trọng cờ Dừng đã lưu
    assert "function isAutoEngaged()" in src
    assert 'localStorage.getItem("AUTOTOOL_STOPPED") === "1"' in src
    assert "__AUTOTOOL_ENGAGED" in src

    # Mặc định TẮT khi tab load — chỉ controller mới được bật
    assert "G.__AUTOTOOL_ENGAGED = false;" in src

    # Nhánh "Sai mức cược" phải đi qua cổng, không tự out khi chơi tay
    assert "isAutoEngaged() ? Number(G.__target_hunt_bet || 0) : 0" in src

    # Cả khối săn bàn / xử lý khách lạ phải đi qua cổng
    assert "if (!isAutoEngaged()) {" in src

    # Tự đánh bài cũng phải qua cổng
    assert "if (!isAutoEngaged()) return;" in src

    # Dừng phải dọn sạch cấu hình lượt chạy
    assert "function clearRunConfig()" in src
    for key in ("__target_hunt_bet", "__AUTOTOOL_AUTO_DISCARD", "__AUTOTOOL_MATCH_ROLE",
                "__autotool_partners", "__AUTOTOOL_SUB_JOIN_TICKET"):
        assert key in src.split("function clearRunConfig()", 1)[1][:900], f"clearRunConfig thiếu {key}"


def test_controller_mo_va_dong_cong_kich_hoat():
    """Controller bật cổng ở preflight và đóng lại khi Dừng."""
    from pathlib import Path

    base = Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
    matching = (base / "matching.py").read_text(encoding="utf-8")
    lobby = (base / "lobby.py").read_text(encoding="utf-8")

    assert "window.__AUTOTOOL_ENGAGED = true;" in matching, "preflight chưa mở cổng"
    assert "window.__AUTOTOOL_ENGAGED = false;" in lobby, "_clear_hunt_state chưa đóng cổng"
    # Và phải xoá mức cược cũ, nếu không lần chơi tay sau vẫn bị tự out
    assert "window.__target_hunt_bet = 0;" in lobby


def test_ready_start_uu_tien_goi_api_component():
    """Ready/Start phải gọi thẳng API game trước, chỉ click khi API không có.

    Dò trên scene thật (TLDLScene) cho thấy HitClub lộ phương thức, tên KHÔNG
    bị obfuscate: CardGameTableNoDealer.sendReady() và btn_begin của TLMNScene.
    Đường cũ (dò nhãn "SẴN SÀNG"/"BẮT ĐẦU" -> so ảnh OpenCV -> click toạ độ)
    phụ thuộc ngôn ngữ hiển thị và độ phân giải; chính kiểu dò nhãn đó đã gây
    lỗi nhận nhầm sảnh trước đây.
    """
    src = _controller_source()

    assert "typeof c.sendReady === \"function\"" in src, "chưa gọi sendReady()"
    assert "c.btn_begin.node.activeInHierarchy" in src, \
        "phải dùng activeInHierarchy, không dùng node.active (bỏ sót node cha bị tắt)"
    # Đường cũ vẫn phải còn làm dự phòng
    assert "OpenCV phát hiện nút" in src
    assert "Không thấy nút '%s'; chỉ dùng WS helper đúng vai trò" in src


def test_preflight_xoa_co_dung_tren_moi_trang():
    """Cờ Dừng phải được xoá trên MỌI trang khi bắt đầu lượt chạy mới.

    Lỗi thật: `_clear_hunt_state` SET localStorage AUTOTOOL_STOPPED='1' trên
    tất cả trang khi bấm Dừng, nhưng chỉ khối cấu hình của ANCHOR mới xoá nó.
    Từ lần chạy thứ hai trở đi, nick phụ vẫn còn cờ -> isAutoEngaged() trả
    false -> phụ KHÔNG BAO GIỜ đánh bài dù đã ghép bàn thành công.
    """
    from pathlib import Path

    matching = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
                / "matching.py").read_text(encoding="utf-8")
    preflight = matching.split("preflight_code = f", 1)[1].split('"""', 2)[1]
    assert "localStorage.removeItem('AUTOTOOL_STOPPED')" in preflight, \
        "preflight phải xoá cờ Dừng — nó là nơi duy nhất chạy trên MỌI trang"
    assert "window.__AUTOTOOL_ENGAGED = true;" in preflight


def test_phu_tu_out_sau_van_khong_canh_co_luon_tat():
    """Phụ xả xong phải rời bàn để nhường chỗ khách ngoài.

    Nhánh này từng canh `__AUTOTOOL_AUTO_HUNT`, mà controller ở chế độ
    backend-driven LUÔN tắt cờ đó (để không có hai engine cùng join) -> nhánh
    chết, phụ ngồi lì trong bàn sau khi đánh xong.
    """
    from pathlib import Path

    src = (Path(__file__).parents[1] / "extension" / "content_main.js").read_text(encoding="utf-8")
    assert "if (isAutoEngaged() && isSubMatchProfile()) {" in src, \
        "phải canh cổng kích hoạt, không canh __AUTOTOOL_AUTO_HUNT"
    assert "G.__AUTOTOOL_AUTO_HUNT && isSubMatchProfile()" not in src


def test_resolve_profile_name_khop_ca_ten_in_game():
    """Extension báo tên IN-GAME (character_name), không phải username đăng nhập.

    Thiếu nó thì resolve trả về chuỗi thô -> adapter._page() không tìm ra
    session -> profile bị bỏ qua cả lượt chạy, không được cấu hình gì.
    """
    from controllers.auto_flow_controller.context import resolve_profile_name

    accounts = [{
        "id": "acc-1", "name": "Account 01",
        "username": "nicktestxabai1",          # tên đăng nhập (1 chữ x)
        "character_name": "nicktestxxabai1",   # tên in-game (2 chữ x)
        "game_username": "O6YY7y9a",
    }]
    for probe in ("Account 01", "account01", "nicktestxabai1",
                  "nicktestxxabai1", "O6YY7y9a", "acc-1"):
        assert resolve_profile_name(probe, accounts) == "Account 01", probe
    # Không khớp thì giữ nguyên chuỗi vào
    assert resolve_profile_name("nguoi-la", accounts) == "nguoi-la"


def test_vao_sanh_uu_tien_dieu_huong_cua_extension():
    """Đường OpenCV không dẹp popup -> gặp banner cảnh báo là kẹt ở sảnh chính.

    Triệu chứng thật: nick phụ đứng ngoài sảnh chính trong khi nick chính đã
    vào sảnh chọn bàn, hỏng cả lượt gom bàn.
    """
    from pathlib import Path

    src = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
           / "lobby.py").read_text(encoding="utf-8")
    assert "__autotool_dismiss_popups" in src, "phải dẹp popup trước khi điều hướng"
    assert "__autotool_auto_enter_tldl" in src, "phải ưu tiên điều hướng của extension"
    # Đường OpenCV vẫn giữ làm dự phòng
    assert "OpenCV Template Matching" in src


def _renderer(*phan):
    from pathlib import Path

    return (Path(__file__).parents[2] / "app" / "renderer"
            ).joinpath(*phan).read_text(encoding="utf-8")


def _renderer_code(*phan):
    """Chỉ các dòng CODE, bỏ dòng chú thích `//`.

    Phần giải thích lỗi cũ nhắc lại chính những chuỗi bị cấm, và đó là chủ ý —
    kiểm cả chú thích thì test đỏ vì tài liệu chứ không phải vì code.
    """
    return "\n".join(d for d in _renderer(*phan).splitlines()
                      if not d.strip().startswith("//"))


def test_ui_chi_co_mot_nguon_su_that_cho_profile_se_chay():
    """Chạy đúng những profile được tích. Không đoán, không tự chọn thay.

    Bản trước dò qua 7 tầng dự phòng — dropdown Chính/Phụ, checkbox, dòng được
    bôi, session đang mở, DOM, và cuối cùng "2 account đầu danh sách". Tầng
    cuối nghĩa là KHÔNG TÍCH GÌ CŨNG CHẠY, và chạy nhầm account.
    """
    src = _renderer_code("js", "autoplay.js")
    assert "profilesDaChon" in src, "thiếu nguồn sự thật duy nhất"

    for tan_du in ("Ưu tiên 2", "Ưu tiên 5", "Ưu tiên 7",
                   "App.state.accounts[0].name",
                   "#profileTbody tr.row-selected",
                   "isFromDashboard"):
        assert tan_du not in src, f"còn tầng dự phòng cũ: {tan_du}"

    # Thiếu lựa chọn thì BÁO, không tự chọn thay người dùng
    assert "Hãy tích ít nhất 2 profile" in src


def test_ui_khong_con_chon_chinh_phu():
    """Bỏ hai dropdown Chính/Phụ ở mọi nơi: HTML và JS."""
    html = _renderer("index.html")
    assert "gcProfileMain" not in html and "gcProfileSub" not in html
    assert "gcSelectedChips" in html, "thiếu chỗ hiển thị profile sẽ chạy"

    for f in ("autoplay.js", "render.js", "actions.js"):
        src = _renderer_code("js", f)
        assert "gcProfileMain" not in src, f"{f} còn đọc dropdown Chính"
        assert "gcProfileSub" not in src, f"{f} còn đọc dropdown Phụ"
        assert "setSyncPair" not in src, f"{f} còn gán cặp Chính/Phụ"


def test_thao_tac_don_le_khong_tu_chon_account_thay_nguoi_dung():
    """Tạo bàn / Random vào phòng từng lùi về "Account 1" khi chưa tích gì.

    Đó là thao tác lên một account người dùng không hề chọn — trên tài khoản
    có tiền thật.
    """
    src = _renderer_code("js", "actions.js")
    assert '"Account 1"' not in src, "còn tự chọn Account 1 khi chưa tích gì"
    assert "profileDaTichDauTien" in src
    assert "Hãy tích 1 profile" in src


def test_thu_tu_tich_duoc_hien_thi_ro_cho_nguoi_dung():
    """Profile tích đầu tiên giữ tiền — người dùng phải THẤY thứ tự đó."""
    src = _renderer("js", "autoplay.js")
    assert "gc-chip" in src and "anchor" in src
    assert "giữ tiền" in src
    # Mọi thay đổi lựa chọn phải vẽ lại danh sách
    assert "App.autoplayRenderProfiles()" in _renderer("js", "render.js")



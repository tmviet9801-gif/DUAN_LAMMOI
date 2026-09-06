"""Test các fix trong quy trình "gom bàn" (hunt/matchmaking):

1. Khớp account theo mọi alias (name/username/character_name/uid...) — giúp
   balance/log/cards từ Extension (gửi theo tên in-game dn) cập nhật đúng tài
   khoản, xoá được log/bài cũ (fix "số dư không realtime", "log cũ không xoá").
2. Parse balance an toàn (số nguyên / dấu phân tách hàng nghìn VN).
3. ExtensionHub: khi socket đăng ký bằng tên in-game, cập nhật balance/log vẫn
   tìm đúng account trong accounts.json và emit event theo tên chuẩn (name).
"""
import copy
import json

import pytest
from unittest.mock import AsyncMock

from controllers.account_controller import _match_account, _parse_balance


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

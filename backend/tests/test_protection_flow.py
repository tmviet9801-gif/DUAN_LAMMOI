"""Test logic gom bàn, bảo vệ (chống phá, thoát khách lạ) và xả bài."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from game_sim.adapters.hitclub import HitClubAdapter
from game_sim.auto_flow import AutoFlow


@pytest.mark.anyio
async def test_check_has_stranger_detection():
    config = {"game": {"adapter": "hitclub"}}
    adapter = HitClubAdapter(config)

    mock_page = MagicMock()
    # Giả lập phòng có 2 người: 1 người quen, 1 khách lạ
    adapter._get_room_players = AsyncMock(return_value=[
        {"dn": "MyAccount1", "u": "nick1"},
        {"dn": "Stranger999", "u": "stranger_id"}
    ])

    known = {"myaccount1", "nick1", "myaccount2"}
    res = await adapter._check_has_stranger(mock_page, known)

    assert res["has_stranger"] is True
    assert "Stranger999" in res["strangers"]
    assert len(res["players"]) == 2


@pytest.mark.anyio
async def test_check_no_stranger_when_all_known():
    config = {"game": {"adapter": "hitclub"}}
    adapter = HitClubAdapter(config)

    mock_page = MagicMock()
    # Giả lập phòng chỉ có nick phe mình
    adapter._get_room_players = AsyncMock(return_value=[
        {"dn": "MyAccount1", "u": "nick1"},
        {"dn": "MyAccount2", "u": "nick2"}
    ])

    known = {"myaccount1", "nick1", "myaccount2", "nick2"}
    res = await adapter._check_has_stranger(mock_page, known)

    assert res["has_stranger"] is False
    assert len(res["strangers"]) == 0


@pytest.mark.anyio
async def test_leave_room_sends_simms_command():
    config = {"game": {"adapter": "hitclub"}}
    adapter = HitClubAdapter(config)
    adapter.sniffer.send_raw_channel = AsyncMock(return_value=True)
    adapter._click_retry = AsyncMock(return_value=True)

    mock_page = MagicMock()
    ok = await adapter._leave_room(mock_page)

    assert ok is True
    adapter.sniffer.send_raw_channel.assert_awaited_once_with(
        mock_page, "Simms", '[4,"Simms",-1]'
    )


@pytest.mark.anyio
async def test_auto_flow_protection_trigger():
    config = {
        "game": {"adapter": "hitclub"},
        "chong_pha": True,
        "out_guest": True,
        "xa_delay_ms": 500,
    }
    adapter = MagicMock()
    flow = AutoFlow("test_run", adapter, config)
    flow.members = [{"name": "Acc1", "phase": "JOINED"}]

    mock_page = MagicMock()
    adapter._page = AsyncMock(return_value=mock_page)
    adapter._leave_room = AsyncMock(return_value=True)

    # Khi có khách lạ
    adapter._check_has_stranger = AsyncMock(return_value={
        "has_stranger": True,
        "strangers": ["EnemyBot"],
    })

    safe = await flow._check_table_protection()

    assert safe is False
    assert flow.phase == "STRANGER_DETECTED"
    adapter._leave_room.assert_awaited_once_with(mock_page)


@pytest.mark.anyio
async def test_join_aborted_if_anchor_invaded_by_stranger():
    """Tình huống: Account 1 vào bàn trống, nhưng trong lúc chờ Account 2 vào thì
    có khách lạ chen chân. Cả dàn phải lập tức thoát bàn và không cho Account 2 join vào."""
    config = {
        "game": {"adapter": "hitclub"},
        "chong_pha": True,
        "out_guest": True,
    }
    adapter = MagicMock()
    flow = AutoFlow("test_run_race", adapter, config)
    flow.anchor = "Acc1"
    flow.members = [
        {"name": "Acc1", "phase": "ANCHOR"},
        {"name": "Acc2", "phase": "OPENED"},
    ]
    flow._room_id = 999
    flow._join_template = '[3,"Simms",1,"{room_id}"]'

    anchor_page = MagicMock()
    adapter._page = AsyncMock(return_value=anchor_page)
    adapter._leave_room = AsyncMock(return_value=True)
    adapter._configure_inpage_protection = AsyncMock(return_value=True)

    # Khách lạ vừa nhảy vào bàn Anchor
    adapter._check_has_stranger = AsyncMock(return_value={
        "has_stranger": True,
        "strangers": ["StrangerPlayer"],
    })

    ok = await flow._join_members()

    # Phải từ chối join và yêu cầu Anchor rời bàn ngay
    assert ok is False
    adapter._leave_room.assert_awaited_once_with(anchor_page)


@pytest.mark.anyio
async def test_join_by_id_builds_correct_payload():
    """Kiểm tra frame join 308 và protocol join đích danh đúng room id."""
    config = {"game": {"adapter": "hitclub"}}
    adapter = HitClubAdapter(config)
    adapter.sniffer = MagicMock()
    adapter.sniffer.send_raw = AsyncMock(return_value=True)
    adapter.sniffer.drain = AsyncMock(return_value=True)
    adapter.sniffer.recent = MagicMock(return_value=[])

    mock_page = MagicMock()
    adapter._page = AsyncMock(return_value=mock_page)

    res = await adapter.join_by_id("Acc2", 183921)
    assert res["ok"] is True
    assert res["rid"] == 183921
    adapter.sniffer.send_raw.assert_awaited()
    sent_msg = res["sent"]
    assert "183921" in sent_msg



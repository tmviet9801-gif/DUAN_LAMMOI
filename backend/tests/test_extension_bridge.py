import json
import pytest
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)


def test_bridge_status_endpoint():
    response = client.get("/api/bridge/status")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["version"] == "3.0.0"
    assert "connected_count" in data
    assert "connected_profiles" in data


def test_bridge_command_validation():
    # Missing profile_name
    res1 = client.post("/api/bridge/command", json={"action": "JOIN_ROOM"})
    assert res1.status_code == 400

    # Missing action
    res2 = client.post("/api/bridge/command", json={"profile_name": "Account 1"})
    assert res2.status_code == 400

    # Non-connected profile
    res3 = client.post("/api/bridge/command", json={"profile_name": "Ghost_Profile", "action": "JOIN_ROOM"})
    assert res3.status_code == 200
    assert res3.json()["ok"] is False


def test_bridge_websocket_lifecycle_and_two_way_messaging():
    ext_hub = getattr(main.app.state, "ext_hub", None)
    assert ext_hub is not None

    with client.websocket_connect("/ws/bridge?profile=TestAccountV3") as ws:
        # 1. Nhận tin nhắn chào mừng WELCOME
        welcome_raw = ws.receive_text()
        welcome = json.loads(welcome_raw)
        assert welcome.get("action") == "WELCOME"
        assert welcome.get("version") == "3.0.0"
        assert welcome.get("profile_name") == "TestAccountV3"

        # 2. Kiểm tra trạng thái kết nối trong ExtensionHub
        assert ext_hub.is_connected("TestAccountV3") is True

        # 3. Test Ping - Pong Keep-Alive
        ws.send_text(json.dumps({"action": "PING", "ts": 98765}))
        pong_raw = ws.receive_text()
        pong = json.loads(pong_raw)
        assert pong.get("action") == "PONG"
        assert pong.get("ts") == 98765

        # 4. Test cập nhật thông tin phòng từ Extension lên Hub
        room_payload = {
            "type": "ROOM_UPDATE",
            "room_info": {"rid": 8888, "rn": "Bàn Solo $500", "b": 500, "Mu": 2},
            "players": [{"dn": "Player1", "u": "p1"}]
        }
        ws.send_text(json.dumps(room_payload))

        state = ext_hub.get_profile_state("TestAccountV3")
        assert state["connected"] is True
        assert state["room_info"] is not None
        assert state["room_info"]["rid"] == 8888

        # 5. Test REST Command bắn xuống qua WebSocket
        res = client.post("/api/bridge/command", json={
            "profile_name": "TestAccountV3",
            "action": "JOIN_ROOM",
            "data": {"rid": 8888, "bet": 500}
        })
        assert res.status_code == 200
        assert res.json()["ok"] is True

        cmd_raw = ws.receive_text()
        cmd = json.loads(cmd_raw)
        assert cmd.get("action") == "JOIN_ROOM"
        assert cmd.get("data", {}).get("rid") == 8888

    # 6. Sau khi đóng socket, kiểm tra đã unregister
    assert ext_hub.is_connected("TestAccountV3") is False


from unittest.mock import AsyncMock


@pytest.mark.anyio
async def test_instant_dual_profile_room_sharing():
    """Kiểm tra luồng tức thời (<2ms): Profile A vào bàn -> Profile B nhận lệnh JOIN_ROOM ngay lập tức!"""
    from services.extension_hub import ExtensionHubManager

    hub = ExtensionHubManager()
    ws_a = AsyncMock()
    ws_b = AsyncMock()

    await hub.register("ProfileA", ws_a)
    await hub.register("ProfileB", ws_b)
    assert len(hub.active_sockets) == 2

    # Profile A gửi gói tin ROOM_UPDATE với ID bàn 12345
    hub.handle_message("ProfileA", {
        "type": "ROOM_UPDATE",
        "room_info": {"rid": 12345, "rn": "Bàn Solo $100", "b": 100, "Mu": 2}
    })

    # Đợi task chạy
    import asyncio
    await asyncio.sleep(0.01)

    # 1. Profile B nhận được lệnh JOIN_ROOM
    assert ws_b.send_text.called
    b_calls = [json.loads(c.args[0]) for c in ws_b.send_text.call_args_list]
    join_call = next((c for c in b_calls if c.get("action") == "JOIN_ROOM"), None)
    assert join_call is not None
    assert join_call["data"]["rid"] == 12345
    assert join_call["data"]["source_profile"] == "ProfileA"

    # 2. Profile A nhận được xác nhận ROOM_SHARED_CONFIRM
    assert ws_a.send_text.called
    a_calls = [json.loads(c.args[0]) for c in ws_a.send_text.call_args_list]
    confirm_call = next((c for c in a_calls if c.get("action") == "ROOM_SHARED_CONFIRM"), None)
    assert confirm_call is not None
    assert confirm_call["data"]["rid"] == 12345
    assert confirm_call["data"]["target_count"] == 1


@pytest.mark.anyio
async def test_hub_balance_and_log_update():
    """Kiểm tra cập nhật số dư (balance) và log trạng thái tài khoản qua Hub."""
    from services.extension_hub import ExtensionHubManager

    hub = ExtensionHubManager()
    ws = AsyncMock()
    await hub.register("TestPlayer", ws)

    # Cập nhật số dư
    hub.handle_message("TestPlayer", {
        "type": "BALANCE_UPDATE",
        "balance": 54068,
    })
    state = hub.get_profile_state("TestPlayer")
    assert state["balance"] == 54068

    # Cập nhật log
    hub.handle_message("TestPlayer", {
        "type": "LOG_UPDATE",
        "log": "Đang tìm bàn trống mức $100...",
    })
    assert state["log"] == "Đang tìm bàn trống mức $100..."

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

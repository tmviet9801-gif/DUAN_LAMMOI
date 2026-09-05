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


def test_instant_dual_profile_room_sharing():
    """Kiểm tra luồng tức thời (<2ms): Profile A vào bàn -> Profile B nhận lệnh JOIN_ROOM ngay lập tức!"""
    ext_hub = getattr(main.app.state, "ext_hub", None)
    assert ext_hub is not None

    with client.websocket_connect("/ws/bridge?profile=ProfileA") as ws_a:
        assert json.loads(ws_a.receive_text()).get("action") == "WELCOME"

        with client.websocket_connect("/ws/bridge?profile=ProfileB") as ws_b:
            assert json.loads(ws_b.receive_text()).get("action") == "WELCOME"

            # Profile A vào bàn cược #12345 và gửi ROOM_UPDATE lên Hub
            ws_a.send_text(json.dumps({
                "type": "ROOM_UPDATE",
                "room_info": {"rid": 12345, "rn": "Bàn Solo $100", "b": 100, "Mu": 2}
            }))

            # Profile B lập tức nhận được lệnh JOIN_ROOM với ID 12345 từ Profile A!
            msg_b_raw = ws_b.receive_text()
            msg_b = json.loads(msg_b_raw)
            assert msg_b.get("action") == "JOIN_ROOM"
            assert msg_b.get("data", {}).get("rid") == 12345
            assert msg_b.get("data", {}).get("source_profile") == "ProfileA"

            # Profile A nhận được xác nhận ROOM_SHARED_CONFIRM
            msg_a_raw = ws_a.receive_text()
            msg_a = json.loads(msg_a_raw)
            assert msg_a.get("action") == "ROOM_SHARED_CONFIRM"
            assert msg_a.get("data", {}).get("rid") == 12345
            assert msg_a.get("data", {}).get("target_count") == 1

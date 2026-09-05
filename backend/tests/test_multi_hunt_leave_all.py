import pytest
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_leave_all_endpoint_exists_and_handles_no_sessions():
    response = client.post("/api/autoplay/leave-all", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "count" in data

def test_find_and_match_ws_requires_open_profiles():
    # Calling with non-existent profiles should cleanly return error 400
    response = client.post("/api/autoplay/find-and-match-ws", json={
        "profiles": ["FakeProfile_01", "FakeProfile_02"],
        "target_bet": 100,
        "mu": 2,
        "auto_xa": True,
        "auto_start_guest_ss": True,
        "auto_leave_after": False
    })
    assert response.status_code == 400
    assert "FakeProfile_01" in response.json()["detail"]

def test_stop_endpoint_cancels_active_match_task():
    from unittest.mock import MagicMock
    mock_task = MagicMock()
    mock_task.done.return_value = False

    main.app.state.active_match_task = mock_task

    response = client.post("/api/autoplay/stop", json={})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_task.cancel.assert_called_once()
    assert getattr(main.app.state, "active_match_task", None) is None

def test_leave_room_endpoint():
    response = client.post("/api/autoplay/leave-room", json={"profile_name": "Account 1", "ws_only": True})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "ws_command" in data
    assert data["ws_command"] == '[4,"Simms",-1]'

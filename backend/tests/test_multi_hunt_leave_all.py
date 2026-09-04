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

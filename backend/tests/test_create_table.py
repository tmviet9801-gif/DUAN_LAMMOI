import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_create_table_missing_profile():
    with TestClient(app) as client:
        res = client.post("/api/autoplay/create-table", json={"profile_name": ""})
        assert res.status_code == 400
        assert "profile_name" in res.json()["detail"]

def test_create_table_profile_not_opened():
    with TestClient(app) as client:
        res = client.post("/api/autoplay/create-table", json={"profile_name": "NonExistentProfile", "bet": 100})
        assert res.status_code == 400
        assert "chưa được mở" in res.json()["detail"] or "Không mở được" in res.json()["detail"]

def test_get_accounts_structure():
    with TestClient(app) as client:
        res = client.get("/api/accounts")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        if len(data) > 0:
            assert "room" in data[0]
            assert "log" in data[0]
            assert "status" in data[0]

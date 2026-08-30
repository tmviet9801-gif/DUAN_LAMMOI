import json
from pathlib import Path


class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestConfig:
    def test_get_config_defaults(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert data["grid"]["cols"] == 5
        assert data["default_count"] == 10

    def test_set_config(self, client, tmp_config):
        r = client.post("/api/config", json={"grid": {"cols": 3}})
        assert r.status_code == 200
        assert r.json()["grid"]["cols"] == 3

    def test_set_config_auto_layout(self, client, tmp_config):
        r = client.post("/api/config", json={"auto_layout": False})
        assert r.status_code == 200
        assert r.json()["auto_layout"] is False


class TestInfo:
    def test_info(self, client):
        r = client.get("/api/info")
        assert r.status_code == 200
        data = r.json()
        assert "profiles_dir" in data
        assert "data_dir" in data

    def test_version(self, client):
        r = client.get("/api/version")
        assert r.status_code == 200
        data = r.json()
        assert "version" in data
        assert "app" in data


class TestAntidetect:
    def test_antidetect_options(self, client):
        r = client.get("/api/antidetect")
        assert r.status_code == 200
        data = r.json()
        assert "locale" in data
        assert "random" in data["locale"]


class TestAccounts:
    def test_empty_accounts(self, client):
        r = client.get("/api/accounts")
        assert r.status_code == 200
        assert r.json() == []

    def test_add_account(self, client, tmp_config):
        r = client.post(
            "/api/accounts",
            json={"name": "Test A", "url": "https://example.com"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Test A"
        assert data["url"] == "https://example.com"
        assert data["index"] == 1

    def test_add_and_list(self, client, tmp_config):
        client.post("/api/accounts", json={"name": "A"})
        client.post("/api/accounts", json={"name": "B"})
        r = client.get("/api/accounts")
        assert len(r.json()) == 2

    def test_delete_account(self, client, tmp_config):
        r = client.post("/api/accounts", json={"name": "X"})
        uid = r.json()["id"]
        r = client.delete(f"/api/accounts/{uid}")
        assert r.status_code == 200
        assert client.get("/api/accounts").json() == []

    def test_delete_removes_profile_dir(self, client, tmp_config):
        r = client.post("/api/accounts", json={"name": "X", "save_session": True})
        profile_dir = r.json()["profile_dir"]
        assert profile_dir
        p = Path(profile_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "cookies.sqlite").write_text("x")
        uid = r.json()["id"]

        r = client.delete(f"/api/accounts/{uid}")
        assert r.status_code == 200
        assert not p.exists()

    def test_bulk_delete(self, client, tmp_config):
        ids = []
        for i in range(3):
            r = client.post("/api/accounts", json={"name": f"A{i}"})
            ids.append(r.json()["id"])
        r = client.post("/api/accounts/bulk-delete", json={"account_ids": ids})
        assert r.status_code == 200
        assert r.json()["deleted"] == 3
        assert client.get("/api/accounts").json() == []

    def test_bulk_delete_removes_profile_dirs(self, client, tmp_config):
        dirs = []
        for i in range(2):
            r = client.post("/api/accounts", json={"name": f"B{i}", "save_session": True})
            p = Path(r.json()["profile_dir"])
            p.mkdir(parents=True, exist_ok=True)
            dirs.append(p)
        ids = [client.get("/api/accounts").json()[i]["id"] for i in range(2)]
        r = client.post("/api/accounts/bulk-delete", json={"account_ids": ids})
        assert r.status_code == 200
        for p in dirs:
            assert not p.exists()

    def test_account_has_created_at(self, client, tmp_config):
        r = client.post("/api/accounts", json={"name": "A"})
        assert r.status_code == 200
        assert "created_at" in r.json()

    def test_default_url_is_game(self, client, tmp_config):
        r = client.post("/api/accounts", json={"name": "A"})
        assert r.status_code == 200
        assert r.json()["url"] == "https://v.hitclub.latino/?a=hitclub"

    def test_default_url_config_used(self, client, tmp_config):
        client.post("/api/config", json={"default_url": "https://example.com/game"})
        r = client.post("/api/accounts", json={"name": "A"})
        assert r.status_code == 200
        assert r.json()["url"] == "https://example.com/game"


class TestBulk:
    def test_bulk_add_10(self, client, tmp_config):
        r = client.post(
            "/api/accounts/bulk",
            json={"prefix": "A", "count": 10},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 10
        names = [a["name"] for a in data["accounts"]]
        assert names == ["A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10"]

    def test_bulk_single_default(self, client, tmp_config):
        r = client.post("/api/accounts/bulk", json={"prefix": "B"})
        assert r.status_code == 200
        assert r.json()["count"] == 1
        assert r.json()["accounts"][0]["name"] == "B"

    def test_bulk_empty_prefix_rejected(self, client):
        r = client.post("/api/accounts/bulk", json={"prefix": ""})
        assert r.status_code == 400


class TestSetProfilesDir:
    def test_set_profiles_dir(self, client, tmp_config):
        new_dir = tmp_config.DATA_DIR / "custom_profiles"
        r = client.post("/api/set-profiles-dir", json={"dir": str(new_dir)})
        assert r.status_code == 200
        assert str(new_dir.resolve()) == r.json()["profiles_dir"]

    def test_set_profiles_dir_empty_rejected(self, client):
        r = client.post("/api/set-profiles-dir", json={"dir": ""})
        assert r.status_code == 400


class TestCheckProxy:
    def test_empty_proxy(self, client):
        r = client.post("/api/check-proxy", json={"proxy": ""})
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_invalid_format(self, client):
        r = client.post("/api/check-proxy", json={"proxy": "abc-def-ghi"})
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_bad_proxy_fails_gracefully(self, client):
        # Proxy không tồn tại -> trả ok=False, không crash
        r = client.post("/api/check-proxy", json={"proxy": "127.0.0.1:9:u:p"})
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert "error" in r.json()


class TestBrowserStatus:
    def test_status_endpoint(self, client):
        r = client.get("/api/browser-status")
        assert r.status_code == 200
        data = r.json()
        assert "installed" in data
        assert "version" in data


class TestWebSocket:
    def test_ws_hello(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "hello"
            assert "sessions" in data
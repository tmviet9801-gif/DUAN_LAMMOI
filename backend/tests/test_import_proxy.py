from pathlib import Path

from models import config_model


class TestImportAccounts:
    def test_import_assigns_to_free_profiles(self, client, tmp_config):
        # 2 profile chưa có account
        client.post("/api/accounts", json={"name": "P1"})
        client.post("/api/accounts", json={"name": "P2"})
        r = client.post("/api/accounts/import", json={
            "accounts": [
                {"username": "nick1", "password": "pass1"},
                {"username": "nick2", "password": "pass2"},
            ]
        })
        assert r.status_code == 200
        assert r.json()["imported"] == 2
        assert r.json()["created"] == 0
        accounts = client.get("/api/accounts").json()
        usernames = {a.get("username") for a in accounts}
        assert usernames == {"nick1", "nick2"}

    def test_import_creates_new_when_no_free(self, client, tmp_config):
        client.post("/api/accounts", json={"name": "P1"})
        r = client.post("/api/accounts/import", json={
            "accounts": [{"username": "u1", "password": "p1"}, {"username": "u2", "password": "p2"}]
        })
        assert r.status_code == 200
        assert r.json()["assigned"] == 1  # u1 gán vào P1
        assert r.json()["created"] == 1   # u2 tạo profile mới
        accounts = client.get("/api/accounts").json()
        assert len(accounts) == 2

    def test_import_empty_rejected(self, client):
        r = client.post("/api/accounts/import", json={"accounts": []})
        assert r.status_code == 400


class TestProxy:
    def test_save_proxies(self, client, tmp_config):
        r = client.post("/api/proxies", json={"proxies": ["1.2.3.4:80", "5.6.7.8:90:u:p"]})
        assert r.status_code == 200
        assert r.json()["count"] == 2
        assert client.get("/api/proxies").json()["proxies"] == ["1.2.3.4:80", "5.6.7.8:90:u:p"]

    def test_apply_to_free_profiles(self, client, tmp_config):
        client.post("/api/accounts", json={"name": "P1"})
        client.post("/api/accounts", json={"name": "P2"})
        client.post("/api/accounts", json={"name": "P3", "proxy": "9.9.9.9:1"})  # đã có proxy
        r = client.post("/api/proxies/apply", json={"proxies": ["1.1.1.1:80", "2.2.2.2:90"]})
        assert r.status_code == 200
        assert r.json()["applied"] == 2  # P1, P2; P3 đã có proxy nên không áp
        accounts = client.get("/api/accounts").json()
        proxies = {a["name"]: a["proxy"] for a in accounts}
        assert proxies["P1"] == "1.1.1.1:80"
        assert proxies["P2"] == "2.2.2.2:90"
        assert proxies["P3"] == "9.9.9.9:1"

    def test_validate(self, client, tmp_config):
        r = client.post("/api/proxies/validate", json={"proxies": ["1.2.3.4:80", "abc-def", "1.2.3.4:90:u:p"]})
        assert r.status_code == 200
        assert len(r.json()["valid"]) == 2
        assert len(r.json()["invalid"]) == 1

    def test_proxy_file_is_isolated(self, client, tmp_config):
        # ghi vào thư mục data tạm
        client.post("/api/proxies", json={"proxies": ["x:1"]})
        f = config_model.DATA_DIR / "proxies.json"
        assert f.exists()
        assert "x:1" in f.read_text(encoding="utf-8")

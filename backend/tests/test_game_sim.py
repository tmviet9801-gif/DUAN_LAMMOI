import time


class TestGameSimConfig:
    def test_default_config_has_groups(self, client):
        r = client.get("/api/gamesim/default-config")
        assert r.status_code == 200
        cfg = r.json()
        assert "groups" in cfg
        assert "scenario" in cfg
        assert "timing" in cfg

    def test_default_config_uses_existing_accounts(self, client, tmp_config):
        client.post("/api/accounts", json={"name": "ZMain"})
        client.post("/api/accounts", json={"name": "ZSup1"})
        cfg = client.get("/api/gamesim/default-config").json()
        # nếu có account -> main = account đầu
        assert cfg["groups"]["A"]["main"] == "ZMain"
        assert "ZSup1" in cfg["groups"]["A"]["supports"]


class TestGameSimRun:
    def _poll_until(self, client, pred, tries=60, wait=0.25):
        for _ in range(tries):
            if pred(client):
                return True
            time.sleep(wait)
        return False

    def test_mock_scenario_completes(self, client, tmp_config):
        cfg = client.get("/api/gamesim/default-config").json()
        cfg["rounds"] = 3
        cfg["game"] = {"adapter": "mock", "force": "main_wins", "join_fail_rate": 0.0, "mock_delay": 0.0}

        r = client.post("/api/gamesim/start", json=cfg)
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        ok = self._poll_until(client, lambda c: not c.get("/api/gamesim/status").json()["running"])
        assert ok, "game sim chưa chạy xong"

        status = client.get("/api/gamesim/status").json()
        for g, s in status["groups"].items():
            assert s["state"] == "FINISHED"

        metrics = client.get("/api/gamesim/metrics").json()
        g = list(metrics.keys())[0]
        assert metrics[g]["total_rounds"] == 3
        assert metrics[g]["first_move_accuracy"] == 1.0  # force main_wins -> đúng 100%
        assert metrics[g]["join_ok"] >= 1

        events = client.get("/api/gamesim/events", params={"limit": 10}).json()
        assert len(events) > 0
        # events dùng run_id theo group (prefix + _group)
        assert any((e["run_id"] or "").startswith(run_id) for e in events)

    def test_mock_scenario_reset_on_main_lose(self, client, tmp_config):
        cfg = client.get("/api/gamesim/default-config").json()
        cfg["rounds"] = 3
        cfg["game"] = {"adapter": "mock", "force": "main_loses", "join_fail_rate": 0.0, "mock_delay": 0.0}

        client.post("/api/gamesim/start", json=cfg)
        ok = self._poll_until(client, lambda c: not c.get("/api/gamesim/status").json()["running"])
        assert ok

        metrics = client.get("/api/gamesim/metrics").json()
        g = list(metrics.keys())[0]
        assert metrics[g]["total_rounds"] == 3
        events = client.get("/api/gamesim/events", params={"limit": 100}).json()
        # luồng reset (main_left -> RESETTING) đã xảy ra
        assert any(e["state_from"] == "LEAVING" and e["state_to"] == "RESETTING" for e in events)

    def test_stop(self, client, tmp_config):
        cfg = client.get("/api/gamesim/default-config").json()
        cfg["rounds"] = 500
        cfg["game"] = {"adapter": "mock", "force": "auto", "join_fail_rate": 0.0, "mock_delay": 0.05}
        client.post("/api/gamesim/start", json=cfg)
        time.sleep(0.4)
        r = client.post("/api/gamesim/stop")
        assert r.status_code == 200
        assert client.get("/api/gamesim/status").json()["running"] is False


class TestGameSimGroups:
    def test_save_config(self, client, tmp_config):
        r = client.post("/api/gamesim/config", json={
            "groups": {"A": {"main": "MainA", "supports": ["S1"]}},
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_get_config_returns_saved_groups(self, client, tmp_config):
        client.post("/api/gamesim/config", json={
            "groups": {"X": {"main": "M1", "supports": ["S1", "S2"]}},
        })
        r = client.get("/api/gamesim/config")
        assert r.status_code == 200
        groups = r.json()["groups"]
        assert "X" in groups
        assert groups["X"]["main"] == "M1"
        assert "S1" in groups["X"]["supports"]

    def test_start_uses_saved_groups(self, client, tmp_config):
        client.post("/api/gamesim/config", json={
            "groups": {"A": {"main": "MainA", "supports": ["S1", "S2"]}},
        })
        default = client.get("/api/gamesim/default-config").json()
        assert "A" in default["groups"]
        assert default["groups"]["A"]["main"] == "MainA"

    def test_empty_groups_rejected(self, client):
        r = client.post("/api/gamesim/config", json={"groups": {}})
        assert r.status_code == 400

import json

from models import config_model as config


def test_default_config_merged(tmp_config):
    cfg = config.load_config()
    assert cfg["grid"]["cols"] == 5
    assert cfg["grid"]["gap"] == 8
    assert cfg["grid"]["margin"] == 4
    assert cfg["window"]["width"] == 0
    assert cfg["window"]["height"] == 0
    assert cfg["open_direction"] == "row"
    assert cfg["default_count"] == 10
    assert cfg["auto_layout"] is True
    assert "profiles_dir" in cfg


def test_save_config_roundtrip(tmp_config):
    cfg = config.load_config()
    cfg["grid"]["cols"] = 3
    cfg["window"]["width"] = 1000
    cfg["open_direction"] = "col"
    config.save_config(cfg)

    loaded = config.load_config()
    assert loaded["grid"]["cols"] == 3
    assert loaded["window"]["width"] == 1000
    assert loaded["open_direction"] == "col"


def test_partial_config_merges_defaults(tmp_config):
    config.CONFIG_FILE.write_text(
        json.dumps({"grid": {"cols": 2}}), encoding="utf-8"
    )
    cfg = config.load_config()
    assert cfg["grid"]["cols"] == 2
    assert cfg["grid"]["gap"] == 8
    assert cfg["grid"]["margin"] == 4


def test_corrupt_config_falls_back_to_default(tmp_config):
    config.CONFIG_FILE.write_text("{not json", encoding="utf-8")
    cfg = config.load_config()
    assert cfg["grid"]["cols"] == 5


def test_profiles_dir_default(tmp_config):
    p = config.get_profiles_dir()
    assert p == config.DATA_DIR / "profiles"
    assert p.exists()


def test_profiles_dir_custom(tmp_config):
    custom = tmp_config.DATA_DIR / "my_profiles"
    cfg = config.load_config()
    cfg["profiles_dir"] = str(custom)
    config.save_config(cfg)
    p = config.get_profiles_dir()
    assert p == custom.resolve()
    assert p.exists()


def test_profiles_dir_expand_env(tmp_config, monkeypatch):
    monkeypatch.setenv("TMP_PROFILES", str(tmp_config.DATA_DIR / "env_profiles"))
    cfg = config.load_config()
    cfg["profiles_dir"] = "%TMP_PROFILES%"
    config.save_config(cfg)
    p = config.get_profiles_dir()
    assert p.name == "env_profiles"


def test_make_profile_dir_slugify(tmp_config):
    d = config.make_profile_dir("FB Tài khoản 1", "12345678abcdef")
    assert d.endswith("fb-tai-khoan-1-12345678")
    assert str(config.DATA_DIR / "profiles") in d


def test_accounts_roundtrip(tmp_config):
    accounts = [{"id": "a1", "name": "A"}, {"id": "a2", "name": "B"}]
    config.save_accounts(accounts)
    assert config.load_accounts() == accounts


def test_load_accounts_empty(tmp_config):
    assert config.load_accounts() == []

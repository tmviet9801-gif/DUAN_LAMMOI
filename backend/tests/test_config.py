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


def test_new_account_record_always_save_session(tmp_config):
    rec = config.new_account_record({"name": "X", "save_session": False})
    assert rec["save_session"] is True
    assert rec["profile_dir"]


def test_ensure_accounts_save_session_migrates(tmp_config):
    accs = [
        {"id": "a1", "name": "A", "save_session": False, "profile_dir": ""},
        {"id": "a2", "name": "B", "save_session": True, "profile_dir": ""},
    ]
    out, n = config.ensure_accounts_save_session(accs)
    for a in out:
        assert a["save_session"] is True
        assert a["profile_dir"]
    assert n == 3


def test_default_config_has_default_url(tmp_config):
    cfg = config.load_config()
    assert cfg["default_url"] == "https://v.hitclub.latino/?a=hitclub"


def test_ensure_profile_dirs_current_fixes_moved_project(tmp_config, monkeypatch):
    """Di chuyển/đổi tên thư mục dự án làm profile_dir tuyệt đối chết theo.

    Trước đây chỉ có ensure_accounts_save_session, mà hàm đó chỉ điền khi THIẾU
    profile_dir nên không phát hiện đường dẫn cũ đã hỏng -> Chromium tự tạo
    profile RỖNG ở đó, mất sạch session đăng nhập của mọi account.
    """
    from models import config_model as config

    base = config.get_profiles_dir()
    accounts = [
        {"id": "a1", "name": "Account 01",
         "profile_dir": r"C:\duong\dan\cu\backend\data\profiles\account01-6f50bda5"},
        {"id": "a2", "name": "Account 02",
         "profile_dir": str(base / "account02-ed7a8fb2")},  # đã đúng, phải giữ nguyên
        {"id": "a3", "name": "Account 03"},                 # thiếu hẳn, không đụng tới
    ]

    out, n = config.ensure_profile_dirs_current(accounts)

    assert n == 1, "chỉ account có đường dẫn lạc mới bị nắn"
    # Nắn về thư mục hiện tại nhưng GIỮ NGUYÊN tên thư mục -> dùng lại đúng
    # dữ liệu profile (cookie/login) đang nằm sẵn ở đó.
    assert out[0]["profile_dir"] == str(base / "account01-6f50bda5")
    assert out[1]["profile_dir"] == str(base / "account02-ed7a8fb2")
    assert "profile_dir" not in out[2]


def test_is_game_url_matches_any_domain():
    """Cổng game đổi TLD liên tục — không được khớp cứng tên miền đầy đủ."""
    from platform_config import is_game_url

    for u in ["https://v.hitclub.latino/?a=hitclub", "https://v.hitclub.bike/",
              "https://v.hitclub.chat/", "https://v.hitclub.email/",
              "https://PLAY.HITCLUB.voting/"]:
        assert is_game_url(u), u
    for u in ["https://google.com", "about:blank", "", None]:
        assert not is_game_url(u)

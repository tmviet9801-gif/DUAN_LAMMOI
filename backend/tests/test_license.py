import time

import license as lic


def _gen(days=30, max_tabs=10):
    mid = lic.get_machine_id()
    key = lic.make_key(mid, days, max_tabs)
    return mid, key


def test_make_and_validate():
    mid, key = _gen()
    v = lic.validate_key(key, mid)
    assert v["valid"] is True
    assert v["max_tabs"] == 10
    assert v["expiry"] > time.time()


def test_wrong_machine_rejected():
    key = lic.make_key("machine-AAA", 30, 10)
    v = lic.validate_key(key, "machine-BBB")
    assert v["valid"] is False
    assert v["reason"] == "wrong_machine"


def test_expired_rejected():
    key = lic.make_key("machine-X", -1, 10)
    v = lic.validate_key(key, "machine-X")
    assert v["valid"] is False
    assert v["reason"] == "expired"


def test_invalid_key():
    assert lic.validate_key("AUTO-bad-key", "x")["reason"] == "invalid_key"


def test_activate_status_deactivate(tmp_path, monkeypatch):
    import license as lic

    monkeypatch.setattr(lic, "LICENSE_FILE", tmp_path / "license.json")
    mid = lic.get_machine_id()
    key = lic.make_key(mid, 30, 10)
    r = lic.activate(key)
    assert r["valid"] is True
    st = lic.status()
    assert st["activated"] is True
    assert st["valid"] is True
    assert st["max_tabs"] == 10
    lic.deactivate()
    st2 = lic.status()
    assert st2["activated"] is False

"""Test phần kiểm tra license với máy chủ (thu hồi + ân hạn offline)."""
import asyncio
import time

import pytest

import license as lic


@pytest.fixture(autouse=True)
def _secret_cho_test(monkeypatch):
    """Bản phát hành tắt HMAC và không có SECRET. Test key v1 thì bật lại."""
    monkeypatch.setattr(lic, "SECRET", b"secret-chi-dung-trong-test")
    monkeypatch.setattr(lic, "ALLOW_LEGACY_HMAC", True)


@pytest.fixture
def activated(tmp_path, monkeypatch):
    """License đã kích hoạt hợp lệ, lưu vào file tạm."""
    monkeypatch.setattr(lic, "LICENSE_FILE", tmp_path / "license.json")
    mid = lic.get_machine_id()
    key = lic.make_key(mid, 30, 10)
    lic.activate(key)
    return mid, key


def _enable_server(monkeypatch, grace_days=7):
    monkeypatch.setattr(lic, "LICENSE_SERVER_URL", "https://license.example.com")
    monkeypatch.setattr(lic, "LICENSE_OFFLINE_GRACE_DAYS", grace_days)


def _set_check(verdict, age_seconds=0):
    data = lic.load_license()
    data["server_check"] = {"at": int(time.time()) - age_seconds, "verdict": verdict}
    lic.save_license(data)


# --- máy chủ tắt: giữ nguyên hành vi cũ ------------------------------------

def test_server_disabled_behaves_as_before(activated, monkeypatch):
    monkeypatch.setattr(lic, "LICENSE_SERVER_URL", "")
    st = lic.status()
    assert st["valid"] is True
    assert st["server_enabled"] is False
    # Không kiểm tra online thì không gắn kết luận nào của máy chủ.
    assert "server_verdict" not in st


def test_server_disabled_ignores_stale_check(activated, monkeypatch):
    """Tắt máy chủ thì kết quả cũ (kể cả 'revoked') không được dùng để khoá."""
    monkeypatch.setattr(lic, "LICENSE_SERVER_URL", "")
    _set_check("revoked")
    assert lic.status()["valid"] is True


# --- máy chủ bật: thu hồi có hiệu lực ---------------------------------------

@pytest.mark.parametrize("verdict", ["revoked", "suspended", "key_not_issued"])
def test_server_verdict_blocks_valid_signature(activated, monkeypatch, verdict):
    """Đây là lỗ hổng của bản offline thuần: chữ ký còn đúng nhưng key đã bị thu hồi."""
    _enable_server(monkeypatch)
    _set_check(verdict)

    st = lic.status()
    assert st["valid"] is False
    assert st["reason"] == verdict
    assert st["message"]          # có câu giải thích cho người dùng
    assert lic.max_tabs() == 0    # chặn luôn ở chỗ mở tab


def test_server_says_valid(activated, monkeypatch):
    _enable_server(monkeypatch)
    _set_check("valid")
    st = lic.status()
    assert st["valid"] is True
    assert st["server_verdict"] == "valid"
    assert st["max_tabs"] == 10


# --- ân hạn khi mất mạng ----------------------------------------------------

def test_grace_period_allows_offline(activated, monkeypatch):
    """Mất mạng 3 ngày, ân hạn 7 ngày -> vẫn dùng được."""
    _enable_server(monkeypatch, grace_days=7)
    _set_check("valid", age_seconds=3 * 86400)

    st = lic.status()
    assert st["valid"] is True
    assert st["grace_days_left"] == 4  # 7 ngày ân hạn - 3 ngày đã trôi


def test_grace_period_expires(activated, monkeypatch):
    """Mất mạng 8 ngày, ân hạn 7 ngày -> khoá."""
    _enable_server(monkeypatch, grace_days=7)
    _set_check("valid", age_seconds=8 * 86400)

    st = lic.status()
    assert st["valid"] is False
    assert st["reason"] == "offline_too_long"
    assert lic.max_tabs() == 0


def test_never_checked_counts_from_activation(activated, monkeypatch):
    """Chưa kiểm tra được lần nào thì ân hạn đếm từ lúc kích hoạt."""
    _enable_server(monkeypatch, grace_days=7)

    # vừa kích hoạt -> còn trong ân hạn
    assert lic.status()["valid"] is True

    # kích hoạt từ 10 ngày trước, chưa lần nào gọi được máy chủ -> khoá
    data = lic.load_license()
    data["activated_at"] = int(time.time()) - 10 * 86400
    lic.save_license(data)
    st = lic.status()
    assert st["valid"] is False
    assert st["reason"] == "offline_too_long"


def test_zero_grace_requires_online(activated, monkeypatch):
    """Ân hạn 0 ngày = bắt buộc phải online. Kết quả 'valid' vẫn cho chạy."""
    _enable_server(monkeypatch, grace_days=0)
    _set_check("valid", age_seconds=30 * 86400)
    assert lic.status()["valid"] is True


# --- check_online -----------------------------------------------------------

def test_check_online_disabled(activated, monkeypatch):
    monkeypatch.setattr(lic, "LICENSE_SERVER_URL", "")
    assert asyncio.run(lic.check_online())["error"] == "disabled"


def test_network_error_keeps_previous_result(activated, monkeypatch):
    """Rớt mạng KHÔNG được xoá kết quả cũ, nếu không khách mất quyền dùng oan."""
    _enable_server(monkeypatch)
    _set_check("valid", age_seconds=86400)
    before = lic.load_license()["server_check"]

    # URL không tồn tại -> httpx ném lỗi
    monkeypatch.setattr(lic, "LICENSE_SERVER_URL", "http://127.0.0.1:1/")
    result = asyncio.run(lic.check_online())

    assert result["ok"] is False
    assert result["error"] == "unreachable"
    assert lic.load_license()["server_check"] == before
    assert lic.status()["valid"] is True

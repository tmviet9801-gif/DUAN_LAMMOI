"""Test key Ed25519 (v2) — chữ ký bất đối xứng, app chỉ giữ khoá công khai.

Điểm mấu chốt của v2: app KHÔNG giữ khoá ký, nên dịch ngược file exe cũng
không sinh nổi key. Test dưới đây khoá lại đúng tính chất đó.
"""
import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import license as lic


@pytest.fixture(autouse=True)
def _secret_cho_test(monkeypatch):
    """Bản phát hành tắt HMAC và không có SECRET. Test key v1 thì bật lại."""
    monkeypatch.setattr(lic, "SECRET", b"secret-chi-dung-trong-test")
    monkeypatch.setattr(lic, "ALLOW_LEGACY_HMAC", True)


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


@pytest.fixture
def keypair(monkeypatch):
    """Cặp khoá Ed25519 dùng riêng cho test, nạp khoá công khai vào app."""
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes_raw()
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", base64.b64encode(public_raw).decode())
    return private


def _make_v2(private, machine_id="may-test", expiry=9999999999, max_tabs=10, features="game"):
    """Sinh key v2 giống hệt cách portal làm."""
    payload = f"{machine_id}|{expiry}|{max_tabs}|{features}"
    payload_b64 = _b64url_nopad(payload.encode())
    sig = private.sign(payload_b64.encode())  # ký trên CHUỖI base64, không phải payload thô
    return f"AUTO2.{payload_b64}.{_b64url_nopad(sig)}"


# --- đọc key hợp lệ ---------------------------------------------------------

def test_doc_duoc_key_v2(keypair):
    key = _make_v2(keypair, machine_id="may-abc", max_tabs=20, features="game,auto")
    data = lic.parse_key(key)
    assert data == {
        "machine_id": "may-abc",
        "expiry": 9999999999,
        "max_tabs": 20,
        "features": "game,auto",
        "algo": "ed25519",
    }


def test_validate_key_v2(keypair):
    key = _make_v2(keypair, machine_id="may-abc")
    assert lic.validate_key(key, "may-abc")["valid"] is True
    assert lic.validate_key(key, "may-khac")["reason"] == "wrong_machine"


def test_key_v2_het_han(keypair):
    key = _make_v2(keypair, machine_id="may-abc", expiry=1)
    assert lic.validate_key(key, "may-abc")["reason"] == "expired"


# --- chống giả mạo ----------------------------------------------------------

def test_sua_payload_bi_tu_choi(keypair):
    """Nâng 10 tab lên 999 mà giữ nguyên chữ ký -> phải hỏng."""
    key = _make_v2(keypair, machine_id="may-abc", max_tabs=10)
    _, payload_b64, sig_b64 = key.split(".")

    payload = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)).decode()
    gian_lan = payload.replace("|10|", "|999|")
    key_gia = f"AUTO2.{_b64url_nopad(gian_lan.encode())}.{sig_b64}"

    assert lic.parse_key(key_gia) is None


def test_khoa_cong_khai_khac_bi_tu_choi(keypair, monkeypatch):
    key = _make_v2(keypair, machine_id="may-abc")
    khac = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", base64.b64encode(khac).decode())
    assert lic.parse_key(key) is None


def test_ky_bang_khoa_rieng_khac_bi_tu_choi(keypair):
    """Kẻ tấn công tự sinh cặp khoá riêng của mình rồi ký key."""
    key_gia = _make_v2(Ed25519PrivateKey.generate(), machine_id="may-cua-ke-tan-cong", max_tabs=50)
    assert lic.parse_key(key_gia) is None


def test_key_v2_hong_dinh_dang(keypair):
    for xau in ["AUTO2.", "AUTO2.abc", "AUTO2.a.b.c", "AUTO2.@@@.###", "khong-phai-key"]:
        assert lic.parse_key(xau) is None


def test_khong_co_khoa_cong_khai_thi_tu_choi(keypair, monkeypatch):
    key = _make_v2(keypair, machine_id="may-abc")
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", "")
    assert lic.parse_key(key) is None


# --- đây là lý do tồn tại của v2 -------------------------------------------

def test_app_khong_tu_sinh_duoc_key_v2(keypair, monkeypatch):
    """Tắt HMAC rồi thì SECRET nằm trong exe cũng thành vô dụng.

    Kẻ tấn công unpack exe, lấy SECRET, tự sinh key cho máy mình với 50 tab —
    app phải từ chối, vì bản thương mại chỉ chấp nhận chữ ký Ed25519 mà khoá
    ký của nó không có trong exe.
    """
    monkeypatch.setattr(lic, "ALLOW_LEGACY_HMAC", False)

    key_tu_che = lic.make_key("may-cua-ke-tan-cong", 3650, 50, "game,auto")
    assert lic.parse_key(key_tu_che) is None

    # Key thật do portal cấp thì vẫn dùng được bình thường.
    assert lic.parse_key(_make_v2(keypair, machine_id="may-abc")) is not None


def test_bat_legacy_thi_key_hmac_lai_chay(keypair, monkeypatch):
    """Ghi lại đánh đổi: bật legacy trong lúc chuyển đổi là mở lại đúng lỗ hổng cũ."""
    monkeypatch.setattr(lic, "ALLOW_LEGACY_HMAC", True)
    key_tu_che = lic.make_key("may-cua-ke-tan-cong", 3650, 50)
    assert lic.parse_key(key_tu_che) is not None


def test_hai_dinh_dang_song_song(keypair, monkeypatch):
    """Trong lúc chuyển đổi, app phải hiểu cả key cũ lẫn key mới."""
    monkeypatch.setattr(lic, "ALLOW_LEGACY_HMAC", True)

    v1 = lic.make_key("may-abc", 30, 10)
    v2 = _make_v2(keypair, machine_id="may-abc")

    assert lic.parse_key(v1)["algo"] == "hmac"
    assert lic.parse_key(v2)["algo"] == "ed25519"


# --- bản gửi khách phải sạch bí mật ----------------------------------------

def test_ban_build_khong_co_secret_thi_key_v1_tu_vo_hieu(keypair, monkeypatch):
    """Bản build cho khách không có AUTOTOOL_LEGACY_SECRET.

    Kể cả khi ai đó bật ALLOW_LEGACY_HMAC, không có SECRET thì key v1 vẫn hỏng
    — vì không có gì để kiểm tra chữ ký. Đây là lớp chặn thứ hai, độc lập với cờ.
    """
    monkeypatch.setattr(lic, "ALLOW_LEGACY_HMAC", True)
    monkeypatch.setattr(lic, "SECRET", b"")

    assert lic.parse_key("AUTO-0123456789abcdef-YWJj") is None
    # Key Ed25519 vẫn chạy bình thường: nó không cần SECRET.
    assert lic.parse_key(_make_v2(keypair, machine_id="may-abc")) is not None


def test_khong_co_secret_thi_khong_ky_duoc(monkeypatch):
    """make_key phải báo lỗi rõ thay vì lặng lẽ ký bằng chuỗi rỗng."""
    monkeypatch.setattr(lic, "SECRET", b"")
    with pytest.raises(RuntimeError, match="AUTOTOOL_LEGACY_SECRET"):
        lic.make_key("may-abc", 30, 10)


def test_ma_nguon_khong_hardcode_bi_mat():
    """Chặn việc ai đó vô tình dán lại secret vào mã nguồn."""
    from pathlib import Path

    goc = Path(__file__).resolve().parent.parent
    cam = ["AutoToolLicenseSecret", "AutoToolOwner@"]
    for ten in ["license.py", "platform_config.py"]:
        noi_dung = (goc / ten).read_text(encoding="utf-8")
        for chuoi in cam:
            assert chuoi not in noi_dung, f"{ten} dang hardcode bi mat: {chuoi}"


# --- bản gửi khách phải sạch bí mật ----------------------------------------

def test_ban_build_khong_co_secret_thi_key_v1_tu_vo_hieu(keypair, monkeypatch):
    """Bản build cho khách không có AUTOTOOL_LEGACY_SECRET.

    Kể cả khi ai đó bật ALLOW_LEGACY_HMAC, không có SECRET thì key v1 vẫn hỏng
    — vì không có gì để kiểm tra chữ ký. Đây là lớp chặn thứ hai, độc lập với cờ.
    """
    monkeypatch.setattr(lic, "ALLOW_LEGACY_HMAC", True)
    monkeypatch.setattr(lic, "SECRET", b"")

    assert lic.parse_key("AUTO-0123456789abcdef-YWJj") is None
    # Key Ed25519 vẫn chạy bình thường: nó không cần SECRET.
    assert lic.parse_key(_make_v2(keypair, machine_id="may-abc")) is not None


def test_khong_co_secret_thi_khong_ky_duoc(monkeypatch):
    """make_key phải báo lỗi rõ thay vì lặng lẽ ký bằng chuỗi rỗng."""
    monkeypatch.setattr(lic, "SECRET", b"")
    with pytest.raises(RuntimeError, match="AUTOTOOL_LEGACY_SECRET"):
        lic.make_key("may-abc", 30, 10)


def test_ma_nguon_khong_hardcode_bi_mat():
    """Chặn việc ai đó vô tình dán lại secret vào mã nguồn."""
    from pathlib import Path

    goc = Path(__file__).resolve().parent.parent
    cam = ["AutoToolLicenseSecret", "AutoToolOwner@"]
    for ten in ["license.py", "platform_config.py"]:
        noi_dung = (goc / ten).read_text(encoding="utf-8")
        for chuoi in cam:
            assert chuoi not in noi_dung, f"{ten} dang hardcode bi mat: {chuoi}"

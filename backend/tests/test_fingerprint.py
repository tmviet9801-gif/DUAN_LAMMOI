from models.fingerprint_model import (
    DESKTOP_OS,
    diverse_os,
    extract_os,
    random_chrome_ua,
    random_desktop_os,
)


def test_random_desktop_os_valid():
    for _ in range(50):
        assert random_desktop_os() in DESKTOP_OS


def test_random_chrome_ua_format():
    for _ in range(20):
        ua = random_chrome_ua("windows")
        assert ua.startswith("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        assert "Chrome/" in ua
        assert "Safari/537.36" in ua


def test_random_chrome_ua_version_range():
    for _ in range(30):
        ua = random_chrome_ua("windows")
        version = ua.split("Chrome/")[1].split(" ")[0]
        major = int(version.split(".")[0])
        assert 126 <= major <= 148


def test_random_chrome_ua_no_os():
    ua = random_chrome_ua()
    assert "Chrome/" in ua


def test_extract_os():
    assert extract_os(random_chrome_ua("windows")) == "windows"
    assert extract_os(random_chrome_ua("macos")) == "macos"
    assert extract_os(random_chrome_ua("linux")) == "linux"
    assert extract_os("Mozilla/5.0 (X11; FreeBSD)") == "unknown"


def test_diverse_os_avoids_used():
    used = {"windows"}
    for _ in range(30):
        assert diverse_os(used) in ("macos", "linux")


def test_diverse_os_all_used_returns_any():
    result = diverse_os(set(DESKTOP_OS))
    assert result in DESKTOP_OS


def test_diverse_os_empty_returns_valid():
    assert diverse_os([]) in DESKTOP_OS

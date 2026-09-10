"""App đang chạy mà license chết thì phải bị dừng ngay, không đợi khởi động lại.

Kiểm tra license lúc mở tab và lúc bấm chạy là chưa đủ: máy đã mở sẵn 10 tab và
auto flow đang chạy thì thu hồi license không chạm được tới nó — khách cứ để app
mở là dùng tiếp vô thời hạn. Watchdog phải chủ động dừng.
"""
import asyncio
import types

import pytest

import main


class _Flow:
    def __init__(self):
        self.da_dung = False

    def stop(self):
        self.da_dung = True


class _Manager:
    def __init__(self):
        self.da_dong = False

    async def close_all(self):
        self.da_dong = True


class _Events:
    def __init__(self):
        self.da_gui = []

    def emit(self, kind, **data):
        self.da_gui.append({"type": kind, **data})


def _app_gia():
    """App giả có đủ ba thứ watchdog cần chạm tới."""
    app = types.SimpleNamespace()
    app.state = types.SimpleNamespace()
    app.state.auto_flow = {"flow": _Flow()}
    app.state.manager = _Manager()
    app.state.events = _Events()
    return app


# --- hành động khoá --------------------------------------------------------

def test_khoa_app_dung_auto_flow_va_dong_trinh_duyet():
    app = _app_gia()
    asyncio.run(
        main._khoa_app_vi_license(app, {"reason": "revoked", "message": "License đã bị thu hồi"})
    )

    assert app.state.auto_flow["flow"].da_dung is True
    assert app.state.manager.da_dong is True

    su_kien = app.state.events.da_gui
    assert len(su_kien) == 1
    assert su_kien[0]["type"] == "license_invalid"
    assert su_kien[0]["reason"] == "revoked"
    assert "thu hồi" in su_kien[0]["message"]


def test_khoa_app_van_chay_khi_khong_co_auto_flow():
    """Chưa chạy auto flow thì vẫn phải đóng trình duyệt và báo giao diện."""
    app = _app_gia()
    app.state.auto_flow = None

    asyncio.run(main._khoa_app_vi_license(app, {"reason": "expired", "message": "Hết hạn"}))

    assert app.state.manager.da_dong is True
    assert app.state.events.da_gui[0]["type"] == "license_invalid"


def test_mot_phan_hong_khong_chan_phan_con_lai():
    """Đóng trình duyệt lỗi thì vẫn phải báo được lên giao diện."""
    app = _app_gia()

    async def _no(): raise RuntimeError("chrome treo")
    app.state.manager.close_all = _no

    asyncio.run(main._khoa_app_vi_license(app, {"reason": "revoked", "message": "Thu hồi"}))

    assert app.state.auto_flow["flow"].da_dung is True
    assert app.state.events.da_gui[0]["type"] == "license_invalid"


# --- vòng lặp watchdog -----------------------------------------------------

def _chay_watchdog_mot_vong(monkeypatch, app, trang_thai, so_vong=1):
    """Chạy watchdog đúng `so_vong` vòng rồi thoát bằng cách cho sleep ném lỗi."""
    import license as lic

    monkeypatch.setattr(lic, "server_enabled", lambda: False)
    monkeypatch.setattr(lic, "status", lambda: trang_thai)

    dem = {"n": 0}

    async def _sleep_gia(_):
        dem["n"] += 1
        if dem["n"] >= so_vong:
            raise asyncio.CancelledError
    monkeypatch.setattr(main.asyncio, "sleep", _sleep_gia)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._license_watchdog(app))


def test_watchdog_khoa_app_khi_license_chet(monkeypatch):
    app = _app_gia()
    _chay_watchdog_mot_vong(
        monkeypatch, app,
        {"valid": False, "activated": True, "reason": "revoked", "message": "Đã thu hồi"},
    )
    assert app.state.manager.da_dong is True
    assert app.state.auto_flow["flow"].da_dung is True


def test_watchdog_khong_dung_gi_khi_license_con_han(monkeypatch):
    app = _app_gia()
    _chay_watchdog_mot_vong(monkeypatch, app, {"valid": True, "activated": True})

    assert app.state.manager.da_dong is False
    assert app.state.auto_flow["flow"].da_dung is False
    assert app.state.events.da_gui == []


def test_watchdog_bo_qua_may_chua_kich_hoat(monkeypatch):
    """Chưa nhập key lần nào thì màn hình khoá đã hiện sẵn, không cần đóng gì."""
    app = _app_gia()
    _chay_watchdog_mot_vong(
        monkeypatch, app,
        {"valid": False, "activated": False, "reason": "not_activated"},
    )
    assert app.state.manager.da_dong is False
    assert app.state.events.da_gui == []


def test_watchdog_chi_khoa_mot_lan(monkeypatch):
    """Không được đóng trình duyệt lại mỗi phút khi license vẫn đang chết."""
    app = _app_gia()
    _chay_watchdog_mot_vong(
        monkeypatch, app,
        {"valid": False, "activated": True, "reason": "revoked", "message": "Đã thu hồi"},
        so_vong=5,
    )
    assert len(app.state.events.da_gui) == 1

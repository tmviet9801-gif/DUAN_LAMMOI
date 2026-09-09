"""Check Live: đọc trạng thái thật rồi cập nhật database.

Trọng tâm: khoá xác minh đồng đội là TÊN IN-GAME (`character_name`), không phải
tên đăng nhập. Hai tên chỉ khác một ký tự (`nicktestxabai1` vs
`nicktestxxabai1`) nên nhầm là khớp sai người — Account chính có thể ngồi xả
bài với khách lạ.
"""
import pytest

from controllers.auto_flow_controller.check_live import (
    apply_to_account,
    canh_bao_trung_ten,
    check_live,
    check_one_profile,
)


def test_ghi_ten_in_game_khi_database_con_trong():
    acc = {"name": "Account03", "username": "dangnhap03", "character_name": None}
    changed = apply_to_account(acc, {
        "ten_in_game": "nicktestxxabai3", "uid": "aB3cD4", "so_du": 12345,
    })
    assert acc["character_name"] == "nicktestxxabai3"
    assert acc["uid"] == "aB3cD4"
    assert acc["game_username"] == "aB3cD4"
    assert acc["balance"] == 12345
    assert any("character_name" in c for c in changed)


def test_khong_ghi_de_bang_gia_tri_rong():
    """Đọc hụt (profile chưa mở) KHÔNG được xoá dữ liệu cũ trong database."""
    acc = {"name": "Account 01", "character_name": "nicktestxxabai1",
           "uid": "eXBrqK5a", "balance": 95_745}
    changed = apply_to_account(acc, {"ten_in_game": None, "uid": None, "so_du": None})
    assert changed == []
    assert acc["character_name"] == "nicktestxxabai1"
    assert acc["uid"] == "eXBrqK5a"
    assert acc["balance"] == 95_745


def test_cap_nhat_khi_ten_in_game_doi():
    acc = {"name": "Account 01", "character_name": "ten_cu"}
    changed = apply_to_account(acc, {"ten_in_game": "ten_moi"})
    assert acc["character_name"] == "ten_moi"
    assert changed and "ten_cu -> ten_moi" in changed[0]


def test_khong_nham_sang_ten_dang_nhap():
    """Tên đăng nhập và tên in-game chỉ khác MỘT ký tự — không được lẫn."""
    acc = {"name": "Account 01", "username": "nicktestxabai1",
           "character_name": None}
    apply_to_account(acc, {"ten_in_game": "nicktestxxabai1"})
    assert acc["character_name"] == "nicktestxxabai1"
    assert acc["username"] == "nicktestxabai1", "tên đăng nhập phải giữ nguyên"
    assert acc["character_name"] != acc["username"]


def test_canh_bao_khi_hai_account_trung_ten_in_game():
    """Trùng tên in-game thì không phân biệt được ai với ai khi ghép bàn."""
    accs = [
        {"name": "Account 01", "character_name": "trung_ten"},
        {"name": "Account 02", "character_name": "Trung_Ten"},   # khác hoa/thường
        {"name": "Account03", "character_name": "rieng_biet"},
        {"name": "Account04", "character_name": None},           # trống -> bỏ qua
    ]
    canh_bao = canh_bao_trung_ten(accs)
    assert len(canh_bao) == 1
    assert "Account 01" in canh_bao[0] and "Account 02" in canh_bao[0]


def test_khong_canh_bao_khi_moi_ten_rieng_biet():
    accs = [
        {"name": "Account 01", "character_name": "nicktestxxabai1"},
        {"name": "Account 02", "character_name": "nicktestxxabai2"},
    ]
    assert canh_bao_trung_ten(accs) == []


# ---------- đọc trạng thái sống ----------

class _FakePage:
    def __init__(self, data):
        self._data = data

    async def evaluate(self, expression, arg=None, isolated_context=True):
        return self._data


class _FakeAdapter:
    def __init__(self, pages):
        self._pages = pages

    async def _page(self, name):
        return self._pages.get(name)


class _FakeHub:
    def __init__(self, states):
        self._states = states

    def get_profile_state(self, name):
        return self._states.get(name)


@pytest.mark.anyio
async def test_doc_tu_trang_khi_extension_da_nap():
    adapter = _FakeAdapter({"Account 01": _FakePage({
        "dn": "nicktestxxabai1", "u": "abc", "uid": "eXBrqK5a",
        "balance": 95_745, "hooked": True, "on_login": False,
    })})
    live = await check_one_profile(adapter, None, {"name": "Account 01"})
    assert live["mo"] is True
    assert live["dang_nhap"] is True
    assert live["ten_in_game"] == "nicktestxxabai1"
    assert live["so_du"] == 95_745
    assert live["nguon"] == "trang"
    assert live["loi"] is None


@pytest.mark.anyio
async def test_bao_loi_khi_extension_chua_nap():
    """Chưa nạp extension thì mọi biến trên trang vô nghĩa — phải báo, không đoán."""
    adapter = _FakeAdapter({"Account 01": _FakePage({"hooked": False})})
    live = await check_one_profile(adapter, None, {"name": "Account 01"})
    assert live["ten_in_game"] is None
    assert "Extension chưa nạp" in live["loi"]


@pytest.mark.anyio
async def test_du_phong_bang_hub_khi_trang_khong_co_du_lieu():
    adapter = _FakeAdapter({"Account 01": _FakePage({
        "dn": None, "uid": None, "balance": None, "hooked": True, "on_login": False,
    })})
    hub = _FakeHub({"Account 01": {"dn": "nicktestxxabai1", "balance": 106_481,
                                   "uid": "eXBrqK5a"}})
    live = await check_one_profile(adapter, hub, {"name": "Account 01"})
    assert live["ten_in_game"] == "nicktestxxabai1"
    assert live["so_du"] == 106_481
    assert live["nguon"] == "hub"


@pytest.mark.anyio
async def test_profile_chua_mo_thi_bao_dung_su_that():
    """Không bịa dữ liệu cho profile đóng — đây là lỗi của endpoint cũ."""
    adapter = _FakeAdapter({})
    live = await check_one_profile(adapter, None, {"name": "Account05"})
    assert live["mo"] is False
    assert live["ten_in_game"] is None
    assert live["so_du"] is None


@pytest.mark.anyio
async def test_check_live_loc_dung_profile_duoc_chon(tmp_config, monkeypatch):
    from models import config_model as cfg
    import controllers.auto_flow_controller.check_live as cl

    state = {"accounts": [
        {"id": "a1", "name": "Account 01", "character_name": None},
        {"id": "a2", "name": "Account 02", "character_name": None},
    ]}
    saved = {}
    monkeypatch.setattr(cl, "load_accounts", lambda: state["accounts"])
    monkeypatch.setattr(cl, "save_accounts", lambda a: saved.update({"v": a}))

    adapter = _FakeAdapter({
        "Account 01": _FakePage({"dn": "ten01", "uid": None, "balance": 10,
                                 "hooked": True, "on_login": False}),
        "Account 02": _FakePage({"dn": "ten02", "uid": None, "balance": 20,
                                 "hooked": True, "on_login": False}),
    })

    r = await check_live(adapter, None, ["Account 01"])
    assert r["so_luong"] == 1, "chỉ kiểm profile được chọn"
    assert r["ket_qua"][0]["profile"] == "Account 01"
    assert state["accounts"][0]["character_name"] == "ten01"
    assert state["accounts"][1]["character_name"] is None, "không đụng profile khác"
    assert saved.get("v") is not None, "phải lưu lại database khi có thay đổi"


@pytest.mark.anyio
async def test_khong_luu_database_khi_khong_co_gi_doi(tmp_config, monkeypatch):
    import controllers.auto_flow_controller.check_live as cl

    accs = [{"id": "a1", "name": "Account 01", "character_name": "ten01",
             "balance": 10}]
    saved = {"goi": 0}
    monkeypatch.setattr(cl, "load_accounts", lambda: accs)
    monkeypatch.setattr(cl, "save_accounts",
                        lambda a: saved.__setitem__("goi", saved["goi"] + 1))

    adapter = _FakeAdapter({"Account 01": _FakePage({
        "dn": "ten01", "uid": None, "balance": 10, "hooked": True, "on_login": False,
    })})
    await check_live(adapter, None, None)
    assert saved["goi"] == 0, "không có thay đổi thì không ghi đĩa"


def test_endpoint_khong_con_bia_du_lieu():
    """Bản cũ đoán account theo chữ "2" trong tên và trả số dư hardcode."""
    from pathlib import Path

    src = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
           / "routes_basic.py").read_text(encoding="utf-8")
    assert "gold = 77607 if is_acc2 else 57377" not in src
    assert 'is_acc2 = any(x in name.lower() for x in ["2", "sub", "phu", "xabai2"])' not in src
    assert '"/api/autoplay/check-live"' in src


def test_endpoint_gold_cung_khong_con_bia():
    """`/api/autoplay/gold` có CÙNG lỗi bịa dữ liệu — test đầu tiên đã bắt được nó."""
    from pathlib import Path

    src = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
           / "routes_basic.py").read_text(encoding="utf-8")
    khoi = src.split('@router.get("/api/autoplay/gold")', 1)[1].split("@router", 1)[0]
    # Kiểm DÒNG CODE, không kiểm con số — docstring có nhắc lại chúng để giải
    # thích lỗi cũ, và đó là chủ ý.
    assert "gold = 77607 if is_acc2 else 57377" not in khoi
    assert "is_acc2 = any(" not in khoi
    assert "check_one_profile" in khoi

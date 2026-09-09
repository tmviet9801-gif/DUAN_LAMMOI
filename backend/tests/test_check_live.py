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
        "ten_in_game": "nicktestxxabai3", "uid": "aB3cD4", "u": "1_643156999",
        "so_du": 12345,
    })
    assert acc["character_name"] == "nicktestxxabai3"
    assert acc["uid"] == "aB3cD4"
    assert acc["game_username"] == "1_643156999", "game_username là trường `u`, không phải uid"
    assert acc["balance"] == 12345
    assert any("character_name" in c for c in changed)


def test_game_username_khong_bi_nhoi_uid():
    """`context.py` dùng `game_username` làm ứng viên đối chiếu profile.

    Bản trước gán thẳng `game_username = uid`, bơm một định danh khác không
    gian vào tập đối chiếu. Quy ước sẵn có là lấy trường `u` của gói WS.
    """
    acc = {"name": "Account 01"}
    apply_to_account(acc, {"uid": "eXBrqK5a", "u": "1_643156061"})
    assert acc["uid"] == "eXBrqK5a"
    assert acc["game_username"] == "1_643156061"


def test_thieu_truong_u_thi_lui_ve_uid():
    """Khung không có `u` thì vẫn phải điền được — không để trống."""
    acc = {"name": "Account 01"}
    apply_to_account(acc, {"uid": "eXBrqK5a"})
    assert acc["game_username"] == "eXBrqK5a"


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


class _FakeTokenStore:
    """Kho token giả — giữ test kín, không chạm file thật hay mạng."""

    def __init__(self, token=None, khoa="Account 01"):
        self._token, self._khoa = token, khoa

    def find_for_account(self, account):
        return (self._token, self._khoa) if self._token else (None, None)


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
    live = await check_one_profile(adapter, None, {"name": "Account05"},
                                   token_store=_FakeTokenStore(None))
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


# ---------- đọc qua WebSocket bằng token (không mở Chrome) ----------

def _gia_lap_ws(monkeypatch, ket_qua, ghi=None):
    import controllers.auto_flow_controller.check_live as cl

    async def _fake(token, **kw):
        if ghi is not None:
            ghi.append({"token": token, **kw})
        return ket_qua
    monkeypatch.setattr(cl, "doc_qua_ws", _fake)


@pytest.mark.anyio
async def test_dung_ws_khi_profile_dong(monkeypatch):
    """Mục tiêu chính: đọc được số dư/tên mà KHÔNG mở Chrome."""
    ghi = []
    _gia_lap_ws(monkeypatch, {
        "ok": True, "ten_in_game": "nicktestxxabai1", "uid": "1_643156061",
        "so_du": 95_745, "loi": None, "ma_loi": None,
    }, ghi)

    live = await check_one_profile(
        _FakeAdapter({}), None,
        {"name": "Account 01", "proxy": "1.2.3.4:8080", "user_agent": "UA-X"},
        token_store=_FakeTokenStore("1-" + "a" * 32))

    assert live["mo"] is False, "không mở Chrome"
    assert live["ten_in_game"] == "nicktestxxabai1"
    assert live["so_du"] == 95_745
    assert live["uid"] == "1_643156061"
    assert live["nguon"] == "ws"
    assert live["loi"] is None
    # proxy và user-agent của account phải được dùng, không bỏ qua
    assert ghi[0]["proxy"] == "1.2.3.4:8080"
    assert ghi[0]["user_agent"] == "UA-X"


@pytest.mark.anyio
async def test_khong_mo_ws_khi_profile_dang_mo(monkeypatch):
    """Phiên WS thứ hai có thể đá phiên trình duyệt — mặc định không được mở."""
    ghi = []
    _gia_lap_ws(monkeypatch, {"ok": True, "ten_in_game": "x", "so_du": 1}, ghi)

    adapter = _FakeAdapter({"Account 01": _FakePage({"hooked": False})})
    live = await check_one_profile(adapter, None, {"name": "Account 01"},
                                   token_store=_FakeTokenStore("1-" + "a" * 32))
    assert ghi == [], "profile đang mở thì KHÔNG được mở phiên WS thứ hai"
    assert "Extension chưa nạp" in live["loi"]


@pytest.mark.anyio
async def test_ep_ws_thi_dung_ca_khi_dang_mo(monkeypatch):
    ghi = []
    _gia_lap_ws(monkeypatch, {"ok": True, "ten_in_game": "ten_ws", "so_du": 7}, ghi)

    adapter = _FakeAdapter({"Account 01": _FakePage({"hooked": False})})
    live = await check_one_profile(adapter, None, {"name": "Account 01"},
                                   token_store=_FakeTokenStore("1-" + "a" * 32),
                                   ep_ws=True)
    assert len(ghi) == 1
    assert live["ten_in_game"] == "ten_ws"
    assert live["nguon"] == "ws"


@pytest.mark.anyio
async def test_token_het_han_bao_ro_khong_bia(monkeypatch):
    """Server trả mã 404 -> nói thẳng token hết hạn, không đoán dữ liệu."""
    _gia_lap_ws(monkeypatch, {
        "ok": False, "ten_in_game": None, "uid": None, "so_du": None,
        "loi": "Token hết hạn hoặc không hợp lệ — cần mở profile đăng nhập lại.",
        "ma_loi": 404,
    })
    live = await check_one_profile(_FakeAdapter({}), None, {"name": "Account03"},
                                   token_store=_FakeTokenStore("1-" + "b" * 32))
    assert live["ten_in_game"] is None
    assert live["so_du"] is None
    assert live["ma_loi"] == 404
    assert "hết hạn" in live["loi"]


@pytest.mark.anyio
async def test_khong_co_token_thi_bao_can_dang_nhap(monkeypatch):
    ghi = []
    _gia_lap_ws(monkeypatch, {"ok": True, "ten_in_game": "x"}, ghi)
    live = await check_one_profile(_FakeAdapter({}), None, {"name": "Account09"},
                                   token_store=_FakeTokenStore(None))
    assert ghi == [], "không có token thì đừng gọi mạng"
    assert "Chưa có token" in live["loi"]


# ---------- tìm token trong kho khoá lộn xộn ----------

def _kho(tmp_path, data):
    import json
    from game_sim.token_store import TokenStore

    f = tmp_path / "tok.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return TokenStore(f)


def test_tim_token_chiu_duoc_khoa_khong_nhat_quan(tmp_path):
    """Kho thật có cả `Account 01`, `Account01` và tên đăng nhập cho cùng một người."""
    store = _kho(tmp_path, {
        "Account01":      {"token": "1-cu",  "saved_at": "2026-09-03T11:40:00+00:00"},
        "nicktestxabai1": {"token": "1-vua", "saved_at": "2026-09-05T16:43:10+00:00"},
        "Account 01":     {"token": "1-moi", "saved_at": "2026-09-08T21:29:09+00:00"},
    })
    tok, khoa = store.find_for_account(
        {"name": "Account 01", "username": "nicktestxabai1"})
    assert tok == "1-moi", "phải chọn bản ghi mới nhất — token cũ đã hết hạn"
    assert khoa == "Account 01"


def test_tim_token_qua_ten_dang_nhap_khi_ten_profile_khong_khop(tmp_path):
    store = _kho(tmp_path, {
        "nicktestxabai2": {"token": "1-x", "saved_at": "2026-09-05T08:07:01+00:00"},
    })
    tok, _ = store.find_for_account({"name": "Ten Khac",
                                     "username": "nicktestxabai2"})
    assert tok == "1-x"


def test_khong_tim_thay_thi_tra_none(tmp_path):
    store = _kho(tmp_path, {"Account 01": {"token": "1-a", "saved_at": "2026-09-08"}})
    assert store.find_for_account({"name": "Account 99"}) == (None, None)
    assert store.find_for_account(None) == (None, None)


# ---------- an toàn & proxy ----------

def test_khong_bao_gio_lo_token_day_du():
    from core.ws_account import che_token

    tok = "1-" + "0123456789abcdef" * 2
    che = che_token(tok)
    assert tok not in che
    assert che.startswith("1-0123") and che.endswith("cdef")


def test_proxy_cua_account_duoc_chuyen_dung_dang():
    from core.ws_account import proxy_url

    assert proxy_url("1.2.3.4:8080:user:pass") == "http://user:pass@1.2.3.4:8080"
    assert proxy_url("1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert proxy_url("") is None
    assert proxy_url(None) is None


@pytest.mark.anyio
async def test_check_live_khong_duoc_mo_chrome(monkeypatch):
    """Check Live phải ĐỌC trạng thái, không được bật profile lên.

    Bản cũ gọi `adapter._page()` -> `page_pool.get_or_open()` -> mở Chrome.
    Chọn 5 profile để check là 5 cửa sổ bật lên — sai mục đích.
    """
    ghi = []
    _gia_lap_ws(monkeypatch, {"ok": True, "ten_in_game": "ten_ws", "so_du": 5}, ghi)

    class _AdapterCoPeek:
        def __init__(self):
            self.da_goi_page = False

        def peek_page(self, name):
            return None                      # profile đang đóng

        async def _page(self, name):
            self.da_goi_page = True          # nếu bị gọi là đã mở Chrome
            raise AssertionError("_page() sẽ mở Chrome — không được gọi")

    ad = _AdapterCoPeek()
    live = await check_one_profile(ad, None, {"name": "Account 01"},
                                   token_store=_FakeTokenStore("1-" + "a" * 32))
    assert ad.da_goi_page is False
    assert live["mo"] is False
    assert live["nguon"] == "ws"
    assert live["so_du"] == 5


def test_page_pool_co_duong_tra_khong_mo():
    """`peek` phải tồn tại và không đụng tới `open_sessions`."""
    import inspect

    from services.page_pool import PagePool

    assert hasattr(PagePool, "peek")
    assert not inspect.iscoroutinefunction(PagePool.peek), "peek là tra nhanh, không async"
    assert "open_sessions" not in inspect.getsource(PagePool.peek)

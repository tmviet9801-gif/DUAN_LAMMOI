"""Xé lẻ quy trình (Tìm bàn / Vào bàn) + cổng kết nối extension.

Người dùng chốt 11/09/2026, lấy theo cách làm của công cụ Sunwin
(`control/control.py`): mỗi kết nối là một hàng ngang có nút riêng, ai giữ được
bàn thì bàn đó thành BÀN CHUNG và máy khác bấm vào thẳng bàn ấy. Ở HIT trước
đó phải tích sẵn account chính + phụ rồi chạy đồng thời, không chen ngang được.

Và: bấm Dừng là "thao tác như người dùng" — đóng WebSocket giữa extension và
app, để từ đó không lệnh nào của tool chạm tới Chrome. WebSocket của GAME thì
TUYỆT ĐỐI không đụng: đóng nó là văng khỏi bàn, mất cược.
"""
import ast
import sys
from pathlib import Path

import pytest

BE = Path(__file__).parents[1]
if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))

from controllers.auto_flow_controller import kich_hoat as KH  # noqa: E402

AF = BE / "controllers" / "auto_flow_controller"
EXT = BE / "extension"


def _code_py(p: Path) -> str:
    src = p.read_text(encoding="utf-8")
    cay = ast.parse(src)
    bo = set()
    for node in ast.walk(cay):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and ast.get_docstring(node, clean=False) is not None:
                s0 = node.body[0]
                bo.update(range(s0.lineno, (s0.end_lineno or s0.lineno) + 1))
    return "\n".join(d for i, d in enumerate(src.splitlines(), 1)
                     if i not in bo and not d.strip().startswith("#"))


def _code_js(p: Path) -> str:
    dong = []
    for d in p.read_text(encoding="utf-8").splitlines():
        s = d.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        dong.append(d)
    return "\n".join(dong)


# ===================== 1. Danh sách đồng đội KHÔNG được rỗng =====================

def test_giu_ban_khong_xoa_trang_danh_sach_dong_doi():
    """Lỗi thật suýt tạo ra hôm nay: `js_giu_ban` bản trước XOÁ TRẮNG hai danh
    sách đồng đội. Từ khi luật đổi sang "chỉ xả với đồng đội", danh sách rỗng
    nghĩa là `isPartner` trả false cho mọi người -> extension coi cả bàn là
    khách lạ và KHÔNG BAO GIỜ đánh."""
    js = KH.js_giu_ban(True, 100, 2)
    assert "window.__AUTOTOOL_PARTNER_PROFILES = [];" not in js
    assert "window.__autotool_partners = [];" not in js

    js2 = KH.js_giu_ban(True, 100, 2, dong_doi=["nicktestxxabai2"])
    assert 'window.__AUTOTOOL_PARTNER_PROFILES = ["nicktestxxabai2"];' in js2
    assert 'window.__autotool_partners = ["nicktestxxabai2"];' in js2


def test_tu_danh_cung_bom_danh_sach_dong_doi():
    js = KH.js_tu_danh(True, ["abc"])
    assert '"abc"' in js
    assert "window.__AUTOTOOL_GIU_BAN = true;" in js
    td = _code_py(AF / "tu_danh.py")
    assert "js_tu_danh(auto_xa, _ten_dong_doi(ten))" in td, \
        "bật Tự đánh mà không bơm đồng đội thì tool sẽ im vì không nhận ra ai"


def test_ten_dong_doi_lay_theo_character_name():
    """Khoá đối chiếu là tên nhân vật in-game, KHÔNG phải username: hai tên chỉ
    khác một ký tự (`nicktestxabai1` vs `nicktestxxabai1`)."""
    code = _code_py(AF / "ban_chung.py")
    assert 'a.get("character_name")' in code
    assert 'a.get("username")' not in code


# ===================== 2. Cổng kết nối extension =====================

def test_background_co_cong_cho_phep_ket_noi():
    src = _code_js(EXT / "background.js")
    assert "let hubAllowed = true;" in src
    assert "if (!hubAllowed) return;" in src, "connectToHub phải bị chặn khi đã ngắt"
    i = src.index("function scheduleReconnect()")
    assert "if (!hubAllowed) return;" in src[i:i + 200], "ngắt rồi mà vẫn tự nối lại là vô nghĩa"
    assert 'hub_allowed' in src, "phải nhớ trong chrome.storage, không mất khi service worker ngủ"
    for lenh in ('message.type === "HUB_DISCONNECT"', 'message.type === "HUB_CONNECT"'):
        assert lenh in src, lenh


def test_ngat_ket_noi_khong_dung_toi_websocket_cua_game():
    """Đóng socket game là người dùng văng khỏi bàn — chỉ đóng socket với app."""
    src = _code_js(EXT / "background.js")
    i = src.index('message.type === "HUB_DISCONNECT"')
    khoi = src[i:i + 700]
    assert "hubSocket.close()" in khoi
    for cam in ("__ws_get_simms", "Simms", "cmd\":203"):
        assert cam not in khoi, f"nhánh ngắt không được đụng tới `{cam}`"


def test_content_js_lam_cau_noi_cho_lenh_ket_noi():
    """Ngắt rồi thì không còn WS để app gọi — Playwright bơm postMessage là
    đường DUY NHẤT nối lại, nên content script phải nghe được."""
    src = _code_js(EXT / "content.js")
    assert 'ev.data.type === "AUTOTOOL_HUB_DISCONNECT"' in src
    assert 'ev.data.type === "AUTOTOOL_HUB_CONNECT"' in src
    assert '{ type: "HUB_DISCONNECT" }' in src
    assert 'type: "HUB_CONNECT"' in src


def test_backend_bom_lenh_qua_playwright():
    code = _code_py(AF / "ket_noi.py")
    assert "AUTOTOOL_HUB_CONNECT" in code and "AUTOTOOL_HUB_DISCONNECT" in code
    assert "window.postMessage" in code
    assert "json.dumps" in code, "chèn tên profile thô vào JS là lỗi trích dẫn chờ sẵn"


def test_dung_thi_ngat_luon_ket_noi():
    code = _code_py(AF / "routes_basic.py")
    i = code.index("async def _dung_auto")
    khoi = code[i:i + 6000]
    assert "await ngat_extension(request, _t)" in khoi
    assert "da_ngat_extension" in khoi


# ===================== 3. Luồng xé lẻ =====================

def test_ban_chung_dung_lai_ham_join_chung():
    """Chép lại hàm join là sớm muộn hai bản lệch nhau."""
    bc = _code_py(AF / "ban_chung.py")
    mt = _code_py(AF / "matching.py")
    assert "from .join_js import" in bc
    assert "leave_then_join_fn = JS_LEAVE_THEN_JOIN" in mt, \
        "matching.py phải dùng chung nguồn, không giữ bản chép riêng"
    # `server_join_fn` (join thẳng, không rời trước) vẫn nằm ở matching.py và là
    # hàm KHÁC — chỉ chốt phần rời-rồi-join không bị chép hai bản.
    assert "'leave_ack'" not in mt, "còn sót bản chép leave_then_join trong matching.py"
    assert "'leave_ack'" in _code_py(AF / "join_js.py")


def test_tim_ban_giu_ban_khi_gap_ban_trong():
    code = _code_py(AF / "ban_chung.py")
    assert "js_kich_hoat(" in code, "phải mở cổng trước khi dò"
    assert "_ghi_ban(request, ten, rid_that, bet, mu)" in code
    i = code.index("async def _do_va_giu")
    khoi = code[i:i + 4500]
    assert "js_giu_ban(auto_xa, bet, mu," in khoi, "ngồi được bàn trống thì phải GIỮ"


def test_ban_trong_xac_minh_theo_TEN_NHAN_VAT_khong_dem_dau_nguoi():
    """Bàn 2 người có thể là mình + đồng đội (đúng) hoặc mình + khách (phải
    rời). Đếm đầu người là không phân biệt được."""
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def _do_va_giu")
    khoi = code[i:i + 4500]
    assert 'tt.get("so_khach")' in khoi, "phải tách khách bằng isPartner"
    assert "roi_khi_co_khach=True" in khoi, "giữ bàn mà khách vào thì phải rời"
    js = (AF / "join_js.py").read_text(encoding="utf-8")
    for truong in ("window.__is_partner", "so_khach", "ten_khach", "so_dong_doi"):
        assert truong in js, truong


def test_vao_ban_theo_dung_ban_chung():
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def vao_ban")
    khoi = code[i:i + 5000]
    assert "_chon_ban_de_vao(request, ten, chu_muon)" in khoi
    assert "status_code=409" in khoi, "không bàn nào ghép được thì phải báo rõ"
    # Vào xong bật GIỮ BÀN cho nick vừa vào — qua `_mo_cong_bat_tay`, hàm duy
    # nhất được gọi `js_giu_ban(..., cho_bat_tay=True)`.
    assert "_mo_cong_bat_tay(trang, ten, bet, mu, auto_xa)" in khoi
    j = code.index("async def _mo_cong_bat_tay")
    assert "js_giu_ban(auto_xa, bet, mu" in code[j:j + 1600]


def test_vao_ban_kiem_TRUOC_va_xac_minh_SAU_bang_ten_nhan_vat():
    """Lỗi thật 11/09/2026: khách chen vào bàn đang giữ, nick thứ hai bấm Vào
    bàn thì bàn đã đầy nên không vào được. Phải hỏi trang của nick giữ bàn
    TRƯỚC khi join, và sau khi join phải thấy đúng TÊN NHÂN VẬT của nick đó."""
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def _chon_ban_de_vao")
    truoc = code[i:i + 4500]
    assert "_trang_dang_mo(request, chu)" in truoc, "phải hỏi trang của nick giữ bàn"
    assert 'tt.get("so_khach")' in truoc, "kiểm khách TRƯỚC khi join"
    assert 'ban.get("mu")' in truoc, "bàn đã đủ người thì không ghép nữa"
    j = code.index("async def vao_ban")
    sau = code[j:j + 5000]
    assert "dung_chu" in sau and "chu_cn" in sau, "xác minh theo character_name"
    assert "_character_name(" in code


def test_canh_ban_do_lai_khi_khach_chen_vao():
    code = _code_py(AF / "ban_chung.py")
    assert "async def _canh_giu_ban" in code
    i = code.index("async def _canh_giu_ban")
    khoi = code[i:i + 4500]
    assert 'tt.get("so_dong_doi")' in khoi, "đồng đội vào rồi thì thôi canh"
    assert "_do_va_giu(" in khoi, "khách vào thì phải dò bàn khác"
    assert "gom_ban_stop_epoch" in khoi, "bấm Dừng là phải thôi canh"
    assert "HAN_CANH_BAN" in khoi, "không để task sống mãi"


def test_extension_giu_ban_roi_khi_khach_vao():
    src = _code_js(EXT / "content_main.js")
    assert "G.__AUTOTOOL_ROI_KHI_CO_KHACH" in src
    # cmd 200 (khách vừa bước vào) và cmd 202 (khung tả lại cả bàn) — cả hai
    # đường phát hiện khách đều phải rời.
    assert src.count("RỜI để dò bàn khác") >= 2, "thiếu một đường phát hiện khách"
    i = src.index("RỜI để dò bàn khác")
    khoi = src[max(0, i - 700):i + 700]
    assert "__autotool_exec_leave()" in khoi, "khách vào bàn đang giữ thì phải rời"
    assert "some(isPartner)" in khoi, "đồng đội đã ngồi rồi thì không rời"


def test_ban_chung_co_han_su_dung():
    """Người giữ bàn có thể đã rời từ đời nào — bàn chung cũ phải hết hạn."""
    code = _code_py(AF / "ban_chung.py")
    assert "HAN_BAN_CHUNG" in code
    i = code.index("def _ds_ban")
    assert "> HAN_BAN_CHUNG" in code[i:i + 700], "đọc bảng bàn là phải dọn bàn quá hạn"


# ===================== 4. Đo lượt đi trước =====================

def test_extension_bao_ai_duoc_di_truoc():
    """Bản bắt WS hiện có chỉ ghép được 5 cặp ván liên tiếp cùng bàn (60/40),
    quá ít để kết luận luật. Gắn đo để lấy số thật."""
    src = _code_js(EXT / "content_main.js")
    assert 'type: "AUTOTOOL_FIRST_TURN"' in src
    i = src.index('type: "AUTOTOOL_FIRST_TURN"')
    khoi = src[i:i + 500]
    assert "di_truoc" in khoi and "thang_van_truoc" in khoi
    assert "G.__thang_van_truoc" in src, "phải nhớ người thắng ván trước để đối chiếu"

    ct = _code_js(EXT / "content.js")
    assert 'type: "FIRST_TURN"' in ct
    bg = _code_js(EXT / "background.js")
    assert 'message.type === "FIRST_TURN"' in bg
    hub = _code_py(BE / "services" / "extension_hub.py")
    assert '"FIRST_TURN"' in hub
    assert "ĐI TRƯỚC" in (BE / "services" / "extension_hub.py").read_text(encoding="utf-8")


# ===================== 5. Endpoint =====================

class _FakeSession:
    def __init__(self, name, sid, page):
        self.session_id = sid
        self.account = {"name": name, "id": f"id-{sid}"}
        self.page = page
        self.room_id = 5
        self.log = ""
        self.state = "ready"
        self.browser_ctx = None


class _FakePage:
    def __init__(self):
        self.js = []

    async def evaluate(self, expression, *a, **k):
        self.js.append(expression)
        return None


@pytest.fixture()
def phien(client):
    trang = _FakePage()
    man = client.app.state.manager
    assert man is not None
    man.sessions = {"s1": _FakeSession("Account 01", "s1", trang)}
    client.app.state.ban_dang_giu = {}
    client.app.state.canh_ban_tasks = {}
    return trang


def test_endpoint_ngat_va_noi(client, phien):
    r = client.post("/api/extension/ngat", json={})
    assert r.status_code == 200 and r.json()["profiles"] == ["Account 01"]
    assert any("AUTOTOOL_HUB_DISCONNECT" in j for j in phien.js)

    phien.js.clear()
    r = client.post("/api/extension/noi", json={"profile_name": "Account 01"})
    assert r.status_code == 200
    assert any("AUTOTOOL_HUB_CONNECT" in j for j in phien.js)


def test_endpoint_trang_thai_ket_noi(client, phien):
    r = client.get("/api/extension/trang-thai")
    assert r.status_code == 200
    d = r.json()
    assert d["tong"] == 1 and d["profiles"][0]["profile"] == "Account 01"


def test_vao_ban_khong_co_ban_chung_thi_409(client, phien):
    r = client.post("/api/autoplay/vao-ban", json={"profile_name": "Account 01"})
    assert r.status_code == 409


def test_tim_ban_chan_tham_so_vo_nghia(client, phien):
    r = client.post("/api/autoplay/tim-ban", json={"profile_name": "Account 01", "bet": 123})
    assert r.status_code == 400 and "không có trong game" in r.json()["detail"]


def test_tim_ban_TU_MO_chrome_khong_bat_nguoi_dung_mo_tay():
    """Người dùng báo lỗi thật 11/09/2026: bấm Tìm bàn khi Chrome chưa mở thì
    tool từ chối. Phải dùng lại nguyên luồng của gom bàn: tự mở Chrome, nạp
    extension, dẹp popup rồi điều hướng vào sảnh Đếm Lá."""
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def _chuan_bi")
    khoi = code[i:i + 2500]
    assert "adapter._page(ten)" in khoi, "phải MỞ Chrome, không chỉ peek"
    assert "load_extension_scripts()" in khoi, "thiếu script thì hàm join trả no_socket"
    assert "_ensure_in_tldl_lobby_util(" in khoi, "phải dẹp popup + vào sảnh Đếm Lá"
    i2 = code.index("async def _chuan_bi")
    assert "chưa mở Chrome" not in code[i2:i2 + 2500]

    assert "Không mở được Chrome" in code, "mở không được thì phải báo rõ, không treo"


def test_xem_va_xoa_ban_chung(client, phien):
    import time
    client.app.state.ban_dang_giu = {
        "Account 01": {"rid": 2, "bet": 100, "mu": 2, "chu_cn": "nick1", "luc": time.time()},
    }
    r = client.get("/api/autoplay/ban-chung").json()
    assert r["co"] is True and r["so_ban"] == 1
    assert r["ban"][0]["rid"] == 2 and r["ban"][0]["chu"] == "Account 01"

    assert client.post("/api/autoplay/ban-chung/xoa", json={}).status_code == 200
    assert client.get("/api/autoplay/ban-chung").json()["co"] is False


def test_nhieu_nick_giu_ban_song_song(client, phien):
    """Người dùng chốt 11/09/2026: 2-3 nick cùng bấm TÌM BÀN, mỗi nick giữ một
    bàn riêng; nick khác bấm VÀO BÀN thì ghép vào MỘT trong số đó."""
    import time
    now = time.time()
    client.app.state.ban_dang_giu = {
        "Account 01": {"rid": 2, "bet": 100, "mu": 2, "chu_cn": "nick1", "luc": now - 5},
        "Account 02": {"rid": 4, "bet": 500, "mu": 2, "chu_cn": "nick2", "luc": now},
    }
    r = client.get("/api/autoplay/ban-chung").json()
    assert r["so_ban"] == 2
    # Xếp theo thứ tự giữ: bàn giữ lâu nhất đứng trước, đó cũng là bàn được ghép trước.
    assert [b["chu"] for b in r["ban"]] == ["Account 01", "Account 02"]

    # Xoá đích danh một bàn, bàn còn lại phải nguyên.
    assert client.post("/api/autoplay/ban-chung/xoa",
                       json={"profile_name": "Account 01"}).status_code == 200
    r2 = client.get("/api/autoplay/ban-chung").json()
    assert r2["so_ban"] == 1 and r2["ban"][0]["chu"] == "Account 02"


def test_vao_ban_bao_ro_khi_moi_ban_deu_ket(client, phien):
    """Chrome của nick giữ bàn đã đóng -> phải nói rõ vì sao, không im lặng."""
    import time
    client.app.state.ban_dang_giu = {
        "Account 09": {"rid": 2, "bet": 100, "mu": 2, "chu_cn": "nick9", "luc": time.time()},
    }
    r = client.post("/api/autoplay/vao-ban", json={"profile_name": "Account 01"})
    assert r.status_code == 409
    assert "Chrome đã đóng" in r.json()["detail"]


def test_vao_ban_tu_choi_chinh_nick_dang_giu(client, phien):
    import time
    client.app.state.ban_dang_giu = {
        "Account 01": {"rid": 2, "bet": 100, "mu": 2, "chu_cn": "nick1", "luc": time.time()},
    }
    r = client.post("/api/autoplay/vao-ban", json={"profile_name": "Account 01"})
    assert r.status_code == 409 and "đang giữ bàn" in r.json()["detail"]


# ===================== 6. Giao diện =====================

def test_giao_dien_co_nut_moi():
    html = (BE.parent / "app" / "renderer" / "index.html").read_text(encoding="utf-8")
    for id_nut in ('id="btnExtNoi"', 'id="btnExtNgat"', 'id="gcBanChung"'):
        assert id_nut in html, id_nut
    assert ">Tìm bàn</th>" in html and ">Vào bàn</th>" in html
    assert ">Site</th>" not in html, "cột Site đã bỏ (chỉ làm trên HIT)"

    js = (BE.parent / "app" / "renderer" / "js" / "autoplay.js").read_text(encoding="utf-8")
    for duong in ("/api/autoplay/tim-ban", "/api/autoplay/vao-ban",
                  "/api/extension/noi", "/api/extension/ngat"):
        assert duong in js, duong

    render = (BE.parent / "app" / "renderer" / "js" / "render.js").read_text(encoding="utf-8")
    assert "btn-row-join" in render and "App.vaoBan" in render
    assert "App.timBan" in render


# ===================== 7. Mục tiêu cuối: bàn phải để người ngoài vào được =====================

def test_thoi_co_roi_khi_co_khach_sau_khi_dong_doi_da_vao():
    """Mục tiêu cuối của cả dự án (người dùng nhắc lại 11/09/2026): bàn phải là
    BÀN CÔNG CỘNG để sau khi xả xong, một nick rời đi thì NGƯỜI CHƠI NGOÀI vào
    được. Đó cũng là lý do KHÔNG dùng bàn đặt mật khẩu.

    Cờ "khách vào là rời" chỉ đúng trong lúc ĐANG CHỜ đồng đội. Để bật tiếp sau
    đó thì hết ván, nick ở lại sẽ bỏ chạy đúng lúc người chơi thật ngồi xuống.
    """
    code = _code_py(AF / "ban_chung.py")
    assert "async def _mo_cong_bat_tay" in code
    i = code.index("async def _mo_cong_bat_tay")
    than = code[i:i + 1600]
    assert "roi_khi_co_khach=False" in than

    # Tắt cờ ở ĐÚNG MỘT chỗ: endpoint VÀO BÀN, cho cả hai bên. Vòng canh KHÔNG
    # được tự tắt — xem test_canh_ban_khong_tu_mo_cong_khi_gap_dong_doi.
    k = code.index("async def vao_ban")
    khoi_vao = code[k:k + 6000]
    assert "_mo_cong_bat_tay(trang_chu, chu" in khoi_vao, "chủ bàn chưa được tắt cờ"
    assert "_mo_cong_bat_tay(trang, ten" in khoi_vao, "nick vừa vào chưa được tắt cờ"


def test_chi_bat_co_roi_khi_dang_cho_dong_doi():
    """Bật cờ đúng một chỗ: lúc vừa giành được bàn trống và đang chờ đồng đội."""
    code = _code_py(AF / "ban_chung.py")
    assert code.count("roi_khi_co_khach=True") == 1, \
        "chỉ được bật ở lúc giữ bàn chờ đồng đội"
    i = code.index("roi_khi_co_khach=True")
    j = code.index("async def _do_va_giu")
    k = code.index("async def _mo_cong_bat_tay")
    assert j < i < k, "cờ phải được bật trong _do_va_giu"


# ============ 8. DÒ BÀN thì gặp đồng đội cũng không được vào ván ============
#
# Lỗi thật 11/09/2026 (log 05:11): Account 01 giữ bàn trống #2; Account 02 bấm
# TÌM BÀN rồi dò trúng đúng bàn ấy. Vòng dò bên Python từ chối ("bàn đã có
# người ngồi sẵn") nhưng extension thấy đồng đội là bắt tay và VÀO VÁN TIỀN
# THẬT — người dùng chưa hề bấm VÀO BÀN. Mỗi mức cược chỉ có đúng một rid công
# cộng, nên đây không phải trùng hợp hiếm: hai nick cùng dò kiểu gì cũng gặp
# nhau. Cổng `__AUTOTOOL_CHO_BAT_TAY` khoá suốt lúc dò, chỉ VÀO BÀN mới mở.


def test_js_giu_ban_co_cong_cho_bat_tay():
    js_khoa = KH.js_giu_ban(True, 100, 2, cho_bat_tay=False)
    assert "window.__AUTOTOOL_CHO_BAT_TAY = false;" in js_khoa
    js_mo = KH.js_giu_ban(True, 100, 2)
    assert "window.__AUTOTOOL_CHO_BAT_TAY = true;" in js_mo, "mặc định phải MỞ"


def test_extension_dang_do_ban_thi_khong_bat_tay():
    """Chặn ở CẢ HAI nút thắt: hàm bắt tay, và hai lệnh Sẵn sàng/Bắt đầu."""
    src = _code_js(EXT / "content_main.js")
    i = src.index("function triggerVerifiedMatchReadyAndStart(")
    dau = src[i:i + 1400]
    assert "if (G.__AUTOTOOL_CHO_BAT_TAY === false) {" in dau
    assert dau.index("__AUTOTOOL_CHO_BAT_TAY") < dau.index("__room_players"), \
        "phải chặn TRƯỚC khi khoá bàn và chạy nhịp nhắc lại Bắt đầu"

    j = src.index("function khongDuocBatDauVoiNguoiLa()")
    assert "if (G.__AUTOTOOL_CHO_BAT_TAY === false) return true;" in src[j:j + 400], \
        "exec_ready/exec_start chưa gác cờ dò bàn"


def test_do_ban_va_giu_ban_deu_khoa_bat_tay():
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def _chuan_bi")
    assert "window.__AUTOTOOL_CHO_BAT_TAY = false;" in code[i:i + 4000], \
        "lúc chuẩn bị dò phải khoá"
    j = code.index("async def _do_va_giu")
    k = code.index("async def _mo_cong_bat_tay")
    assert "cho_bat_tay=False" in code[j:k], "giành được bàn rồi vẫn phải khoá"


def test_chi_vao_ban_moi_mo_cong_bat_tay():
    """Mở cổng đúng một chỗ, và mở xong phải ĐÁ LẠI bắt tay."""
    code = _code_py(AF / "ban_chung.py")
    assert code.count("cho_bat_tay=True") == 1
    i = code.index("cho_bat_tay=True")
    j = code.index("async def _mo_cong_bat_tay")
    k = code.index("async def _canh_giu_ban")
    assert j < i < k, "chỉ _mo_cong_bat_tay được mở cổng"
    # Khung 200/202 báo đồng đội ngồi xuống đã trôi qua lúc cổng còn khoá;
    # server không gửi lại. Không kích thì cả hai ngồi im tới lúc bị out.
    assert "__autotool_giu_ban_kiem_ngay" in code[j:k], \
        "mở cổng xong phải kích lại bắt tay"


def test_canh_ban_khong_tu_mo_cong_khi_gap_dong_doi():
    """Vòng canh thấy đồng đội KHÔNG có nghĩa là người dùng đã bấm VÀO BÀN."""
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def _canh_giu_ban")
    than = code[i:i + 3000]
    j = than.index('if int(tt.get("so_dong_doi") or 0) > 0:')
    nhanh = than[j:j + 800]
    assert "_mo_cong_bat_tay" not in nhanh, \
        "vòng canh tự mở cổng là vào ván tiền thật ngoài ý muốn"
    assert "continue" in nhanh, "phải ngồi yên giữ bàn, không thôi canh"


def test_dung_va_dong_luot_deu_mo_lai_cong_bat_tay():
    """Dừng / hết lượt: trả trang về đúng trạng thái người dùng chơi tay."""
    code = _code_py(AF / "lobby.py")
    assert code.count("window.__AUTOTOOL_CHO_BAT_TAY = true;") >= 2
    src = _code_js(EXT / "content_main.js")
    i = src.index("function clearRunConfig()")
    assert "G.__AUTOTOOL_CHO_BAT_TAY = true;" in src[i:i + 1200]


# ============ 9. Hai nick cùng TÌM BÀN gặp nhau: ghép lại, không nhảy bàn ============
#
# Bản bắt WS 06:00 ngày 11/09/2026 (sau khi đã chặn tự bắt đầu): hai nick nhảy
# bàn 1,3 giây một lần suốt 60 giây rồi bỏ cuộc. Hai nguyên nhân: (1) server
# HIT xếp người mới vào ghế trống sẵn có, nên nick 1 luôn bị xếp vào bàn nick 2
# đang ngồi một mình (hoặc bàn khách lạ ngồi một mình); (2) hub gom-bàn cũ:
# nick rơi vào bàn có khách phát CANCEL_ROOM_INVITE -> hub ép MỌI profile khác
# LEAVE_ROOM -> nick 2 bị đá khỏi bàn trống nó vừa giữ được.


def test_xe_le_khong_phat_cancel_va_bo_lenh_dieu_phoi_cua_hub():
    src = _code_js(EXT / "content_main.js")
    i = src.index("Phát hiện bàn có người lạ / Full")
    assert "!isSubProfile && !G.__AUTOTOOL_XE_LE" in src[i:i + 1200], \
        "xé lẻ mà phát CANCEL là hub ép nick khác rời bàn đang giữ"
    j = src.index('if (event.data.type !== "AUTOTOOL_EXEC_COMMAND") return;')
    khoi = src[j:j + 1200]
    assert "G.__AUTOTOOL_XE_LE" in khoi
    for lenh in ('"LEAVE_ROOM"', '"JOIN_ROOM"', '"CONFIRM_MATCH"', '"READY"', '"START"'):
        assert lenh in khoi, f"phải bỏ qua lệnh hub {lenh} khi xé lẻ"
    k = src.index("function clearRunConfig()")
    assert "G.__AUTOTOOL_XE_LE = false;" in src[k:k + 1200]


def test_chuan_bi_bat_xe_le_va_dung_tat():
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def _chuan_bi")
    assert "window.__AUTOTOOL_XE_LE = true;" in code[i:i + 4500]
    lobby = _code_py(AF / "lobby.py")
    assert lobby.count("window.__AUTOTOOL_XE_LE = false;") >= 2, \
        "Dừng và hết lượt đều phải tắt chế độ xé lẻ"


def test_hub_van_giu_cancel_cho_luong_gom_ban():
    """Chặn ở extension, không ở hub: luồng GOM BÀN cũ vẫn cần CANCEL -> LEAVE_ROOM."""
    hub = (BE / "services" / "extension_hub.py").read_text(encoding="utf-8")
    assert '"LEAVE_ROOM"' in hub


def test_do_trung_dong_doi_thi_ghep_khong_do_tiep():
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def _do_va_giu")
    j = code.index("async def _mo_cong_bat_tay")
    than = code[i:j]
    k = than.index('if int(tt.get("so_dong_doi") or 0) > 0:')
    nhanh = than[k:k + 1200]
    assert 'return "ghep"' in nhanh, "gặp đồng đội là ghép, không dò tiếp"
    assert "cho_bat_tay=False" in nhanh, "ghép rồi vẫn KHÔNG được tự bắt đầu"
    assert "_ghi_ghep(" in nhanh
    assert than.index('tt.get("so_khach")') < k, "khách phải kiểm TRƯỚC đồng đội"
    assert 'return "giu"' in than and 'return "khong"' in than


def test_ghi_ghep_duoi_ten_chu_ban_that():
    code = _code_py(AF / "ban_chung.py")
    i = code.index("def _ghi_ghep(")
    than = code[i:i + 1200]
    assert "la_chu" in than and "_profile_theo_cn(" in than
    assert "_ghi_ngoi_cung(" in than
    js = (AF / "join_js.py").read_text(encoding="utf-8")
    assert "la_chu:" in js, "JS_DOC_BAN phải đọc cờ C (chủ bàn) của khung 202"


def test_vao_ban_khi_da_ngoi_san_khong_join_lai():
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def _chon_ban_de_vao")
    assert "da_ngoi_san=True" in code[i:i + 3000], "phải nhận ra nick đã ngồi sẵn"
    j = code.index("async def _mo_bat_tay_ban_da_ngoi")
    k = code.index("async def vao_ban")
    than = code[j:k]
    assert "o_yen=True" in than, "đang ngồi trong bàn thì không được điều hướng về sảnh"
    assert "__autotool_leave_then_join" not in than, "không join lại"
    assert "_mo_cong_bat_tay(" in than
    assert "_mo_bat_tay_ban_da_ngoi(request, ten, chu, ban" in code[k:k + 3000]
    m = code.index("async def _chuan_bi")
    assert "if not o_yen and not await _is_in_tldl_lobby_util(trang):" in code[m:m + 4500]


def test_mo_cong_bat_tay_chu_ban_truoc():
    """Mở người vào trước thì Sẵn sàng của họ có thể tới lúc chủ còn khoá."""
    code = _code_py(AF / "ban_chung.py")
    k = code.index("async def vao_ban")
    khoi = code[k:k + 7000]
    assert khoi.index("_mo_cong_bat_tay(trang_chu, chu") < khoi.index("_mo_cong_bat_tay(trang, ten")
    j = code.index("async def _mo_bat_tay_ban_da_ngoi")
    assert 'tt.get("la_chu")' in code[j:j + 3500]


def test_ban_chung_bao_ai_dang_ngoi_cung():
    code = _code_py(AF / "ban_chung.py")
    i = code.index("async def xem_ban_chung")
    assert '"ngoi_cung"' in code[i:i + 1200]
    ui = (BE.parent / "app" / "renderer" / "js" / "autoplay.js").read_text(encoding="utf-8")
    assert "ngoi_cung" in ui and "da_ghep" in ui and "da_ngoi_san" in ui

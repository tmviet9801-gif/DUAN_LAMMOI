"""Nút TỰ ĐÁNH: bật bộ xả cho 1 profile tự vào bàn, KHÔNG chạy gom bàn.

Yêu cầu (10/09/2026): "khi tôi không chạy quy trình này mà vào 1 phòng thủ
công với 1 người chơi khác sẽ thực hiện quy trình xả bài giống như đang làm".

Chế độ này = GIỮ BÀN (đã chạy thật sau ván gom bàn 17:08 ngày 10/09) nhưng do
người dùng tự vào bàn, nên phải lo thêm đúng hai việc:
  1. không có mức cược mục tiêu -> extension không tự out vì "sai mức cược";
  2. mình có thể là KHÁCH trong bàn người khác -> phải Sẵn sàng, không phải
     Bắt đầu. Cờ chủ bàn đọc từ trường `C` của khung 202 (bản bắt WS: ngồi một
     mình C:true; vào bàn đã có chủ thì chủ C:true, mình C:false); cờ Sẵn sàng
     là `r` (khung 202).
  3. server KHÔNG phát 363/aRd cho người khác: ai bấm Sẵn sàng/Bắt đầu thì mọi
     người nhận [5,{uid,dn,cmd:5}] và không có khung 202 mới. Lỗi thật 17:59
     ngày 10/09/2026: chủ bàn bật Tự đánh, khách Sẵn sàng, tool không Bắt đầu.
Không đổi một dòng nào ở luật chọn nước.
"""
import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

BE = Path(__file__).parents[1]
HIT = BE.parent
AF = BE / "controllers" / "auto_flow_controller"
MODULE = BE / "extension" / "vai_tro_ban.js"
EXT = BE / "extension" / "content_main.js"
INDEX = HIT / "app" / "renderer" / "index.html"
AUTOPLAY = HIT / "app" / "renderer" / "js" / "autoplay.js"

import sys  # noqa: E402
if str(BE) not in sys.path:
    sys.path.insert(0, str(BE))
from controllers.auto_flow_controller import kich_hoat as KH  # noqa: E402

NODE = shutil.which("node")
can_node = pytest.mark.skipif(NODE is None, reason="cần node để chạy vai_tro_ban.js")


def run_js(body: str):
    script = f"const M = require({json.dumps(str(MODULE))});\n{body}"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                         timeout=60, encoding="utf-8")
    assert out.returncode == 0, f"node lỗi:\n{out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


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
    return "\n".join(
        d for i, d in enumerate(src.splitlines(), 1)
        if i not in bo and not d.strip().startswith("#"))


def _code_js(p: Path) -> str:
    dong = []
    for d in p.read_text(encoding="utf-8").splitlines():
        s = d.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        dong.append(d)
    return "\n".join(dong)


# ===================== 1. Luật thuần (vai_tro_ban.js) =====================

@can_node
def test_la_chu_ban_doc_co_C_cua_khung_202():
    res = run_js("""
      const chu = {dn:"khanh1112221960", C:true,  r:true,  sit:0};
      const toi = {dn:"nicktestxxabai1", C:false, r:false, sit:1};
      const motMinh = {dn:"nicktestxxabai1", C:true, r:false, sit:0};
      console.log(JSON.stringify([
        M.laChuBan(toi, [chu, toi]),
        M.laChuBan(chu, [chu, toi]),
        M.laChuBan(motMinh, [motMinh]),
        M.laChuBan({dn:"a", sit:1}, [{dn:"b", C:true, sit:0}, {dn:"a", sit:1}]),
        M.laChuBan({dn:"a", sit:0}, [{dn:"a", sit:0}, {dn:"b", sit:1}]),
        M.laChuBan({dn:"a", sit:2}, [{dn:"a", sit:2}, {dn:"b", sit:1}]),
        M.laChuBan({dn:"a"}, [{dn:"a"}, {dn:"b"}]),
        M.laChuBan(undefined, []),
        M.laChuBan({dn:"a", C:"true"}, [{dn:"b", C:"false"}]),
      ]));
    """)
    # vào bàn có chủ | là chủ | một mình | người khác có C | ghế nhỏ nhất |
    # ghế lớn hơn | không có gì để dựa -> chủ (đúng GIỮ BÀN cũ) | rỗng | C dạng chuỗi
    assert res == [False, True, True, False, True, False, True, True, True]


@can_node
def test_da_san_sang_doc_r_khung_202_va_aRd_khung_363():
    res = run_js("""console.log(JSON.stringify([
      M.daSanSang({r:true}), M.daSanSang({r:false}), M.daSanSang({aRd:"true"}),
      M.daSanSang({aRd:true}), M.daSanSang({aRd:1}), M.daSanSang({aRd:"false"}),
      M.daSanSang({}), M.daSanSang(null), M.daSanSang({ss:true}),
      M.daSanSang({ready:true}), M.daSanSang({r:"1"}), M.daSanSang("true"),
    ]))""")
    assert res == [True, False, True, True, True, False, False, False, True, True, False, False]


@can_node
def test_hanh_dong_giu_ban_bang_quyet_dinh():
    res = run_js("""
      const H = M.hanhDongGiuBan;
      console.log(JSON.stringify([
        H({dangVan:true,  coKhach:true,  tuBatTay:true,  laChu:false, khachSS:true,  minhSS:false}),
        H({dangVan:false, coKhach:false, tuBatTay:true,  laChu:true}),
        H({dangVan:false, coKhach:true,  tuBatTay:false, laChu:false, minhSS:false}),
        H({dangVan:false, coKhach:true,  tuBatTay:true,  laChu:false, minhSS:false}),
        H({dangVan:false, coKhach:true,  tuBatTay:true,  laChu:false, minhSS:true}),
        H({dangVan:false, coKhach:true,  tuBatTay:true,  laChu:true,  khachSS:true}),
        H({dangVan:false, coKhach:true,  tuBatTay:true,  laChu:true,  khachSS:false}),
        H(undefined),
      ]));
    """)
    # đang ván | một mình | tắt tự bắt tay | khách chưa SS -> SS | khách đã SS
    # | chủ + khách SS -> bắt đầu | chủ + khách chưa SS | không có gì
    assert res == ["dang_van", "cho", "cho", "san_sang", "cho", "bat_dau", "cho", "cho"]


@can_node
def test_module_van_thuan_sau_khi_them():
    code = _code_js(MODULE)
    for cam in ("document", "localStorage", "Date.now", "cc.", "fetch(", "window."):
        assert cam not in code, f"module không được đụng `{cam}`"
    assert run_js('console.log(JSON.stringify(typeof M.laChuBan))') == "function"


# ===================== 2. Nối vào content_main.js =====================

def test_extension_giu_ban_biet_minh_la_khach():
    src = _code_js(EXT)
    i = src.index("if (G.__AUTOTOOL_GIU_BAN && !isSubProfile) {")
    khoi = src[i:i + 1200]
    assert "quyetDinhGiuBan(me, p.ps || [], guestSS)" in khoi
    assert 'guiSanSangGiuBan("cmd:202")' in khoi, "mình là khách thì phải Sẵn sàng"
    assert "G.__autotool_exec_start()" in khoi, "mình là chủ, khách SS thì vẫn Bắt đầu như cũ"
    # Sẵn sàng của khách đọc qua MỘT chỗ, nhận cả `r` của khung 202
    assert "const guestSS = strangers.some((x) => daSanSangNguoiChoi(x));" in src


def test_extension_quyet_dinh_uy_quyen_module_thuan_va_du_phong_an_toan():
    src = _code_js(EXT)
    i = src.index("function quyetDinhGiuBan(")
    than = src[i:src.index("function guiSanSangGiuBan(", i)]
    for c in ("M.hanhDongGiuBan(t)", "laChuBanHienTai(me, ds)",
              "G.__auto_start_guest_ss", "G.__game_in_progress", "isPartner(x)"):
        assert c in than, c
    i = src.index("function laChuBanHienTai(")
    than = src[i:i + 300]
    assert "M.laChuBan(me, players)" in than
    assert "return true;" in than, "thiếu module thì coi là chủ bàn — đúng GIỮ BÀN đã chạy thật"


def test_extension_khach_san_sang_lai_sau_van():
    src = _code_js(EXT)
    i = src.index("if (p.cmd === 252)")
    khoi = src[i:i + 7000]
    assert "nc.r = false; nc.aRd = false;" in khoi, "hết ván phải xoá cờ SS cũ"
    j = khoi.index("isAutoEngaged() && G.__AUTOTOOL_GIU_BAN && !isSubMatchProfile()")
    sau = khoi[j:j + 700]
    assert '__autotool_giu_ban_kiem_ngay("cmd:252")' in sau
    assert "G.__game_in_progress" in sau, "ván mới đã chạy thì không gửi SS"


def test_kiem_ngay_hanh_dong_theo_quyet_dinh_va_tra_ket_qua():
    """Bấm TỰ ĐÁNH khi đã ngồi sẵn trong bàn người khác: không có khung 202 mới
    nào sắp tới, extension phải tự kiểm bàn đang ngồi và Sẵn sàng ngay."""
    src = _code_js(EXT)
    i = src.index("G.__autotool_giu_ban_kiem_ngay = function (nguon) {")
    than = src[i:i + 900]
    assert "quyetDinhGiuBan(ps.find(isMe), ps, false)" in than
    assert "guiSanSangGiuBan(" in than
    assert "G.__autotool_exec_start()" in than
    assert "return hanhDong;" in than, "phải trả hành động để backend ghi log"
    assert "isSubMatchProfile()" in than, "nick phụ của lượt gom bàn không được đi đường này"


def test_extension_bat_khung_cmd5_phat_lai_khach_san_sang():
    """Server không gửi 363/aRd cho người khác (75.517 khung bắt được, không khung
    nhận nào chứa aRd); khách bấm Sẵn sàng thì mọi người nhận [5,{uid,dn,cmd:5}]
    và không có khung 202 mới. Chủ bàn phải Bắt đầu từ khung này."""
    src = _code_js(EXT)
    i = src.index("if (p.cmd === 5 && (p.uid || p.dn)) {")
    khoi = src[i:i + 1700]
    assert "isMe(nguoi)" in khoi, "cmd 5 phát lại của CHÍNH MÌNH thì bỏ qua"
    assert "x.r = true; x.aRd = true;" in khoi, "phải ghi cờ SS vào danh sách người chơi"
    assert 'G.__autotool_giu_ban_kiem_ngay("cmd:5")' in khoi
    assert ("G.__AUTOTOOL_GIU_BAN && isAutoEngaged() && !isSubMatchProfile() "
            "&& !G.__game_in_progress") in khoi
    # cùng chuỗi handler, trước khối chia bài
    assert i < src.index("if (p.cmd === 250)")


def test_het_van_bao_ket_qua_len_backend():
    """Log backend 17:59-18:03 (10/09/2026) chỉ thấy số dư nhảy -22.580 qua hai
    ván, không một dòng nào nói ván thắng/thua hay tool có đánh không."""
    src = _code_js(EXT)
    i = src.index('type: "AUTOTOOL_GAME_ENDED"')
    khoi = src[i:i + 300]
    assert "cards_left: laConLai" in khoi
    assert "won: p.fP ? isMe(p.fP) : null" in khoi
    j = src.index("if (p.cmd === 252)")
    assert "const laConLai" in src[j:src.index('type: "AUTOTOOL_GAME_ENDED"', j)], \
        "phải đếm lá còn lại TRƯỚC khi xoá __my_cards"
    cj = (BE / "extension" / "content.js").read_text(encoding="utf-8")
    k = cj.index('ev.data.type === "AUTOTOOL_GAME_ENDED"')
    assert 'type: "GAME_ENDED"' in cj[k:k + 900]
    bg = (BE / "extension" / "background.js").read_text(encoding="utf-8")
    assert 'message.type === "GAME_ENDED"' in bg, "background.js không chuyển tiếp thì Hub không nhận"
    hub = _code_py(BE / "services" / "extension_hub.py")
    assert '"GAME_ENDED"' in hub
    assert 'd.get("cards_left")' in hub, "background.js gói message vào `data`, Hub phải đọc từ đó"


def test_gui_san_sang_khong_gui_don():
    src = _code_js(EXT)
    i = src.index("function guiSanSangGiuBan(")
    than = src[i:i + 700]
    assert "__giu_ban_ss_luc" in than
    assert "G.__autotool_exec_ready()" in than


def test_clear_run_config_tat_tu_danh():
    src = _code_js(EXT)
    i = src.index("function clearRunConfig()")
    assert "G.__AUTOTOOL_TU_DANH = false;" in src[i:i + 900]


# ===================== 3. kich_hoat / lobby / matching / stop =====================

def test_js_tu_danh_la_giu_ban_khong_muc_cuoc():
    js = KH.js_tu_danh(True, True)
    for dong in ("window.__AUTOTOOL_GIU_BAN = true;",
                 "window.__AUTOTOOL_TU_DANH = true;",
                 "window.__AUTOTOOL_ENGAGED = true;",
                 "window.__AUTOTOOL_ARMED = true;",
                 "window.__AUTOTOOL_AUTO_HUNT = false;",
                 "window.__AUTOTOOL_AUTO_DISCARD = true;",
                 "window.__auto_start_guest_ss = true;",
                 "window.__target_hunt_bet = 0;",
                 "window.__target_hunt_mu = 0;",
                 'window.__AUTOTOOL_MATCH_ROLE = "anchor";',
                 "window.__autotool_partners = [];",
                 "localStorage.removeItem('AUTOTOOL_STOPPED')",
                 "window.__autotool_giu_ban_kiem_ngay('bat_tu_danh')"):
        assert dong in js, dong
    js2 = KH.js_tu_danh(False, False)
    assert "window.__AUTOTOOL_AUTO_DISCARD = false;" in js2
    assert "window.__auto_start_guest_ss = false;" in js2


def test_giu_ban_sau_gom_ban_va_kich_hoat_khong_phai_tu_danh():
    js = KH.js_giu_ban(True, True, 100, 2)
    assert "window.__AUTOTOOL_TU_DANH = false;" in js
    assert "__autotool_giu_ban_kiem_ngay" not in js, \
        "GIỮ BÀN sau gom bàn giữ nguyên đường đã chạy thật, không kiểm ngay"
    assert "window.__AUTOTOOL_TU_DANH = false;" in KH.js_kich_hoat("anchor", True, [], 100, 2)
    assert "window.__AUTOTOOL_TU_DANH = false;" in KH.js_kich_hoat("sub", True, [], 100, 2)


def test_doc_trang_thai_tu_danh_doc_dung_cong():
    js = KH.JS_DOC_TU_DANH
    for c in ("__AUTOTOOL_TU_DANH", "__AUTOTOOL_GIU_BAN", "__AUTOTOOL_ENGAGED",
              "AUTOTOOL_STOPPED", "__AUTOTOOL_AUTO_DISCARD", "__room_players"):
        assert c in js, c


def test_dung_va_dong_luot_deu_tat_tu_danh():
    code = _code_py(AF / "lobby.py")
    assert code.count("window.__AUTOTOOL_TU_DANH = false;") >= 2


def test_gom_ban_va_dung_go_ten_khoi_danh_sach_tu_danh():
    assert "_tap_tu_danh.difference_update(profiles_input)" in _code_py(AF / "matching.py")
    assert "tap_tu_danh.discard(_t)" in _code_py(AF / "routes_basic.py")


# ===================== 4. Endpoint =====================

class _FakePage:
    """Trang giả: ghi lại JS được eval và mô phỏng cờ trong bộ nhớ trang."""

    def __init__(self):
        self.js = []
        self.tu_danh = False
        self.engaged = False
        self.auto_xa = False

    async def evaluate(self, expression, *args, **kwargs):
        self.js.append(expression)
        e = expression
        if "window.__AUTOTOOL_TU_DANH = true;" in e:
            self.tu_danh = True
        if "window.__AUTOTOOL_TU_DANH = false;" in e:
            self.tu_danh = False
        if "window.__AUTOTOOL_ENGAGED = true;" in e:
            self.engaged = True
        if "window.__AUTOTOOL_ENGAGED = false;" in e:
            self.engaged = False
        if "window.__AUTOTOOL_AUTO_DISCARD = true;" in e:
            self.auto_xa = True
        if "window.__AUTOTOOL_AUTO_DISCARD = false;" in e:
            self.auto_xa = False
        if "tu_danh:" in e:      # JS_DOC_TU_DANH
            return {"tu_danh": self.tu_danh, "engaged": self.engaged,
                    "auto_xa": self.auto_xa, "trong_ban": True, "so_nguoi": 2}
        if "__autotool_giu_ban_kiem_ngay('bat_tu_danh')" in e:   # js_tu_danh
            return "san_sang"
        return None


class _FakeSession:
    def __init__(self, name, sid, page):
        self.session_id = sid
        self.account = {"name": name, "id": f"id-{sid}"}
        self.page = page
        self.room_id = 5
        self.log = ""


@pytest.fixture()
def phien(client):
    """Account 01 đang mở Chrome; Account 02 có session nhưng không có trang."""
    trang = _FakePage()
    man = client.app.state.manager
    assert man is not None
    man.sessions = {"s1": _FakeSession("Account 01", "s1", trang),
                    "s2": _FakeSession("Account 02", "s2", None)}
    client.app.state.gom_ban_profiles = set()
    client.app.state.tu_danh_profiles = set()
    return trang


def _bat(client, **them):
    body = {"profile_name": "Account 01", "auto_xa": True, "auto_start_guest_ss": True}
    body.update(them)
    return client.post("/api/autoplay/tu-danh/bat", json=body)


def test_bat_dat_che_do_giu_ban_khong_muc_cuoc_va_doc_lai(client, phien):
    r = _bat(client)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["profile"] == "Account 01" and d["trong_ban"] is True and d["so_nguoi"] == 2
    assert d["hanh_dong_ngay"] == "san_sang", "phải trả hành động extension vừa làm lúc bật"
    js = "\n".join(phien.js)
    for dong in ("window.__AUTOTOOL_GIU_BAN = true;", "window.__AUTOTOOL_TU_DANH = true;",
                 "window.__AUTOTOOL_ENGAGED = true;", "window.__AUTOTOOL_AUTO_DISCARD = true;",
                 "window.__target_hunt_bet = 0;", "window.__auto_start_guest_ss = true;",
                 "localStorage.removeItem('AUTOTOOL_STOPPED')"):
        assert dong in js, dong
    assert "tu_danh:" in js, "phải ĐỌC LẠI trang sau khi đặt"
    st = client.get("/api/autoplay/tu-danh/status").json()
    assert st["profiles"] == ["Account 01"] and st["da_roi"] == []


def test_ton_trong_tuy_chon_tat_xa_va_tat_tu_bat_tay(client, phien):
    r = _bat(client, auto_xa=False, auto_start_guest_ss=False)
    assert r.status_code == 200, r.text
    js = "\n".join(phien.js)
    assert "window.__AUTOTOOL_AUTO_DISCARD = false;" in js
    assert "window.__auto_start_guest_ss = false;" in js


def test_chua_mo_chrome_thi_400_khong_mo_ho(client, phien):
    r = client.post("/api/autoplay/tu-danh/bat", json={"profile_name": "Account 02"})
    assert r.status_code == 400
    assert "chưa mở Chrome" in r.json()["detail"]
    assert phien.js == []


def test_thieu_ten_thi_400(client, phien):
    assert client.post("/api/autoplay/tu-danh/bat", json={}).status_code == 400
    assert phien.js == []


def test_dang_gom_ban_thi_409_khong_dung_trang(client, phien):
    client.app.state.gom_ban_profiles = {"Account 01"}
    r = _bat(client)
    assert r.status_code == 409
    assert phien.js == []


def test_doc_lai_khong_bat_duoc_thi_500_khong_ghi_danh(client, phien):
    """Extension chưa nạp: đặt cờ xong đọc lại vẫn tắt -> báo lỗi, không ghi danh."""
    async def evaluate(expression, *a, **k):
        phien.js.append(expression)
        if "tu_danh:" in expression:
            return {"tu_danh": False, "engaged": False, "auto_xa": False}
        return None
    phien.evaluate = evaluate
    r = _bat(client)
    assert r.status_code == 500
    assert client.get("/api/autoplay/tu-danh/status").json()["profiles"] == []


def test_tat_dong_cong_khong_roi_ban_khong_dat_co_dung(client, phien):
    assert _bat(client).status_code == 200
    phien.js.clear()
    r = client.post("/api/autoplay/tu-danh/tat", json={"profile_name": "Account 01"})
    assert r.status_code == 200 and r.json()["van_trong_ban"] is True
    js = "\n".join(phien.js)
    assert "window.__AUTOTOOL_ENGAGED = false;" in js
    assert "window.__AUTOTOOL_TU_DANH = false;" in js
    assert "AUTOTOOL_STOPPED', '1'" not in js, "tắt Tự đánh không phải là Dừng"
    assert "STOP_HUNT" not in js and '"cmd":203' not in js, "tắt Tự đánh không được rời bàn"
    assert client.get("/api/autoplay/tu-danh/status").json()["profiles"] == []


def test_status_doc_tu_trang_trang_tai_lai_thi_bao_roi_mot_lan(client, phien):
    assert _bat(client).status_code == 200
    phien.engaged = False      # trang tải lại: extension khởi tạo lại cờ
    phien.tu_danh = False
    st = client.get("/api/autoplay/tu-danh/status").json()
    assert st["profiles"] == [] and st["da_roi"] == ["Account 01"]
    st2 = client.get("/api/autoplay/tu-danh/status").json()
    assert st2["da_roi"] == [], "chỉ báo rớt một lần"


def test_dung_chung_cung_go_khoi_danh_sach(client, phien):
    assert _bat(client).status_code == 200
    r = client.post("/api/autoplay/stop", json={"profile_name": "Account 01"})
    assert r.status_code == 200
    assert "Account 01" not in client.app.state.tu_danh_profiles


# ===================== 5. Giao diện =====================

def test_giao_dien_co_nut_va_goi_dung_endpoint():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="btnGcTuDanh"' in html
    js = AUTOPLAY.read_text(encoding="utf-8")
    for e in ("/api/autoplay/tu-danh/bat", "/api/autoplay/tu-danh/tat",
              "/api/autoplay/tu-danh/status"):
        assert e in js, e
    than = js[js.index("async function batTatTuDanh"):]
    assert "profileDaTichDauTien" in than, "chỉ chạy trên profile tích ĐẦU TIÊN, không tự chọn"
    assert 'if ($("btnGcTuDanh")) $("btnGcTuDanh").onclick = batTatTuDanh;' in js
    assert "da_roi" in js, "giao diện phải báo khi chế độ rớt (trang tải lại)"

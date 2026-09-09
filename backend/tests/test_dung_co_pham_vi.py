"""Bấm Dừng không được đụng tới profile người dùng đang tự chơi.

Người dùng mở 6 Chrome, tích 2 cái để gom bàn, 4 cái còn lại đang tự tay chơi
bài. Bản trước bấm Dừng là cả 4 nick kia bị gửi lệnh rời bàn GIỮA VÁN — mất
tiền cược trên tài khoản thật.
"""
from pathlib import Path

import pytest


class _FakeSession:
    def __init__(self, name, sid):
        self.session_id = sid
        self.account = {"name": name, "id": f"id-{sid}"}
        self.page = None          # None -> bỏ qua _clear_hunt_state
        self.room_id = 5
        self.log = ""


@pytest.fixture()
def sessions(client):
    """Sáu profile đang mở; test tự quyết cái nào thuộc lượt chạy."""
    ss = {f"s{i}": _FakeSession(f"Account {i:02d}", f"s{i}") for i in range(1, 7)}
    man = getattr(client.app.state, "manager", None)
    assert man is not None, "app chưa có manager"
    man.sessions = ss
    client.app.state.gom_ban_profiles = None
    return ss


def _phong(ss):
    return {ten: s.room_id for ten, s in ss.items()}


# ---------- chỉ định tên ----------

def test_dung_theo_ten_chi_cham_dung_profile_do(client, sessions):
    """Nút "Dừng"/"Thoát.P" trên từng dòng ĐÃ gửi `profile_name` từ trước.

    Nhưng endpoint có chữ ký `autoplay_stop(request)` — không hề đọc body — nên
    bấm một dòng là dừng cả nhóm.
    """
    r = client.post("/api/autoplay/stop", json={"profile_name": "Account 03"})
    assert r.status_code == 200
    assert r.json()["profiles"] == ["Account 03"]

    assert sessions["s3"].room_id == -1
    for k in ("s1", "s2", "s4", "s5", "s6"):
        assert sessions[k].room_id == 5, f"{k} bị dừng oan"


def test_dung_theo_danh_sach_ten(client, sessions):
    r = client.post("/api/autoplay/stop",
                    json={"profile_names": ["Account 01", "Account 05"]})
    assert r.status_code == 200
    assert sorted(r.json()["profiles"]) == ["Account 01", "Account 05"]
    assert sessions["s1"].room_id == -1 and sessions["s5"].room_id == -1
    assert sessions["s2"].room_id == 5 and sessions["s6"].room_id == 5


def test_ten_khong_khop_thi_khong_dung_ai(client, sessions):
    """Gõ nhầm tên KHÔNG được biến thành "dừng tất cả"."""
    r = client.post("/api/autoplay/stop", json={"profile_name": "Khong Ton Tai"})
    assert r.status_code == 200
    assert r.json()["profiles"] == []
    assert all(v == 5 for v in _phong(sessions).values())


def test_khop_ten_khong_phan_biet_hoa_thuong(client, sessions):
    r = client.post("/api/autoplay/stop", json={"profile_name": "  account 02 "})
    assert r.status_code == 200
    assert sessions["s2"].room_id == -1


# ---------- không chỉ định tên ----------

def test_khong_chi_dinh_thi_chi_dung_profile_cua_luot_dang_chay(client, sessions):
    """Đây là đường nút Dừng lớn đi qua: nó không gửi body."""
    client.app.state.gom_ban_profiles = {"Account 01", "Account 02"}
    r = client.post("/api/autoplay/stop")
    assert r.status_code == 200
    assert sorted(r.json()["profiles"]) == ["Account 01", "Account 02"]

    assert sessions["s1"].room_id == -1 and sessions["s2"].room_id == -1
    for k in ("s3", "s4", "s5", "s6"):
        assert sessions[k].room_id == 5, f"{k} đang chơi tay mà bị dừng"


def test_khong_co_luot_nao_chay_thi_dung_tat_ca(client, sessions):
    """Không biết lượt nào đang chạy -> giữ hành vi cũ, đừng im lặng bỏ qua."""
    client.app.state.gom_ban_profiles = set()
    r = client.post("/api/autoplay/stop")
    assert r.status_code == 200
    assert len(r.json()["profiles"]) == 6


def test_leave_all_van_thoat_tat_ca(client, sessions):
    """`/leave-all` là endpoint riêng, cố ý không giới hạn phạm vi."""
    client.app.state.gom_ban_profiles = {"Account 01"}
    r = client.post("/api/autoplay/leave-all")
    assert r.status_code == 200
    assert len(r.json()["profiles"]) == 6


# ---------- lượt chạy phải ghi danh profile của nó ----------

def test_luot_chay_ghi_danh_va_go_ten_khi_xong():
    """Dùng SET hợp nhất, không phải danh sách phẳng: nhiều lượt chạy đồng thời
    thì một danh sách sẽ bị lượt sau ghi đè lượt trước."""
    src = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
           / "matching.py").read_text(encoding="utf-8")
    assert "request.app.state.gom_ban_profiles = dang_chay" in src
    assert "dang_chay.update(profiles_input)" in src
    assert "dang_chay.discard(_t)" in src, "không gỡ tên khi lượt chạy kết thúc"


def test_broadcast_khong_cham_moi_extension_khi_pham_vi_hep():
    """Broadcast chạm tới MỌI extension đang online, kể cả profile đang chơi tay."""
    src = (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
           / "routes_basic.py").read_text(encoding="utf-8")
    khoi = src.split("async def _dung_auto", 1)[1][:2500]
    assert "if toan_bo:" in khoi
    assert 'ext_hub.send_command(t, "STOP_HUNT"' in khoi


# ---------- Dừng bấm sớm không được biến mất ----------

def _matching():
    return (Path(__file__).parents[1] / "controllers" / "auto_flow_controller"
            / "matching.py").read_text(encoding="utf-8")


def test_chup_moc_dung_ngay_dau_ham():
    """Phần mở đầu (mở Chrome + inject 3 script/profile) mất 3-30 giây.

    Bấm Dừng trong khoảng đó: endpoint tăng epoch và duyệt active_match_tasks,
    nhưng task này CHƯA đăng ký nên không có gì bị huỷ; ngay sau đó
    MatchContext mới đọc epoch và đọc trúng giá trị MỚI -> _should_stop() trả
    False vĩnh viễn. Người dùng đã bấm Dừng mà mọi nick vẫn đánh hết ván.
    """
    src = _matching()
    i_chup = src.index("stop_epoch_vao = int(getattr(")
    i_ctx = src.index("ctx = MatchContext(")
    i_mo = src.index("page_a = await adapter._page(profile_a)")
    assert i_chup < i_mo, "phải chụp mốc TRƯỚC khi mở Chrome"
    assert i_chup < i_ctx
    assert "ctx.stop_epoch = stop_epoch_vao" in src, "ctx vẫn tự đọc mốc mới"


def test_co_chot_kiem_dung_truoc_khi_mo_chrome():
    src = _matching()
    khoi = src.split("Chốt kiểm Dừng TRƯỚC khi mở Chrome", 1)[1]               .split("page_a = await adapter._page", 1)[0]
    assert "!= stop_epoch_vao" in khoi
    assert '"stopped": True' in khoi

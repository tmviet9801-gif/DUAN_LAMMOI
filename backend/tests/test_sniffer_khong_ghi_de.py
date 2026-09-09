"""Hai script cùng ghi một biến, và cmd 305 là quảng bá của MỌI game.

Đây chính là đường sinh lại triệu chứng "chọn bàn $100 mà vào bàn $500".
"""
from pathlib import Path

import pytest

BE = Path(__file__).parents[1]


def _code(rel):
    """Chỉ dòng CODE — chú thích giải thích lỗi cũ nhắc lại chuỗi bị cấm."""
    return "\n".join(d for d in (BE / rel).read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith(("//", "#")))


def test_cmd_305_khong_duoc_ghi_thong_tin_phong_dang_ngoi():
    """cmd 305 quảng bá bàn của MỌI game: Phom gid=8 cược 2.000, Chinese Poker...

    Ghi nó vào `__last_room_info` làm vòng trích rid nhận rid 142 của bàn Phom
    làm "phòng thật", và cổng kiểm mức cược đọc b=2000 rồi tự out khỏi bàn $100
    hoàn toàn đúng.
    """
    code = _code("game_sim/ws_sniffer.py")
    assert "p.cmd === 308 || p.cmd === 305" not in code
    assert "G.__ws_sniffer_broadcast_room = p.ri" in code, (
        "305 phải vào namespace riêng, không đụng biến dùng chung")


def test_chi_cmd_308_moi_duoc_ghi_last_room_info():
    src = (BE / "game_sim/ws_sniffer.py").read_text(encoding="utf-8")
    khoi = src.split("} else if (p.cmd === 308)", 1)[1].split("} else if (p.cmd === 305)", 1)[0]
    assert "G.__last_room_info = p.ri" in khoi


def test_sniffer_khong_ghi_de_bien_cua_content_main():
    """Giá trị cuối cùng phụ thuộc thứ tự gọi hàm hook, không phải thứ tự gói tin."""
    code = _code("game_sim/ws_sniffer.py")
    assert "if (!G.__ws_main_hooked) {" in code
    khoi = code.split("if (!G.__ws_main_hooked) {", 1)[1][:400]
    assert "G.__room_players" in khoi and "G.__room_state" in khoi


def test_sniffer_khong_con_tu_roi_ban_theo_chuoi_con():
    """Khối cũ dùng `dn.indexOf(k) !== -1` rồi tự gửi [4,"Simms",-1] (rời bàn).

    Cùng lỗi so-chuỗi-con đã bị loại khỏi isPartner — nhưng ở đây hậu quả là
    TỰ RỜI BÀN giữa ván.
    """
    code = _code("game_sim/ws_sniffer.py")
    assert "dn.indexOf(k)" not in code
    assert "__auto_protect" not in code, "khối tự out theo chuỗi con vẫn còn"


# ---------- bản sao thứ ba của cùng lỗi, trong Python ----------

@pytest.mark.anyio
async def test_nhan_dien_khach_la_khop_chinh_xac():
    """Sai theo CẢ HAI chiều nếu dùng chuỗi con: người lạ tên chứa chuỗi con của
    tên quen thì thành NGƯỜI QUEN (tool ngồi lại xả bài cho họ); còn tên quen
    viết khác đi chút thì thành KHÁCH LẠ (tự out oan)."""
    from game_sim.adapters.hitclub import HitClubAdapter

    ad = object.__new__(HitClubAdapter)

    async def _ps(_page):
        return [{"dn": "nicktestxxabai1"}, {"dn": "abai1"},
                {"dn": "nicktestxxabai11"}, {"dn": "nicktestxxabai2"}]
    ad._get_room_players = _ps

    kq = await HitClubAdapter._check_has_stranger(
        ad, object(), ["nicktestxxabai1", "nicktestxxabai2"])
    assert kq["has_stranger"] is True
    assert sorted(kq["strangers"]) == ["abai1", "nicktestxxabai11"]


@pytest.mark.anyio
async def test_toan_dong_doi_thi_khong_bao_khach_la():
    from game_sim.adapters.hitclub import HitClubAdapter

    ad = object.__new__(HitClubAdapter)

    async def _ps(_page):
        return [{"dn": "NickTestXXAbai1"}, {"dn": "nicktestxxabai2"}]
    ad._get_room_players = _ps

    kq = await HitClubAdapter._check_has_stranger(
        ad, object(), ["nicktestxxabai1", "nicktestxxabai2"])
    assert kq["has_stranger"] is False, "khớp phải bỏ qua hoa/thường"


def test_khong_con_so_chuoi_con_trong_hitclub():
    code = _code("game_sim/adapters/hitclub.py")
    assert "k in dn_lower or dn_lower in k" not in code

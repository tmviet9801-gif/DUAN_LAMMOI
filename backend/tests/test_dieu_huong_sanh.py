"""Bấm ĐÚNG ô để vào sảnh Tiến Lên Miền Nam Đếm Lá.

Người dùng gặp: tool bấm nhầm vào sảnh cược Tài/Xỉu thay vì Game Bài. Có BA
đường dẫn tới chuyện đó, và cả ba đều có thật trong code.
"""
from pathlib import Path

BE = Path(__file__).parents[1]
EXT = BE / "extension" / "content_main.js"
LOBBY = BE / "controllers" / "auto_flow_controller" / "lobby.py"


def _code(p, mo="//"):
    return "\n".join(d for d in p.read_text(encoding="utf-8").splitlines()
                     if not d.strip().startswith(mo))


# ---------- đường 1: loại nhầm chính ô cần bấm ----------

def test_dau_hieu_phan_biet_la_DEM_LA_khong_phai_vang_MIEN_NAM():
    """Game này TÊN ĐẦY ĐỦ là "Tiến Lên Miền Nam Đếm Lá".

    Bản trước loại trừ `!text.includes("MIỀN NAM")` — nếu ô trong sảnh ghi đủ
    tên thì điều kiện ấy loại đúng ô cần bấm, hàm trả false, rồi luồng gọi rơi
    xuống click mù và trúng sảnh khác.
    """
    code = _code(EXT)
    assert '!text.includes("MIỀN NAM")' not in code
    khoi = EXT.read_text(encoding="utf-8").split("function clickCocosGameTLDL", 1)[1][:1600]
    assert 'includes("ĐẾM LÁ")' in khoi, "phải lấy ĐẾM LÁ làm dấu hiệu phân biệt"


# ---------- đường 2: click mù theo toạ độ ----------

def test_khong_con_click_mu_trong_luong_dieu_huong():
    """Toạ độ tỉ lệ trượt vài chục pixel là trúng ô game bên cạnh."""
    khoi = _code(EXT).split("async function autoEnterTLDLLobby", 1)[1]
    khoi = khoi.split("G.__autotool_is_inside_table", 1)[0]
    assert "dispatchCanvasClick" not in khoi
    assert "0.427" not in khoi and "0.320" not in khoi


def test_duong_opencv_cung_khong_click_mu():
    """Sửa mỗi phía JS là chưa đủ — đường OpenCV bên Python có đúng hai click
    mù đó, trong khi chú thích ngay trên lại ghi "tuyệt đối không click mù"."""
    code = _code(LOBBY, mo="#")
    assert "int(sw * 0.427)" not in code
    assert "int(sw * 0.320)" not in code
    assert "không click mò" in LOBBY.read_text(encoding="utf-8")


def test_bao_ro_buoc_nao_hong():
    """Không vào được thì phải nói vì sao, để người dùng biết làm gì."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("async function autoEnterTLDLLobby", 1)[1][:4000]
    for b in ('step: "game_bai"', 'step: "tldl"', 'step: "sanh_chon_ban"'):
        assert b in khoi, f"thiếu báo bước hỏng: {b}"


# ---------- đường 3: bấm trúng node vô hình / nút cha sai ----------

def test_tim_node_chi_duyet_node_dang_hien():
    """Cocos tắt UI bằng cách hạ cờ active của node CHA. Kiểm `node.active` của
    chính node sẽ 'thấy' cả ô đang ẩn — bấm vào không có gì xảy ra nhưng hàm
    lại báo thành công, nên luồng đi tiếp trong khi chưa chuyển màn."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function timNodeHien", 1)[1][:900]
    assert "isNodeVisible(node)" in khoi
    for f in ("clickCocosTabGameBai", "clickCocosGameTLDL"):
        than = src.split(f"function {f}", 1)[1][:1600]
        assert "node.active" not in than, f"{f} còn kiểm node.active"


def test_loai_tru_nhan_cua_sanh_game_khac():
    code = _code(EXT)
    assert "NHAN_SANH_KHAC" in code
    assert '"TÀI XỈU"' in code
    assert "function laSanhKhac" in code


def test_khong_di_nguoc_cay_vo_han_de_tim_nut():
    """`clickCocosNode` đi ngược lên tìm cc.Button KHÔNG giới hạn tầng. Nhãn nằm
    trong container mà nút gần nhất phía trên là ô game khác -> bấm nhầm ô đó."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function bamNodeAnToan", 1)[1][:1800]
    assert "len < (sauMax === undefined ? 3 : sauMax)" in khoi, "chưa giới hạn số tầng"
    assert "TỪ CHỐI bấm" in khoi, "chưa xác minh nút còn chứa đúng nhãn"


def test_xac_minh_da_vao_man_game_bai():
    """Bấm xong phải KIỂM, không tin giá trị trả về."""
    code = _code(EXT)
    assert "function dangOManGameBai()" in code
    khoi = EXT.read_text(encoding="utf-8").split("function dangOManGameBai", 1)[1][:400]
    assert 'includes("ĐẾM LÁ")' in khoi and 'includes("PHỎM")' in khoi


# ---------- popup ----------

def test_dep_popup_dung_activeInHierarchy():
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function dismissPopupsAndBanners", 1)[1][:2200]
    assert "isCloseBtn && isNodeVisible(node)" in khoi
    assert "isCloseBtn && node.active" not in khoi


def test_ten_nut_dong_khop_mau_chu_khong_phai_chuoi_con():
    """`name.includes("dong")` khớp cả `khungdong`, `dongho`, `dongxu` — bấm
    bừa vào những node đó là thao tác ngoài ý muốn giữa sảnh."""
    khoi = _code(EXT).split("function dismissPopupsAndBanners", 1)[1][:2200]
    assert 'name.includes("close")' not in khoi
    assert 'name.includes("dong")' not in khoi
    assert "close|dong|x|exit|cancel|huy|skip" in khoi


# ---------- bấm được node KHÔNG có cc.Button ----------

def test_bam_theo_vi_tri_cua_chinh_node():
    """ĐO TRÊN SẢNH THẬT: node `Tab > GameBai` KHÔNG có component nào, và cả
    chuỗi tổ tiên tới gốc cũng không có `cc.Button`.

    `clickCocosNode` đi ngược lên tìm Button, không thấy thì leo tới node GỐC
    rồi `emit(TOUCH_END)` ở đó — và trả về true. Nên đường Cocos cho tab GAME
    BÀI CHƯA BAO GIỜ hoạt động, mà vì báo thành công nên còn chặn luôn đường dự
    phòng: màn ở nguyên tab ALL GAMES, rồi bước sau bấm vào vị trí ô Đếm Lá —
    trên tab ALL GAMES chỗ đó là ô Tài Xỉu.
    """
    code = _code(EXT)
    assert "function viTriNodeTrenCanvas(" in code
    khoi = EXT.read_text(encoding="utf-8").split("function bamNodeAnToan", 1)[1][:2600]
    assert "viTriNodeTrenCanvas(node)" in khoi
    assert "dispatchCanvasClick(vt.nx, vt.ny)" in khoi


def test_vi_tri_lay_tu_node_khong_phai_hang_so():
    """Toạ độ phải suy ra từ hình học của node, để đúng ở mọi kích thước cửa sổ."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function viTriNodeTrenCanvas", 1)[1][:1400]
    assert "getBoundingBoxToWorld" in khoi
    assert "cc.view.getVisibleSize" in khoi
    assert "1 - cy / vs.height" in khoi, "Cocos đếm y từ dưới lên"


def test_node_ngoai_khung_hinh_thi_tu_choi_bam():
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function viTriNodeTrenCanvas", 1)[1][:1400]
    assert "nx >= 0 && nx <= 1 && ny >= 0 && ny <= 1" in khoi


def test_phep_doi_toa_do_khop_so_do_that():
    """Chốt lại phép đổi bằng số ĐO ĐƯỢC trên sảnh thật.

    Node "GAME BÀI": bbox world {x:619.338, y:760.982, w:90.06, h:13.75};
    cc.view.getVisibleSize() = 1560 x 1004.847; canvas = 784 x 505.
    Toạ độ mù cũ là (0.427, 0.250) — sát ngay cạnh, nên nó "đúng" ở đúng kích
    thước này và sai khi bố cục đổi.
    """
    bx, by, bw, bh = 619.338, 760.9824693877551, 90.06, 13.75
    vw, vh = 1560.0, 1004.8469387755102
    nx = (bx + bw / 2) / vw
    ny = 1 - (by + bh / 2) / vh
    assert abs(nx - 0.4259) < 0.001, nx
    assert abs(ny - 0.2359) < 0.001, ny
    # ra pixel canvas
    assert abs(nx * 784 - 333.9) < 1.0
    assert abs(ny * 505 - 119.1) < 1.0


def test_nut_dong_popup_loi_moi_that_duoc_khop():
    """Popup ĐANG MỞ trên máy người dùng lúc dò: `PopupInveteJoinRom`, nút tên
    `BtnCancel`. Mẫu CŨ chỉ khớp `btn_cancel` (có gạch dưới) nên KHÔNG đóng
    được — popup nằm che màn và mọi thao tác sau đó đều trượt.
    """
    import re

    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function dismissPopupsAndBanners", 1)[1][:2200]
    dong = [d for d in khoi.splitlines() if "test(name)" in d and "close|dong" in d][0]
    mau = dong.split("/", 1)[1].rsplit("/", 1)[0]
    rx = re.compile(mau, re.I)
    assert rx.match("btncancel"), "không khớp nút thật BtnCancel"
    assert rx.match("btn_close") and rx.match("btnClose")
    # không được khớp bừa
    assert not rx.match("btnok"), "không được bấm CHẤP NHẬN lời mời"
    assert not rx.match("khungdong") and not rx.match("dongho")

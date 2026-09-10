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
    """Bấm xong phải KIỂM, không tin giá trị trả về.

    Và phải kiểm bằng SPRITE, không phải chữ: ĐO TRÊN MÀN GAME BÀI THẬT cho
    thấy các ô game KHÔNG có nhãn chữ — tên game là hình vẽ. Bản dò theo chữ
    trả về "chưa vào" ngay cả khi màn đã mở.
        vgcg_1  -> "tien-len-dem-la@2x"   (ô cần bấm)
        vgcg_11 -> "tielenmiennam@2x"     (ô Tiến Lên Miền Nam, phải tránh)
    """
    code = _code(EXT)
    assert "function dangOManGameBai()" in code
    khoi = EXT.read_text(encoding="utf-8").split("function dangOManGameBai", 1)[1][:600]
    assert "timTheoSprite(" in khoi, "vẫn nhận màn Game Bài bằng chữ"
    assert 'includes("demla")' in khoi


def test_o_dem_la_phan_biet_voi_tien_len_mien_nam():
    """Hai ô RIÊNG BIỆT trong màn Game Bài. Sprite phân biệt chúng dứt khoát:
    ô cần bấm là "tien-len-dem-la", ô cần tránh là "tielenmiennam" — chuỗi
    "demla" chỉ có ở ô đầu."""
    code = _code(EXT)
    khoi = code.split("MUC_DIEU_HUONG", 1)[1][:700]
    assert 'timTheoSprite((sp) => sp.includes("demla"))' in khoi
    # chốt bằng chính hai tên sprite đo được
    chuan = lambda t: t.lower().replace("@2x", "").replace("-", "")
    assert "demla" in chuan("tien-len-dem-la@2x")
    assert "demla" not in chuan("tielenmiennam@2x")


def test_ten_sprite_duoc_chuan_hoa():
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function tenSprite", 1)[1][:700]
    assert "@" in khoi and "toLowerCase()" in khoi
    assert "[^a-z0-9]" in khoi


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


# ---------- lớp phủ rỗng KHÔNG phải popup ----------

def test_lop_phu_rong_khong_bi_coi_la_popup():
    """ĐO TRÊN SẢNH THẬT: `PopupNode` là container RỖNG phủ toàn màn
    (1560x720) và LUÔN tồn tại — không nhãn, không nút.

    Chỉ khớp theo tên có chữ "popup" thì `hasBlockingPopup()` luôn trả true ->
    `isAlreadyInTLDLLobby()` luôn false -> tool KHÔNG BAO GIỜ coi profile nào là
    sẵn sàng ở sảnh. Đây là lỗi do chính bản vá popup trước đó gây ra.
    """
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function tenPopupDangChe", 1)[1][:2600]
    assert "coNoiDung" in khoi, "chưa kiểm popup có nội dung hay không"
    assert "&& coNoiDung(node)" in khoi, "vẫn nhận popup chỉ theo tên"


def test_popup_co_noi_dung_nghia_la_co_nhan_hoac_nut():
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("const coNoiDung =", 1)[1][:900]
    assert "getCocosNodeText(n)" in khoi
    assert 'n.getComponent("cc.Button")' in khoi


def test_van_bat_duoc_banh_bao_lua_dao_theo_CHU():
    """Banner "CẢNH BÁO LỪA ĐẢO" nhận theo CHỮ nên không phụ thuộc tên node."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function tenPopupDangChe", 1)[1][:2600]
    assert 'text === "CẢNH BÁO LỪA ĐẢO"' in khoi
    assert 'text === "BỎ QUA"' in khoi
    # nhánh theo chữ phải đứng TRƯỚC nhánh theo tên (không cần coNoiDung)
    assert khoi.index('CẢNH BÁO LỪA ĐẢO') < khoi.index("&& coNoiDung(node)")


# ---------- không được đâm vào card game ngay bên dưới tab ----------

def test_tu_choi_bam_neu_diem_roi_vao_o_game_khac():
    """Ngay dưới hàng tab là dãy card TÀI XỈU / TÀI XỈU MD5 / XÓC ĐĨA.

    Toạ độ mù `0.250` là TỈ LỆ theo chiều cao canvas: ở 784x505 nó ra y=126
    (trúng tab), nhưng ở kích thước cửa sổ mặc định của app 520x580 thì
    0.250*580 = 145 — đúng mép trên của card TÀI XỈU. Một hằng số chỉ đúng ở
    đúng một kích thước cửa sổ.
    """
    code = _code(EXT)
    assert "function deLenSanhKhac(" in code
    khoi = EXT.read_text(encoding="utf-8").split("function bamNodeAnToan", 1)[1][:2600]
    assert "deLenSanhKhac(vt.nx, vt.ny)" in khoi
    assert "TỪ CHỐI bấm" in khoi


def test_chot_bo_qua_nhan_ti_hon_chi_xet_o_that():
    """Nhãn chữ nhỏ không phải "ô game" — chỉ chặn khi khối đủ lớn."""
    src = EXT.read_text(encoding="utf-8")
    khoi = src.split("function deLenSanhKhac", 1)[1][:1600]
    assert "vs.width * 0.03" in khoi and "vs.height * 0.03" in khoi
    assert "1 - ny) * vs.height" in khoi, "phải đổi về hệ Cocos (y từ dưới lên)"


def test_danh_sach_nhan_khop_anh_chup_that():
    """Đọc từ ảnh chụp sảnh: tab ALL GAMES / YÊU THÍCH / GAME BÀI / SLOTS /
    LIVE / KHÁC, và card TÀI XỈU, TÀI XỈU MD5, XÓC ĐĨA."""
    code = _code(EXT)
    khoi = code.split("const NHAN_SANH_KHAC", 1)[1][:400]
    for nhan in ('"TÀI XỈU MD5"', '"XÓC ĐĨA"', '"ALL GAMES"', '"KHÁC"'):
        assert nhan in khoi, f"thiếu nhãn: {nhan}"


def test_phep_doi_toa_do_o_kich_thuoc_cua_so_mac_dinh():
    """Chứng minh bằng số: cùng hằng số 0.250, hai kích thước cửa sổ cho hai
    kết quả khác hẳn — một trúng tab, một trúng card."""
    # kích thước lúc đo được
    assert round(0.250 * 505) == 126        # trúng dải tab
    # kích thước mặc định của app (hai ô "Rộng/Cao" cũ: 520x580)
    assert round(0.250 * 580) == 145        # rơi xuống mép card TÀI XỈU


# ---------- JS tính vị trí, Python bấm THẬT ----------

def test_js_khong_tu_bam_ma_chi_tra_vi_tri():
    """ĐO ĐƯỢC: sự kiện chuột/cảm ứng TỔNG HỢP bằng JS KHÔNG tới được Cocos.

    Đã thử năm kiểu trên sảnh thật — mouse trên canvas, touch, pointer kiểu
    touch, mouse trên document, emit thẳng vào node — không kiểu nào chuyển
    được tab. Chỉ `page.mouse.click` của Playwright (sự kiện thật) mới ăn; đã
    xác nhận bằng ảnh chụp trước/sau.
    """
    code = _code(EXT)
    assert "G.__autotool_vi_tri_muc = function" in code
    khoi = EXT.read_text(encoding="utf-8").split("__autotool_vi_tri_muc", 1)[1][:1400]
    assert "dispatchCanvasClick" not in khoi, "JS vẫn tự bấm"
    assert "return { ok: true, nx:" in khoi


def test_python_bam_bang_chuot_that():
    src = (BE / "controllers/auto_flow_controller/lobby.py").read_text(encoding="utf-8")
    khoi = src.split("async def bam_muc", 1)[1][:2200]
    assert "__autotool_vi_tri_muc" in khoi
    assert "await p.mouse.click(x, y)" in khoi


def test_uu_tien_node_TRONG_KHUNG_HINH():
    """Danh sách game là ScrollView ngang: cùng lúc có ô Đếm Lá ở nx=0.286
    (đang hiện) và các mục khác ở nx=2.2, 3.7, 4.1 — ngoài màn về bên phải,
    mà `activeInHierarchy` vẫn TRUE. Lấy "node khớp đầu tiên" là bấm ra ngoài
    khung hình (đo được: tính ra x=1739 trên canvas rộng 784).
    """
    src = EXT.read_text(encoding="utf-8")
    for ham in ("function timTheoSprite", "function timNodeHien"):
        khoi = src.split(ham, 1)[1][:1800]
        assert "viTriNodeTrenCanvas(khop[i])" in khoi, f"{ham} chưa ưu tiên node trong khung"


# ---------- nhận diện màn hình theo TÊN SCENE ----------

def test_nhan_dien_theo_ten_scene():
    """ĐO ĐƯỢC — dấu hiệu dứt khoát nhất, khỏi đoán qua chữ:
        "LobbyNew"  -> sảnh chính
        "TLDLScene" -> khu Tiến Lên Đếm Lá
    """
    code = _code(EXT)
    assert "function tenScene()" in code
    khoi = EXT.read_text(encoding="utf-8").split("__autotool_man_hinh", 1)[1][:1400]
    assert 'sc.includes("tldl")' in khoi


def test_moc_cua_sanh_chon_ban_dung_ten_node_do_duoc():
    """ĐO ĐƯỢC ở sảnh chọn bàn: `lblMucCuoc` (nhãn mức cược trên từng ô bàn),
    `lblSolo` chữ "BÀN SOLO (280)", `lbl4Nguoi` chữ "BÀN 4 NGƯỜI (6)"."""
    code = _code(EXT)
    assert 'n === "lblmuccuoc"' in code
    assert 'n === "lblsolo"' in code and 'n === "lbl4nguoi"' in code


def test_tab_cho_ngoi_khop_nhan_THAT():
    """Nhãn thật là "BÀN SOLO (280)", KHÔNG phải "SOLO" trần như bản trước tìm —
    và còn kèm số đếm nên phải khớp theo TIỀN TỐ."""
    code = _code(EXT)
    khoi = code.split("MUC_DIEU_HUONG", 1)[1][:900]
    assert 'startsWith("BÀN SOLO")' in khoi
    assert 'startsWith("BÀN 4 NGƯỜI")' in khoi
    assert 't === "SOLO"' not in khoi, "vẫn khớp nhãn trần 'SOLO'"


# ---------- rào chắn: MỌI account phải ở sảnh chọn bàn ----------

def test_xac_minh_lai_tung_profile_truoc_khi_join():
    """Một nick còn kẹt ngoài sảnh chính là cả lượt chạy hỏng: nick giữ tiền
    vào bàn rồi ngồi đó một mình với người lạ."""
    src = (BE / "controllers/auto_flow_controller/matching.py").read_text(encoding="utf-8")
    khoi = src.split("not_ready = []", 1)[1][:900]
    assert "man_hinh_hien_tai(pages.get(p_name))" in khoi
    assert 'man != "chon_ban"' in khoi


def test_bao_ro_dang_ket_o_dau():
    src = (BE / "controllers/auto_flow_controller/lobby.py").read_text(encoding="utf-8")
    khoi = src.split("async def ly_do_chua_o_sanh", 1)[1][:2000]
    for m in ("sanh_chinh", "game_bai", "trong_ban", "chon_ban"):
        assert m in khoi, f"thiếu mô tả cho màn {m}"
    assert "chưa bấm được ô Tiến Lên Đếm Lá" in khoi

"""Đo việc bàn bị chen — CHỈ ĐO VÀ BÁO, không tự dừng lượt chạy.

VÌ SAO KHÔNG LÀM NHƯ SUNWIN

Công cụ Sunwin có cờ `chongPha`: ở trạng thái đợi khách, nếu bàn "từng sạch rồi
hết sạch" mà nút Bắt đầu chưa kịp hiện thì nó kết luận bàn bị phá, rời bàn và
huỷ trạng thái. Bên mình KHÔNG mang luật đó sang, vì đo trên chính bản ghi WS
của dự án cho thấy hai tín hiệu tương đương đều là sinh hoạt bình thường của
sảnh, không phải dấu hiệu bị phá:

  - "Vừa join đã thấy có người": 68/117 khung cmd 202 trong `ws_capture.jsonl`
    (58%) và 23/58 trong `manual_join_capture.jsonl` (40%) có hơn một người.
    Nguyên nhân cơ cấu: mỗi (mức cược, số ghế) chỉ có ĐÚNG MỘT rid, nên lệnh
    join là "cho tôi vào phòng $100 Solo" và server tự xếp chỗ — giờ đông thì
    bàn có sẵn người là kết quả mặc định.

  - "Có người chen vào lúc đang giữ bàn": trong `manual_join_capture.jsonl`,
    bốn người chơi thật khác nhau ngồi rồi đi ở cùng một bàn $100 trong chưa
    đầy một phút (Thongcat ~11 giây, vanbidinh0704 ~7 giây, rồi hai người nữa).
    Đếm tuyệt đối sẽ ghi bốn mốc "bị phá" cho một phút chơi hoàn toàn bình thường.

Nên bộ đếm này phân biệt hai việc:
  * `ghi_moc`  — ghi nhận MỌI mốc, để về sau có số liệu thật mà đặt ngưỡng.
  * `tom_tat`  — chỉ cảnh báo khi CÙNG MỘT người (theo uid) chen nhiều lần
    trong cửa sổ thời gian. Khách khác nhau mỗi lần là sinh hoạt sảnh, không đếm.

Thuần, không I/O, không import FastAPI — kiểm thử trực tiếp bằng pytest.
"""

LY_DO_HOP_LE = (
    "khach_la",            # join xong thấy bàn đã có người lạ
    "ban_full",            # join xong thấy bàn đã đủ chỗ
    "khong_doc_duoc",      # không đọc được trạng thái bàn
    "khach_chen_khi_giu",  # ĐÃ xác minh bàn trống rồi mới bị chen — tín hiệu thật
    "gate_khong_an_toan",  # cổng cấp vé từ chối
    "xac_minh_that_bai",   # nick phụ không vào được bàn
)

# Chỉ những lý do này mới được tính vào cảnh báo. Ba lý do đầu của
# `LY_DO_HOP_LE` là kết quả bình thường của việc quét bàn (đo ở phần đầu file).
LY_DO_TINH_CANH_BAO = ("khach_chen_khi_giu",)

# Cùng một uid phải chen từ mức này trở lên trong cửa sổ mới coi là bị phá.
NGUONG_CUNG_NGUOI = 3
CUA_SO_MAC_DINH = 600.0


def ghi_moc(nhat_ky, ly_do, rid, t_ms, uid=None):
    """Trả về DANH SÁCH MỚI, không sửa tại chỗ.

    Trả bản sao để bên gọi không vô tình chia sẻ trạng thái giữa các vòng lặp —
    lỗi kiểu đó rất khó thấy khi đọc log.
    """
    ds = list(nhat_ky or [])
    ly_do_chuan = ly_do if ly_do in LY_DO_HOP_LE else "khong_doc_duoc"
    ds.append({
        "ly_do": ly_do_chuan,
        "rid": rid,
        "t": float(t_ms),
        "uid": str(uid).strip() if uid else "",
    })
    return ds


def tom_tat(nhat_ky, now, cua_so_giay=CUA_SO_MAC_DINH,
            nguong_cung_nguoi=NGUONG_CUNG_NGUOI):
    """Tổng hợp nhật ký thành số liệu + cờ cảnh báo.

    `canh_bao` chỉ bật khi CÙNG MỘT uid chen từ `nguong_cung_nguoi` lần trở lên
    trong cửa sổ. Cấu hình xấu (cửa sổ hoặc ngưỡng <= 0) thì không cảnh báo —
    hỏng theo hướng im lặng, vì đây chỉ là bộ đo.
    """
    ds = list(nhat_ky or [])
    theo_ly_do = {}
    for m in ds:
        theo_ly_do[m["ly_do"]] = theo_ly_do.get(m["ly_do"], 0) + 1

    if cua_so_giay <= 0:
        trong_cua_so = []
    else:
        moc_cu_nhat = float(now) - float(cua_so_giay)
        trong_cua_so = [m for m in ds if m["t"] >= moc_cu_nhat]

    dem_theo_uid = {}
    for m in trong_cua_so:
        if m["ly_do"] not in LY_DO_TINH_CANH_BAO or not m["uid"]:
            continue
        dem_theo_uid[m["uid"]] = dem_theo_uid.get(m["uid"], 0) + 1

    ke_lap_lai = sorted(
        (u for u, n in dem_theo_uid.items() if n >= nguong_cung_nguoi),
        key=lambda u: (-dem_theo_uid[u], u),
    ) if nguong_cung_nguoi > 0 else []

    return {
        "tong": len(ds),
        "trong_cua_so": len(trong_cua_so),
        "theo_ly_do": theo_ly_do,
        "ke_lap_lai": ke_lap_lai,
        "canh_bao": bool(ke_lap_lai),
    }

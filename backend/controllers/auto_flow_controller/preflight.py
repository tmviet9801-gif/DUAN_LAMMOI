"""Kiểm điều kiện TRƯỚC khi mở profile để vào bàn.

Mở Chrome là thao tác đắt và lộ liễu: bật cửa sổ, nạp game, đăng nhập, rồi mới
phát hiện account hết tiền hoặc token đã hết hạn — lúc đó đã ngồi vào bàn rồi.
Tệ hơn, một account thiếu tiền vào bàn sẽ bị server đá ra giữa chừng, để account
giữ tiền ngồi lại một mình với người lạ.

Kiểm trước bằng token + WebSocket (`check_live`), KHÔNG mở Chrome. Profile nào
không thoả thì không mở.

BA ĐIỀU KIỆN:

1. Đọc được trạng thái (token còn hạn). Không đọc được thì không biết gì về
   account đó — mở ra là mò mẫm.

2. Số dư >= mức tối thiểu của bàn. Con số này ĐO ĐƯỢC từ trường `mM` trong
   khung `cmd 300` (danh sách phòng) của server, không phải phỏng đoán:

       cược 100      -> tối thiểu 500        (5x)
       cược 500 trở lên -> tối thiểu = cược x 10

   Bàn $100 chỉ cần 5x chứ không phải 10x — quy tắc không đều, nên bảng này
   bám theo số đo. 862 lần quan sát mỗi mức trong data/game_sim_debug.

3. Có `character_name`. Xác minh đồng đội khớp CHÍNH XÁC tên in-game; thiếu nó
   thì `isPartner` luôn trả false, các nick không nhận ra nhau và tool đánh như
   người thường — vào bàn cũng vô nghĩa.
"""
import logging

from .check_live import check_one_profile

log = logging.getLogger("auto_flow_controller")

# Đo từ trường `mM` của khung cmd 300, gid=1 (Tiến Lên Đếm Lá).
SO_DU_TOI_THIEU_DO_DUOC = {
    100: 500,
    500: 5_000,
    1_000: 10_000,
    2_000: 20_000,
    5_000: 50_000,
    10_000: 100_000,
    20_000: 200_000,
    50_000: 500_000,
    100_000: 1_000_000,
    200_000: 2_000_000,
    500_000: 5_000_000,
    1_000_000: 10_000_000,
    2_000_000: 20_000_000,
    5_000_000: 50_000_000,
}
HE_SO_DU_PHONG = 10          # mức cược lạ -> dùng hệ số phổ biến nhất


def so_du_toi_thieu(bet) -> int:
    """Số dư tối thiểu để ngồi được bàn mức `bet`."""
    try:
        bet = int(bet or 0)
    except (TypeError, ValueError):
        return 0
    if bet <= 0:
        return 0
    if bet in SO_DU_TOI_THIEU_DO_DUOC:
        return SO_DU_TOI_THIEU_DO_DUOC[bet]
    return bet * HE_SO_DU_PHONG


def danh_gia(live, account, bet):
    """Một account có đủ điều kiện vào bàn không.

    Trả `(dat, ly_do)`. `ly_do` là câu nói thẳng cho người dùng, rỗng khi đạt.
    """
    live = live or {}

    if live.get("ten_in_game") is None and live.get("so_du") is None:
        loi = live.get("loi") or "không đọc được trạng thái"
        return False, f"không kiểm tra được ({loi})"

    can = so_du_toi_thieu(bet)
    so_du = live.get("so_du")
    if so_du is None:
        return False, "không đọc được số dư"
    if can and so_du < can:
        return False, (f"số dư {so_du:,} < tối thiểu {can:,} của bàn ${int(bet):,}"
                       .replace(",", "."))

    ten = (live.get("ten_in_game")
           or str(account.get("character_name") or "").strip())
    if not ten:
        return False, "chưa có tên in-game (chạy Check Live trước)"

    return True, ""


async def loc_profile_du_dieu_kien(adapter, hub, accounts, bet, *,
                                   token_store=None):
    """Lọc danh sách account xuống những cái ĐỦ ĐIỀU KIỆN vào bàn.

    Không mở Chrome: profile đang mở thì đọc từ trang, profile đóng thì dùng
    token + WebSocket.

    Trả `(dat, bi_loai)`; `bi_loai` là danh sách dict {profile, ly_do, so_du}
    để báo lại cho người dùng biết vì sao.
    """
    dat, bi_loai = [], []
    for a in accounts or []:
        if not isinstance(a, dict) or not a.get("name"):
            continue
        try:
            live = await check_one_profile(adapter, hub, a, token_store=token_store)
        except Exception as e:
            live = {"loi": f"{type(e).__name__}: {e}"}

        ok, ly_do = danh_gia(live, a, bet)
        if ok:
            # Ghi lại tên in-game vừa đọc được: bước ghép bàn dùng nó làm khoá
            # đối chiếu, và bản trong database có thể đã cũ.
            if live.get("ten_in_game"):
                a = {**a, "character_name": live["ten_in_game"]}
            dat.append(a)
        else:
            bi_loai.append({
                "profile": a.get("name"),
                "ly_do": ly_do,
                "so_du": live.get("so_du"),
            })
            log.warning("preflight: bỏ qua %s — %s", a.get("name"), ly_do)

    return dat, bi_loai

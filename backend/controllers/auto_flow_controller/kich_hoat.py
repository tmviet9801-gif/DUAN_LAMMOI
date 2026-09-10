"""Kích hoạt tự động trên từng trang: ĐẶT, ĐỌC LẠI, và BẬT LẠI khi rớt.

Lỗi thật (gom bàn 2 account, 10/09/2026): hai nick vào chung bàn, chia bài
xong, Account 01 (chính) tự đánh còn Account 02 (phụ) không đánh cũng không
bỏ — mỗi nước cách nhau đúng ~21 giây, tức phụ để server tự bỏ lượt hộ. Hết
ván phụ cũng không rời bàn, khách ngoài không vào được.

Cả hai triệu chứng chung MỘT cổng: `isAutoEngaged()` trong content_main.js
trả false trên trang phụ. Cổng đó đọc localStorage `AUTOTOOL_STOPPED` và ba
cờ trong bộ nhớ trang (`__AUTOTOOL_ENGAGED` / `ARMED` / `AUTO_HUNT`). Khối cấu
hình ANCHOR xoá cờ Dừng và đặt `ARMED = true`; khối cấu hình PHỤ chỉ đặt vai
trò — không xoá cờ, không mở cổng. Vì thế bất kỳ thứ gì làm rớt cổng sau
preflight (trang tải lại, cờ Dừng bị đặt lại, extension nạp lại) là phụ câm
lặng cho tới hết ván. Bước đọc lại cũ chỉ kiểm `__AUTOTOOL_MATCH_ROLE`, nên
không thấy.

Nguyên tắc: mỗi lúc sắp cần tự động (trước Sẵn sàng, trong lúc ván chạy) là
một lần ĐẶT + ĐỌC LẠI, không tin lần đặt trước.
"""
import json
import logging

from core.page_world import eval_page as _eval_page_that

log = logging.getLogger("auto_flow_controller")

# Đọc đúng những gì `isAutoEngaged()` và `handleAutoTurn()` sẽ đọc.
JS_DOC_TRANG_THAI = """() => {
    let coDung = false;
    try { coDung = localStorage.getItem('AUTOTOOL_STOPPED') === '1'; } catch (e) {}
    return {
        role: window.__AUTOTOOL_MATCH_ROLE || null,
        co_dung: coDung,
        engaged: !coDung && !!(window.__AUTOTOOL_ENGAGED
                               || window.__AUTOTOOL_ARMED
                               || window.__AUTOTOOL_AUTO_HUNT),
        auto_xa: !!window.__AUTOTOOL_AUTO_DISCARD,
    };
}"""


def js_kich_hoat(vai_tro, auto_xa, dong_doi, bet, mu):
    """JS đặt TRỌN cấu hình tự động cho một trang theo vai trò.

    Đặt cả cổng lẫn vai trò trong một lần, cho cả anchor lẫn phụ — không còn
    hai khối lệch nhau. Không đụng `__auto_start_guest_ss` (thuộc anchor và do
    chỗ khác quyết).
    """
    la_anchor = vai_tro == "anchor"
    return f"""() => {{
        try {{ localStorage.removeItem('AUTOTOOL_STOPPED'); }} catch (e) {{}}
        window.__AUTOTOOL_ENGAGED = true;
        window.__AUTOTOOL_AUTO_HUNT = false;
        window.__AUTOTOOL_GIU_BAN = false;
        window.__AUTOTOOL_ARMED = {json.dumps(la_anchor)};
        window.__is_hunt_initiator = {json.dumps(la_anchor)};
        window.__AUTOTOOL_MATCH_ROLE = {json.dumps(vai_tro)};
        window.__AUTOTOOL_ROLE = {json.dumps("winner" if la_anchor else "dump")};
        window.__AUTOTOOL_PARTNER_PROFILES = {json.dumps(list(dong_doi))};
        window.__AUTOTOOL_AUTO_DISCARD = {json.dumps(bool(auto_xa))};
        window.__target_hunt_bet = {json.dumps(bet)};
        window.__target_hunt_mu = {json.dumps(mu)};
    }}"""


def js_giu_ban(auto_xa, auto_start_guest_ss, bet, mu):
    """JS đưa trang CHÍNH vào chế độ GIỮ BÀN sau khi phụ đã out.

    Chính ở lại bàn, cổng kích hoạt vẫn MỞ, auto-xả vẫn BẬT: khách lạ ngồi vào
    và Sẵn sàng thì tự Bắt đầu (nếu bật) và bộ xả hiện có tự đánh — không đổi
    một dòng nào của luật chọn nước. Không còn đồng đội để chờ, nên xoá danh
    sách đồng đội: các lớp gác "đang chờ đồng đội -> rời bàn khi thấy khách
    lạ" không được phép nổ trong chế độ này (extension kiểm `__AUTOTOOL_GIU_BAN`).
    """
    return f"""() => {{
        try {{ localStorage.removeItem('AUTOTOOL_STOPPED'); }} catch (e) {{}}
        window.__AUTOTOOL_ENGAGED = true;
        window.__AUTOTOOL_ARMED = true;
        window.__AUTOTOOL_AUTO_HUNT = false;
        window.__AUTOTOOL_GIU_BAN = true;
        window.__AUTOTOOL_MATCH_ROLE = "anchor";
        window.__AUTOTOOL_ROLE = "winner";
        window.__is_hunt_initiator = true;
        window.__is_matched_locked = false;
        window.__AUTOTOOL_PARTNER_PROFILES = [];
        window.__autotool_partners = [];
        window.__partner_cards = null;
        window.__AUTOTOOL_AUTO_DISCARD = {json.dumps(bool(auto_xa))};
        window.__auto_start_guest_ss = {json.dumps(bool(auto_start_guest_ss))};
        window.__target_hunt_bet = {json.dumps(bet)};
        window.__target_hunt_mu = {json.dumps(mu)};
        if (window.__hunt_retry_timer) {{ clearTimeout(window.__hunt_retry_timer); window.__hunt_retry_timer = null; }}
        if (window.__hunt_wait_timer) {{ clearTimeout(window.__hunt_wait_timer); window.__hunt_wait_timer = null; }}
        if (window.__start_retry_timer) {{ clearInterval(window.__start_retry_timer); window.__start_retry_timer = null; }}
        if (window.__guest_ss_wait_timer) {{ clearTimeout(window.__guest_ss_wait_timer); window.__guest_ss_wait_timer = null; }}
        if (window.__stranger_leave_timer) {{ clearTimeout(window.__stranger_leave_timer); window.__stranger_leave_timer = null; }}
    }}"""


def ly_do_chua_kich_hoat(trang_thai, vai_tro, auto_xa):
    """None khi trang đúng như mong đợi; ngược lại là câu nói rõ sai ở đâu."""
    if not isinstance(trang_thai, dict):
        return "không đọc được trạng thái trang"
    if trang_thai.get("role") != vai_tro:
        return f"cần {vai_tro}, thực tế {trang_thai.get('role')}"
    if trang_thai.get("co_dung"):
        return "còn cờ Dừng (AUTOTOOL_STOPPED=1)"
    if not trang_thai.get("engaged"):
        return "cổng kích hoạt đóng (__AUTOTOOL_ENGAGED/ARMED đều tắt)"
    if bool(trang_thai.get("auto_xa")) != bool(auto_xa):
        return f"auto-xả cần {bool(auto_xa)}, thực tế {bool(trang_thai.get('auto_xa'))}"
    return None


async def bao_dam_kich_hoat(pages, first_name, auto_xa, bet, mu,
                            eval_page=None, so_lan=2):
    """Đọc từng trang; trang nào lệch thì đặt lại rồi đọc lại.

    Trả `(loi, da_bat_lai)`:
      - `loi`: danh sách "tên: lý do" cho trang vẫn sai sau `so_lan` lần đặt;
      - `da_bat_lai`: tên các trang đã phải đặt lại (và đã đúng) — người gọi
        nên ghi cảnh báo, vì đó là dấu vết của thứ đã làm rớt cổng.
    """
    goi = eval_page or _eval_page_that
    loi, da_bat_lai = [], []
    for ten, trang in pages.items():
        vai_tro = "anchor" if ten == first_name else "sub"
        dong_doi = ([n for n in pages if n != first_name] if vai_tro == "anchor"
                    else [first_name])
        ly_do = None
        for lan in range(so_lan + 1):
            try:
                trang_thai = await goi(trang, JS_DOC_TRANG_THAI)
            except Exception as e:
                trang_thai = None
                ly_do = f"không đọc được trạng thái trang ({e})"
            else:
                ly_do = ly_do_chua_kich_hoat(trang_thai, vai_tro, auto_xa)
            if ly_do is None:
                if lan > 0:
                    da_bat_lai.append(ten)
                break
            if lan == so_lan:
                break
            try:
                await goi(trang, js_kich_hoat(vai_tro, auto_xa, dong_doi, bet, mu))
            except Exception as e:
                ly_do = f"không đặt được ({e})"
                break
        if ly_do is not None:
            loi.append(f"{ten}: {ly_do}")
    return loi, da_bat_lai

"""Hỏi SỐ NGƯỜI trong bàn TRƯỚC KHI vào — không nhảy vào bàn đang có khách.

Lỗi thật (10/09/2026 16:04:27): bàn $100 Solo chỉ có một rid (#2). Khách
`chiiritroi6879` ngồi sẵn (đã bấm Bắt đầu chờ người), Account chính nhảy vào
để "kiểm bàn trống" — server chia bài NGAY TRONG GIÂY ĐÓ, lệnh rời không
kịp. Chính bị kéo vào một ván tiền thật với khách. Cách dò cũ ("vào rồi mới
nhìn có ai không") về bản chất là đánh cược mỗi lần dò.

Server đẩy thông tin từng bàn qua cmd 305 `ri:{rid, uC, b, Mu, rn}` (`uC` =
số người đang ngồi), cmd 300 `rs[]` là dạng dự phòng — hitclub.py đã dùng
đúng nguồn này để tìm bàn trống. Extension ghi lại theo rid; controller hỏi
trước mỗi lần vào: bàn đang có người thì ĐỨNG Ở SẢNH CHỜ, không vào.

Không đọc được (extension cũ, không có khung 305) thì vào kiểm như cũ —
không tệ hơn trước — và ghi rõ vào log là đang đi đường cũ.
"""
import logging

from core.page_world import eval_page as _eval_page_that

log = logging.getLogger("auto_flow_controller")

# Bộ nhớ trong trang coi là "mới" nếu chưa quá chừng này mili-giây. Khách vừa
# ngồi xuống là uC đổi ngay; nhìn số cũ 2-3 giây là lại rơi vào đúng cuộc đua
# đang tránh, nên chỉ tin số mới hơn 1 giây, còn lại hỏi server.
TUOI_MOI_MS = 1000

# Cài lên trang cùng lúc với hàm join. Trả Promise -> {uC, tuoi_ms, nguon}
# hoặc null khi không có cách nào biết.
JS_SO_NGUOI_BAN = """(function (rid, reqFrame, choMs) {
    return new Promise(function (resolve) {
        const lay = function () { return (window.__ban_theo_rid || {})[Number(rid)] || null; };
        const tuoi = function (b) { return b ? (Date.now() - (b.ts || 0)) : Infinity; };
        const cu = lay();
        if (cu && tuoi(cu) < %(tuoi_moi)d) {
            resolve({ uC: cu.uC, tuoi_ms: tuoi(cu), nguon: 'cache' });
            return;
        }
        const simms = (window.__ws_get_simms && window.__ws_get_simms()) || null;
        if (!simms || simms.readyState !== 1 || !reqFrame) { resolve(null); return; }
        const t0 = Date.now();
        try { simms.send(reqFrame); } catch (e) { resolve(null); return; }
        const tick = setInterval(function () {
            const b = lay();
            if (b && (b.ts || 0) >= t0) {
                clearInterval(tick);
                resolve({ uC: b.uC, tuoi_ms: Date.now() - b.ts, nguon: 'hoi' });
                return;
            }
            if (Date.now() - t0 > choMs) { clearInterval(tick); resolve(null); }
        }, 40);
    });
})""" % {"tuoi_moi": TUOI_MOI_MS}


def doc_so_nguoi(kq):
    """`uC` từ kết quả trang trả về; None khi không biết. Không đoán."""
    if not isinstance(kq, dict):
        return None
    try:
        return int(kq.get("uC"))
    except (TypeError, ValueError):
        return None


async def so_nguoi_trong_ban(page, rid, req_frame, cho_ms=700, eval_page=None):
    """Số người đang ngồi trong bàn `rid`, hoặc None nếu không đọc được."""
    if not rid:
        return None
    goi = eval_page or _eval_page_that
    # `eval_page` chỉ nhận MỘT tham số -> gói vào một object.
    tham_so = {"rid": int(rid), "req": req_frame or "", "cho": int(cho_ms)}
    try:
        kq = await goi(
            page,
            "(a) => (typeof window.__autotool_so_nguoi_ban === 'function')"
            " ? window.__autotool_so_nguoi_ban(a.rid, a.req, a.cho) : null",
            tham_so)
    except Exception as e:
        log.debug("so_nguoi_trong_ban: không hỏi được (%s)", e)
        return None
    return doc_so_nguoi(kq)

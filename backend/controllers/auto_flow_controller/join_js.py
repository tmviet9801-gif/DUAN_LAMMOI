"""JS cài vào trang để RỜI BÀN CŨ RỒI JOIN LIỀN MẠCH — một nguồn duy nhất.

Trước đây đoạn này nằm nguyên văn trong `matching.py`. Luồng tách lẻ (tìm bàn /
vào bàn theo từng account, `ban_chung.py`) cần đúng hàm đó; chép lại là sớm
muộn hai bản lệch nhau, nên tách ra đây.

Vì sao phải "rời rồi join" trong CÙNG một lần chạy JS: server chỉ nhận join sau
khi đã xác nhận rời bàn cũ, mà mỗi lần quay vòng qua Python là một round-trip
CDP. Đợi ack ngay trong trang rồi bắn join là nhanh và không rớt nhịp.
"""

# Hàm nhận (rid, bet, mu) -> Promise<{ok, via, rid} | {ok:false, reason}>
JS_LEAVE_THEN_JOIN = """(function (rid, bet, mu) {
            return new Promise(function (resolve) {
                const simms = (window.__ws_get_simms && window.__ws_get_simms()) || null;
                if (!simms || simms.readyState !== 1) {
                    resolve({ ok: false, reason: 'no_socket' });
                    return;
                }
                const specificRid = (rid && !isNaN(Number(rid)) && Number(rid) > 0) ? Number(rid) : null;
                if (!specificRid) {
                    console.warn('[AutoTool V3][SRV] Thiếu RID cố định, từ chối join để tránh nhầm mức cược.');
                    resolve({ ok: false, reason: 'no_rid' });
                    return;
                }
                // Chống flood: có RID cụ thể thì 1200ms là đủ (khớp extension).
                // 2500ms của bản cũ còn rộng hơn cả chu kỳ auto-rejoin của game.
                const now = Date.now();
                if (window.__last_join_ts && (now - window.__last_join_ts) < 1200) {
                    resolve({ ok: false, reason: 'anti_flood' });
                    return;
                }

                let done = false;
                function fireJoin(via) {
                    if (done) return;
                    done = true;
                    try { simms.removeEventListener('message', onMsg); } catch (e) {}
                    try {
                        simms.send(JSON.stringify([3, 'Simms', specificRid, '']));
                        window.__last_join_ts = Date.now();
                        console.log('[AutoTool V3][SRV] JOIN rid=' + specificRid + ' ($' + bet + ') qua ' + via);
                        resolve({ ok: true, via: via, rid: specificRid });
                    } catch (e) {
                        resolve({ ok: false, reason: 'send_fail' });
                    }
                }
                function onMsg(ev) {
                    const d = (typeof ev.data === 'string') ? ev.data : '';
                    // Server xác nhận đã rời bàn: [4,true,1,-1,0,""]
                    if (d.indexOf('[4,true') === 0) fireJoin('leave_ack');
                }

                const inside = (typeof window.__autotool_is_inside_table === 'function')
                    ? !!window.__autotool_is_inside_table()
                    : !!(window.__room_players && window.__room_players.length > 0);
                if (!inside) { fireJoin('already_lobby'); return; }

                try { simms.addEventListener('message', onMsg); } catch (e) {}
                try {
                    simms.send('[4,"Simms",-1]');
                    simms.send('[6,"Simms","channelPlugin",{"cmd":203}]');
                } catch (e) {}
                // Không thấy ack (có thể đã ở sảnh sẵn) -> vẫn join sau 700ms.
                setTimeout(function () { fireJoin('timeout'); }, 700);
            });
        })"""


def js_cai_dat_join():
    """JS cài `__autotool_leave_then_join` vào trang (chạy một lần trước khi dò)."""
    return (f"() => {{ window.__autotool_leave_then_join = {JS_LEAVE_THEN_JOIN};"
            f" if (!window.__last_join_ts) window.__last_join_ts = 0; }}")


# Đọc trạng thái bàn đang ngồi.
#
# Tách rõ ĐỒNG ĐỘI và KHÁCH LẠ bằng chính `isPartner` của extension (khớp CHÍNH
# XÁC theo tên nhân vật in-game), không đếm đầu người rồi suy diễn: bàn 2 người
# có thể là "mình + đồng đội" (tốt) hoặc "mình + khách" (phải rời ngay).
JS_DOC_BAN = """() => {
    const pls = window.__room_players || [];
    const info = window.__last_room_info;
    const laMinh = (x) => (typeof window.__is_me === 'function') ? window.__is_me(x) : false;
    const laDongDoi = (x) => (typeof window.__is_partner === 'function') ? window.__is_partner(x) : false;
    const ten = (x) => (x && (x.dn || x.u)) ? String(x.dn || x.u) : '';
    const khac = pls.filter((x) => x && !laMinh(x));
    const dongDoi = khac.filter(laDongDoi);
    const khach = khac.filter((x) => !laDongDoi(x));
    return {
        co_thong_tin: !!info,
        so_nguoi: pls.length,
        so_dong_doi: dongDoi.length,
        so_khach: khach.length,
        ten_dong_doi: dongDoi.map(ten).filter(Boolean),
        ten_khach: khach.map(ten).filter(Boolean),
        // `has_stranger` của extension đếm cả người chưa kịp nhận diện; giữ lại
        // để đối chiếu nhưng quyết định thì dựa vào `so_khach`.
        co_khach_la: khach.length > 0,
        has_stranger_ext: info ? !!info.has_stranger : false,
        ban_trong: info ? !!info.is_verified_empty : false,
        rid: info ? info.rid : null,
        dang_van: !!window.__game_in_progress,
    };
}"""

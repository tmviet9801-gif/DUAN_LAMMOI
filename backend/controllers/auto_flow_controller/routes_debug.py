"""Route kiểm thử thủ công: bảo vệ bàn & xả bài cho một profile."""
import logging

from fastapi import APIRouter, HTTPException, Request

from core.page_world import eval_page

from .deps import _active_adapter

log = logging.getLogger("auto_flow_controller")
router = APIRouter()


@router.post("/api/autoplay/test-protection")
async def autoplay_test_protection(body: dict, request: Request):
    """Test bảo vệ bàn cho 1 profile: đọc phòng, người chơi, phát hiện khách lạ, và thử thoát."""
    import time
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    do_leave = bool(body.get("do_leave", False))
    known_names = body.get("known_names") or [name]

    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")

    current_room = await adapter._page_current_room(page)
    players = await adapter._get_room_players(page)
    game_state = await adapter._get_game_state(page)
    stranger_diag = await adapter._check_has_stranger(page, known_names)

    left = False
    if do_leave:
        left = await adapter._leave_room(page)

    shot = await adapter._screenshot(page, f"test_protect_{name}")
    return {
        "ok": True,
        "profile": name,
        "current_room": current_room,
        "game_state": game_state,
        "players": players,
        "stranger_diag": stranger_diag,
        "left": left,
        "screenshot": shot,
    }


@router.post("/api/autoplay/test-discard")
async def autoplay_test_discard(body: dict, request: Request):
    """Test xả bài có delay cho 1 profile."""
    import time
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    delay_ms = int(body.get("delay_ms", 1000))
    auto_out = bool(body.get("auto_out", False))

    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")

    t0 = time.time()
    ok_discard = await adapter._discard_cards(page, name, delay_ms=delay_ms)
    elapsed_ms = int((time.time() - t0) * 1000)

    left = False
    if auto_out:
        left = await adapter._leave_room(page)

    shot = await adapter._screenshot(page, f"test_discard_{name}")
    return {
        "ok": ok_discard,
        "profile": name,
        "delay_ms": delay_ms,
        "elapsed_ms": elapsed_ms,
        "left": left,
        "screenshot": shot,
    }


# ---- Ảnh chụp "những gì profile này NHÌN THẤY trên bàn" ----

_RANK_NAMES = {2: "3", 3: "4", 4: "5", 5: "6", 6: "7", 7: "8", 8: "9", 9: "10",
               10: "J", 11: "Q", 12: "K", 0: "A", 1: "2"}
_SUIT_ICONS = ["♠", "♣", "♦", "♥"]


def _card_name(cid):
    try:
        cid = int(cid)
    except Exception:
        return str(cid)
    if not (0 <= cid <= 51):
        return str(cid)
    return _RANK_NAMES.get(cid // 4, "?") + _SUIT_ICONS[cid % 4]


_TABLE_VIEW_JS = """() => {
    const out = { me: {}, table: {}, players: [], played_sets: [] };

    // 1. Bài của CHÍNH MÌNH — server chỉ gửi bài của mình (đã xác minh: gói
    //    cmd 202 không bao giờ chứa `cs` của người khác).
    out.me = {
        uid: window.__my_uid || null,
        dn: window.__my_dn || null,
        u: window.__my_u || null,
        cards: (window.__my_cards || []).slice(),
    };

    // 2. Người chơi trong bàn + số lá còn lại. `rmC` do server gửi thường là 0;
    //    extension tự trừ dần theo số lá thấy đối phương đánh ra.
    out.players = (window.__room_players || []).map((p) => ({
        uid: p && p.uid, dn: p && p.dn, u: p && p.u,
        rmC: p && p.rmC,
        // KHÔNG kèm p.cs: kiểm chứng cho thấy trường này chỉ có ở gói cmd 252
        // (lật bài cuối ván), không có trong ván.
        co_cs: !!(p && Array.isArray(p.cs) && p.cs.length),
    }));

    const info = window.__last_room_info || null;
    out.table = {
        rid: info && info.rid, bet: info && info.b, mu: info && info.Mu,
        in_game: !!window.__game_in_progress,
        last_table_cards: (window.__last_table_cards || []).slice(),
        partner_cards_count: window.__partner_cards_count,
    };

    // 3. MỌI BỘ BÀI ĐÃ ĐÁNH RA BÀN — đọc từ component CardSet của Cocos.
    //    Đây là thông tin ai ngồi bàn cũng nhìn thấy.
    try {
        const scene = (typeof cc !== "undefined" && cc.director) ? cc.director.getScene() : null;
        if (scene) {
            (function walk(n, d) {
                if (!n || d > 30) return;
                let cs = [];
                try { cs = n.getComponents(cc.Component) || []; } catch (e) { cs = []; }
                for (const c of cs) {
                    if (!c || typeof c.getListCardID !== "function") continue;
                    let ids = null;
                    try { ids = c.getListCardID(); } catch (e) { ids = null; }
                    if (ids && ids.length) out.played_sets.push(ids.slice());
                }
                const ch = n.children || [];
                for (let i = 0; i < ch.length; i++) walk(ch[i], d + 1);
            })(scene, 0);
        }
    } catch (e) { out.cocos_err = String(e).slice(0, 80); }

    return out;
}"""


@router.get("/api/autoplay/table-view")
async def autoplay_table_view(request: Request, profile_name: str = ""):
    """Chụp lại ĐÚNG những gì một profile đang nhìn thấy trên bàn.

    Chỉ đọc thông tin công khai: bài của chính mình, người chơi trong bàn, và
    mọi bộ bài đã đánh ra bàn. KHÔNG có bài úp của người khác — kiểm chứng trên
    ws_capture cho thấy gói `cmd 202` không bao giờ mang `cs` của người khác;
    trường đó chỉ xuất hiện ở `cmd 252` (lật bài khi ván đã kết thúc).

    Trả kèm phần suy diễn đếm bài: 52 lá trừ đi (bài mình + mọi lá đã ra bàn)
    = tập lá còn ẩn. Đây là nền để tính nước nào chắc thắng.
    """
    name = (profile_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")

    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")

    try:
        raw = await eval_page(page, _TABLE_VIEW_JS) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không đọc được trạng thái bàn: {e}")

    my_cards = [int(c) for c in (raw.get("me") or {}).get("cards") or []]
    played = []
    for s in raw.get("played_sets") or []:
        played.extend(int(c) for c in s)

    seen = sorted(set(my_cards) | set(played))
    unseen = [c for c in range(52) if c not in set(seen)]

    return {
        "ok": True,
        "profile": name,
        "me": {
            **(raw.get("me") or {}),
            "cards_ten": [_card_name(c) for c in my_cards],
            "so_la": len(my_cards),
        },
        "table": raw.get("table") or {},
        "players": raw.get("players") or [],
        "played_sets": [
            {"ids": s, "ten": [_card_name(c) for c in s]}
            for s in (raw.get("played_sets") or [])
        ],
        "dem_bai": {
            "da_thay": len(seen),
            "con_an": len(unseen),
            "con_an_ten": [_card_name(c) for c in unseen],
        },
        "luu_y": "Chỉ gồm thông tin công khai trên bàn. Bài úp của người khác "
                 "không nằm trong luồng WS (đã kiểm chứng trên ws_capture).",
        "cocos_err": raw.get("cocos_err"),
    }

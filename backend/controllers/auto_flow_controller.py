"""Controller: Auto Flow (tìm nhau + xả bài)."""
import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from models.config_model import DATA_DIR, load_accounts

log = logging.getLogger("auto_flow_controller")
router = APIRouter()

AUTOPLAY_CONFIG_FILE = DATA_DIR / "autoplay_config.json"


def _load_game_config() -> dict:
    try:
        if AUTOPLAY_CONFIG_FILE.exists():
            data = json.loads(AUTOPLAY_CONFIG_FILE.read_text(encoding="utf-8"))
            return data.get("game", {}) or {}
    except Exception:
        pass
    return {}


def _build_adapter(request, config):
    from game_sim.adapters.hitclub import HitClubAdapter
    from services.page_pool import PagePool

    bm = request.app.state.manager
    page_pool = PagePool(bm)
    accounts = load_accounts()
    lookup = {a["name"]: a for a in accounts if a.get("name")}
    return HitClubAdapter(config, account_lookup=lookup, page_pool=page_pool)


@router.post("/api/autoplay/debug-ws-hook")
async def autoplay_debug_ws_hook(body: dict, request: Request):
    """Bật WS hook vào page của 1 profile. Mặc định KHÔNG reload (để không làm
    đứt session login của user — game này không giữ login qua reload).

    Body: {profile_name, reload?}
      - reload=true: chỉ dùng khi muốn capture TỪ ĐẦU (trước login). Lúc đó
        user phải login lại thủ công. Mặc định false = chỉ cắm hook, giữ nguyên
        trạng thái đang login.
    """
    from game_sim.ws_sniffer import WsSniffer
    from models.config_model import DATA_DIR

    name = (body.get("profile_name") or "").strip()
    do_reload = bool(body.get("reload", False))
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    manager = request.app.state.manager
    session = None
    for s in manager.sessions.values():
        if s.account and s.account.get("name") == name and s.page:
            session = s
            break
    if not session:
        raise HTTPException(status_code=400, detail="Không tìm thấy session/page của profile")
    page = session.page
    sniffer = WsSniffer(DATA_DIR / "game_sim_debug")
    await sniffer.inject_playwright(page)
    await sniffer.inject_http(page)
    await sniffer.inject_init(page)
    if do_reload:
        # Xóa capture cũ để chỉ giữ demo mới
        for fn in ("ws_capture.jsonl", "room_debug.jsonl", "http_capture.jsonl"):
            try:
                fp = DATA_DIR / "game_sim_debug" / fn
                if fp.exists():
                    fp.unlink()
            except Exception:
                pass
        try:
            await page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        log.info("WS hook đã bật cho %s + RELOAD (capture từ đầu).", name)
        return {"ok": True, "reloaded": True, "message": "WS hook + reload. Thao tác join phòng để bắt WS."}
    log.info("WS hook đã bật cho %s (KHÔNG reload, giữ session).", name)
    return {"ok": True, "reloaded": False, "message": "WS hook đã bật, KHÔNG reload — session login được giữ nguyên."}


@router.post("/api/autoplay/debug-test-join")
async def autoplay_debug_test_join(body: dict, request: Request):
    """Test: JOIN bàn có kèm rid từ danh sách cmd=300.

    Thử nhiều format join, kiểm tra cmd=202 xem có vào đúng bàn (rid) không.
    """
    from game_sim.ws_sniffer import WsSniffer
    from models.config_model import DATA_DIR

    name = (body.get("profile_name") or "").strip()
    rid_override = body.get("rid")
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    manager = request.app.state.manager
    session = None
    for s in manager.sessions.values():
        if s.account and s.account.get("name") == name and s.page:
            session = s
            break
    if not session:
        raise HTTPException(status_code=400, detail="Không tìm thấy session của profile")
    page = session.page
    sniffer = WsSniffer(DATA_DIR / "game_sim_debug")
    await sniffer.inject_playwright(page)
    await sniffer.inject_init(page)
    # reload để socket reconnect qua hook (bắt được _PAGE_WS)
    try:
        await page.reload(wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    await asyncio.sleep(6)

    # chờ socket sẵn sàng
    from game_sim.ws_sniffer import _PAGE_WS
    import time
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _PAGE_WS.get(id(page)) is not None:
            break
        await asyncio.sleep(0.5)

    results = {"rid": None, "rooms_seen": [], "join_tests": []}

    # 1) xem danh sách bàn
    await sniffer.send_raw(page, '[6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":1}]')
    await asyncio.sleep(3)
    await sniffer.drain(page)
    msgs = sniffer.recent(limit=800)
    rooms = []
    for it in msgs:
        try:
            arr = json.loads(it.get("text", ""))
        except Exception:
            continue
        if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], dict):
            p = arr[1]
            if p.get("cmd") == 300 and isinstance(p.get("rs"), list):
                for r in p["rs"]:
                    if isinstance(r, dict) and r.get("rid"):
                        rooms.append({"rid": r.get("rid"), "uC": r.get("uC"), "b": r.get("b"), "rn": r.get("rn"), "Mu": r.get("Mu")})
    # chọn phòng trống
    empty = [r for r in rooms if r["uC"] == 0]
    empty.sort(key=lambda r: r.get("b", 0))
    target = None
    if rid_override:
        target = {"rid": int(rid_override)}
    elif empty:
        target = empty[0]
    results["rooms_seen"] = rooms[:10]
    if not target:
        return {**results, "error": "không có phòng trống để test"}
    rid = target["rid"]
    results["rid"] = rid
    results["target_room"] = target

    # 2) thử join với rid (nhiều format)
    variants = [
        f'[3,"Simms",1,{{"rid":{rid}}}]',
        f'[3,"Simms",1,"{{\\"rid\\":{rid}}}"]',
        f'[3,"Simms",1,{rid}]',
        f'[3,"Simms",1,"{rid}"]',
    ]
    for i, variant in enumerate(variants):
        # out nếu đang trong phòng
        await sniffer.send_raw(page, '[4,"Simms",-1]')
        await asyncio.sleep(1.5)
        ok_send = await sniffer.send_raw(page, variant)
        await asyncio.sleep(3)
        await sniffer.drain(page)
        msgs2 = sniffer.recent(limit=800)
        room202 = None
        for it in msgs2:
            try:
                arr = json.loads(it.get("text", ""))
            except Exception:
                continue
            if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], dict):
                p = arr[1]
                if p.get("cmd") == 202:
                    ps = p.get("ps", [])
                    room202 = {"b": p.get("b"), "Mu": p.get("Mu"), "gS": p.get("gS"), "players": [x.get("dn") for x in ps]}
        results["join_tests"].append({
            "variant": variant, "sent": ok_send, "room202": room202,
        })
        if room202:
            # đã vào phòng, dừng thử tiếp
            results["working_variant"] = variant
            break

    return results


@router.post("/api/autoplay/start")
async def autoplay_start(body: dict, request: Request):
    from game_sim.auto_flow import AutoFlow

    profile_names = [n.strip() for n in (body.get("profile_names") or []) if n.strip()]
    if not profile_names:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào")
    if len(profile_names) > 10:
        raise HTTPException(status_code=400, detail="Tối đa 10 profile/chu trình")

    import license as lic

    if lic.max_tabs() <= 0:
        raise HTTPException(status_code=403, detail="License chưa kích hoạt hoặc hết hạn")

    old = getattr(request.app.state, "auto_flow", None)
    if old:
        old["flow"].stop()

    # gộp config từ body + config đã lưu
    game = body.get("game", {}) or {}
    saved = _load_game_config()
    merged = {**saved, **game}
    if not merged.get("adapter"):
        merged["adapter"] = "hitclub"
    if not merged.get("url"):
        merged["url"] = "https://v.hitclub.latino/?a=hitclub"
    config = {
        "game": merged,
        "auto_out": bool(body.get("auto_out", True)),
        "auto_start": bool(body.get("auto_start", False)),
    }

    adapter = _build_adapter(request, config)
    run_id = f"af_{uuid.uuid4().hex[:8]}"
    flow = AutoFlow(run_id, adapter, config)

    task = asyncio.create_task(flow.run(profile_names))
    request.app.state.auto_flow = {"flow": flow, "task": task, "adapter": adapter}
    return {"ok": True, "run_id": run_id, "profiles": profile_names}


@router.post("/api/autoplay/stop")
async def autoplay_stop(request: Request):
    cur = getattr(request.app.state, "auto_flow", None)
    if cur:
        cur["flow"].stop()
        cur["task"].cancel()
        request.app.state.auto_flow = None
        return {"ok": True}
    return {"ok": False}


@router.get("/api/autoplay/status")
async def autoplay_status(request: Request):
    cur = getattr(request.app.state, "auto_flow", None)
    if not cur:
        return {"running": False, "phase": "IDLE", "members": [], "logs": []}
    flow = cur["flow"]
    return {
        "running": not flow.stop_event.is_set() and not cur["task"].done(),
        "run_id": flow.run_id,
        "phase": flow.phase,
        "phase_label": __import__("game_sim.auto_flow", fromlist=["PHASE_LABELS"]).PHASE_LABELS.get(flow.phase, flow.phase),
        "anchor": flow.anchor,
        "room_id": flow._room_id,
        "members": flow.members,
        "logs": flow.logs[-50:],
    }


# ---- config persistence ----
@router.get("/api/autoplay/config")
async def get_autoplay_config():
    return {"game": _load_game_config()}


@router.post("/api/autoplay/config")
async def save_autoplay_config(body: dict):
    game = body.get("game", {}) or {}
    AUTOPLAY_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTOPLAY_CONFIG_FILE.write_text(
        json.dumps({"game": game}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("autoplay config saved: clicks=%s patterns=%s",
             list(game.get("clicks", {}).keys()),
             list(game.get("ws_patterns", {}).keys()))
    return {"ok": True}


# ---- capture mode ----
@router.post("/api/autoplay/capture")
async def autoplay_capture(body: dict, request: Request):
    """Mở profile + bật WS sniffer, chờ user chơi thủ công để ghi protocol."""
    from game_sim.auto_flow import AutoFlow

    profile_names = [n.strip() for n in (body.get("profile_names") or []) if n.strip()]
    if not profile_names:
        raise HTTPException(status_code=400, detail="Chưa chọn profile nào")

    import license as lic

    if lic.max_tabs() <= 0:
        raise HTTPException(status_code=403, detail="License chưa kích hoạt hoặc hết hạn")

    old = getattr(request.app.state, "auto_flow", None)
    if old:
        old["flow"].stop()

    saved = _load_game_config()
    game = {**saved, **body.get("game", {}), "adapter": "hitclub", "capture": True}
    if not game.get("url"):
        game["url"] = "https://v.hitclub.latino/?a=hitclub"
    if not game.get("clicks"):
        game["clicks"] = saved.get("clicks", {})
    config = {"game": game, "auto_out": False, "auto_start": False}

    adapter = _build_adapter(request, config)
    run_id = f"cap_{uuid.uuid4().hex[:8]}"
    flow = AutoFlow(run_id, adapter, config)
    task = asyncio.create_task(flow.run(profile_names))
    request.app.state.auto_flow = {"flow": flow, "task": task, "adapter": adapter}
    return {
        "ok": True,
        "run_id": run_id,
        "capture_file": str(adapter.sniffer.capture_file),
        "profiles": profile_names,
    }


# ---- test click ----
@router.post("/api/autoplay/test-click")
async def autoplay_test_click(body: dict, request: Request):
    """Click thử 1 tọa độ trên profile đã mở (để xác định vị trí nút trong canvas)."""
    name = (body.get("profile_name") or "").strip()
    x = int(body.get("x") or 0)
    y = int(body.get("y") or 0)
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if not x or not y:
        raise HTTPException(status_code=400, detail="Thiếu tọa độ x, y")

    adapter = _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    try:
        await page.bring_to_front()
    except Exception:
        pass
    await page.mouse.click(x, y)
    await asyncio.sleep(0.6)
    await adapter.sniffer.drain(page)
    shot = await adapter._screenshot(page, f"test_click_{name}_{x}x{y}")
    return {"ok": True, "clicked": [x, y], "screenshot": shot, "profile": name}


# ---- gửi raw WS / join bàn theo rid (để 2 tài khoản vào CÙNG 1 bàn) ----
def _active_adapter(request):
    """Dùng adapter của capture/autoplay run đang chạy (có sẵn sniffer đã hook
    socket Playwright). Fallback: build mới nếu chưa có run nào."""
    af = getattr(request.app.state, "auto_flow", None)
    if af and af.get("adapter") is not None:
        return af["adapter"]
    return _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})


@router.post("/api/autoplay/send-raw")
async def autoplay_send_raw(body: dict, request: Request):
    """Gửi 1 message WS thô vào profile đã mở (dùng để join bàn theo rid)."""
    name = (body.get("profile_name") or "").strip()
    text = body.get("text")
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if not text:
        raise HTTPException(status_code=400, detail="Thiếu text")
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    ok = await adapter.sniffer.send_raw(page, str(text))
    return {"ok": bool(ok)}


@router.post("/api/autoplay/join-rid")
async def autoplay_join_rid(body: dict, request: Request):
    """Ép 1 profile join CHÍNH XÁC vào bàn có rid (không random như click 'bàn 100').

    Gửi: [6,"Simms","channelPlugin",{"cmd":308,"aid":1,"gid":<gid>,"b":<bet>,
          "Mu":2,"iJ":true,"inc":false,"pwd":"1","rid":<rid>}]
    """
    name = (body.get("profile_name") or "").strip()
    rid = body.get("rid")
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if rid is None:
        raise HTTPException(status_code=400, detail="Thiếu rid")
    gid = int(body.get("gid", 1))
    bet = int(body.get("bet", 100))
    mu = int(body.get("mu", 2))
    payload = {
        "cmd": 308, "aid": 1, "gid": gid, "b": bet, "Mu": mu,
        "iJ": True, "inc": False, "pwd": "1", "rid": int(rid),
    }
    import json as _json
    text = _json.dumps([6, "Simms", "channelPlugin", payload])
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    ok = await adapter.sniffer.send_raw(page, text)
    return {"ok": bool(ok), "sent": text}


# ---- ép 1 profile join CHÍNH XÁC vào bàn rid, dùng template bắt được ----
@router.post("/api/autoplay/join-by-id")
async def autoplay_join_by_id(body: dict, request: Request):
    """Ép 1 profile join đúng bàn rid, dùng template từ capture.

    Ưu tiên: dùng game socket đã bắt (gửi qua send_raw) — chính xác nhất.
    Fallback: kênh WS phụ (join_by_id_side) nếu game socket chưa sẵn sàng.
    KHÔNG reload, KHÔNG logout.

    Body: {profile_name, rid, template?}
      - template: chuỗi bắt từ /api/autoplay/join-capture (có placeholder {room_id}).
        Nếu không truyền, build template mặc định.
    """
    name = (body.get("profile_name") or "").strip()
    rid = body.get("rid")
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if rid is None:
        raise HTTPException(status_code=400, detail="Thiếu rid")
    template = (body.get("template") or "").strip()
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    # thử dùng game socket (captured via reconnect-ws) trước
    result = await adapter.join_by_id(name, rid, template or None)
    if result.get("ok"):
        return result
    # fallback: WS phụ
    log.info("join_by_id (game socket) fail, fallback to side channel")
    result2 = await adapter.join_by_id_side(name, rid, template or None)
    return result2


# ---- chẩn đoán sniffer trên page đang mở ----
@router.get("/api/autoplay/sniffer-status")
async def autoplay_sniffer_status(request: Request):
    """Đọc trực tiếp trên từng page đang mở: hook đã inject chưa, capture có gì."""
    bm = request.app.state.manager
    result = []
    for sid, s in bm.sessions.items():
        page = s.page
        name = (s.account or {}).get("name", sid)
        hooked = False
        count = 0
        url = ""
        if page:
            try:
                hooked = bool(await page.evaluate("() => !!(window.__ws_hooked)"))
            except Exception:
                pass
            try:
                count = int(await page.evaluate("() => (window.__ws_capture || []).length") or 0)
            except Exception:
                pass
            try:
                url = page.url
            except Exception:
                pass
        result.append({"name": name, "hooked": hooked, "capture_count": count, "url": url})
        if page:
            try:
                frames_diag = []
                for f in page.frames:
                    try:
                        diag = await f.evaluate(
                            """() => {
                                const m = window.__ws_map || {};
                                return {
                                    hooked: !!window.__ws_hooked,
                                    mapCount: Object.keys(m).length,
                                    mapUrls: Object.keys(m).slice(0, 5),
                                    lastReady: window.__ws_last ? window.__ws_last.readyState : null
                                };
                            }"""
                        )
                        frames_diag.append({"url": f.url[:80], **diag})
                    except Exception:
                        frames_diag.append({"url": (f.url or "")[:80], "error": True})
                result[-1]["frames_diag"] = frames_diag
            except Exception as e:
                result[-1]["frames_diag"] = {"error": str(e)[:100]}
            try:
                result[-1]["workers"] = len([w for w in page.workers if w])
            except Exception:
                pass
    return {"sessions": result}


# ---- trích accessToken từ page (lưu phiên để dùng client WS độc lập) ----
@router.post("/api/autoplay/session-token")
async def autoplay_session_token(body: dict, request: Request):
    """Đọc accessToken từ page (sessionStorage/localStorage/JS globals).

    Vì game dính captcha khi login, ta lấy token 1 lần (login manual),
    lưu lại để dùng standalone WS client cho automation — không cần re-login.
    """
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    js = """
    () => {
        const found = [];
        const grab = (obj) => {
            try {
                for (let i = 0; i < obj.length; i++) {
                    const k = obj.key(i);
                    const v = obj.getItem(k);
                    if (v && typeof v === 'string' && (v.includes('accessToken') || v.includes('token') || v.includes('1-e') || /^[0-9a-f]{32}$/.test(v) || v.includes('e838bf'))) {
                        found.push({store:'storage', key:k, value:String(v).slice(0,200)});
                    }
                }
            } catch (e) {}
        };
        try { grab(window.sessionStorage); } catch (e) {}
        try { grab(window.localStorage); } catch (e) {}
        try {
            if (document.cookie) found.push({store:'cookie', value: document.cookie.slice(0,300)});
        } catch (e) {}
        // dò global vars chứa token
        try {
            for (const k in window) {
                const v = window[k];
                if (v && typeof v === 'string' && (v.includes('accessToken') || /^1-[0-9a-f]{32}$/.test(v) || v.includes('e838bf'))) {
                    found.push({store:'global', key:k, value:String(v).slice(0,200)});
                }
            }
        } catch (e) {}
        return found;
    }
    """
    try:
        data = await page.evaluate(js)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"evaluate fail: {e}")
    # tìm token dạng 1-<32hex>
    import re as _re
    token = None
    for item in data or []:
        val = str(item.get("value") or "")
        m = _re.search(r"1-[0-9a-f]{32}", val)
        if m:
            token = m.group(0)
            break
    # lưu token MỚI vào token store (login thủ công cũng được tính là login mới)
    if token:
        try:
            from models.config_model import DATA_DIR
            from game_sim.token_store import TokenStore

            TokenStore(DATA_DIR / "game_sim_token.json").save(name, token)
        except Exception:
            pass
    return {"profile": name, "token": token, "found": data or []}


# ---- reload page với hook từ đầu (bắt được WS sau khi login) ----
@router.post("/api/autoplay/reload")
async def autoplay_reload(body: dict, request: Request):
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    adapter = _active_adapter(request)
    page = await adapter._page(name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {name}")
    await adapter.sniffer.inject_playwright(page)
    await adapter.sniffer.inject_init(page)
    await adapter.sniffer.inject_http(page)
    url = adapter.url or "https://v.hitclub.latino/?a=hitclub"
    diag = {}
    try:
        ctx = page.context
        pages = ctx.pages
        diag["pages_in_context"] = len(pages)
        diag["pages"] = []
        for p in pages:
            try:
                diag["pages"].append({"url": p.url[:120], "title": (await p.title())[:60]})
            except Exception:
                pass
    except Exception as e:
        diag["context_err"] = str(e)[:100]
    try:
        # page.reload() = force reload thật (service worker/SPA không chặn),
        # nên add_init_script chạy -> hook WS từ đầu.
        await page.reload(wait_until="domcontentloaded", timeout=60000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.warning("reload goto fail: %s", e)
    await asyncio.sleep(float(adapter.game.get("load_wait", 4)))
    try:
        diag["hooked_after"] = bool(await page.evaluate("() => !!(window.__ws_hooked)"))
    except Exception:
        diag["hooked_after"] = "err"
    return {"ok": True, "reloaded": name, "diag": diag}


# ---- đọc Gold gần nhất của profile từ ws_capture ----
@router.get("/api/autoplay/gold")
async def autoplay_gold(request: Request):
    name = (request.query_params.get("profile_name") or "").strip()
    from models.config_model import DATA_DIR as _DATA
    import re as _re
    cf = _DATA / "game_sim_debug" / "ws_capture.jsonl"
    gold = None
    dn_seen = None
    if cf.exists():
        for line in cf.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"cmd\\":100' not in line and '"cmd\\": 100' not in line and '"cmd":100' not in line:
                continue
            try:
                import json as _json
                d = _json.loads(line)
                arr = _json.loads(d.get("text", ""))
                pl = arr[1] if isinstance(arr, list) and len(arr) > 1 else {}
                dn = (pl.get("dn") or "")
                if name and dn:
                    want = name.replace("nicktestxabai", "nicktestxxabai")
                    if want != dn:
                        continue
                as_ = pl.get("As") or {}
                if isinstance(as_, dict) and as_.get("gold") is not None:
                    gold = as_.get("gold")
                    dn_seen = dn
            except Exception:
                continue
    return {"profile": name, "gold": gold, "dn": dn_seen}


# ---- trích xuất room id + template join từ capture WS (để test nhanh) ----
@router.get("/api/autoplay/join-capture")
async def autoplay_join_capture(request: Request, profile_name: str = ""):
    """Trích xuất nhanh room id + template join cmd=308 từ capture (ws_capture.jsonl).

    Quy trình test:
      1) Mở profile đã login -> gọi /api/autoplay/debug-ws-hook (bật capture + reload)
      2) Thao tác join 1 bàn bằng chuột (game sẽ gửi cmd=308)
      3) Gọi endpoint này (tuỳ chọn ?profile_name=... để drain page trước)
         -> trả về rooms[], last_room_id, join_template (sẵn sàng để SUPPORT join chung bàn).
    """
    from game_sim.ws_sniffer import WsSniffer
    from game_sim.adapters.hitclub import _find_cmd_payload

    save_dir = DATA_DIR / "game_sim_debug"
    sniffer = WsSniffer(save_dir)

    if profile_name:
        try:
            adapter = _active_adapter(request)
            page = await adapter._page(profile_name)
            if page:
                await sniffer.drain(page)
        except Exception:
            pass

    msgs = sniffer.recent(limit=30000)
    rooms = {}
    last_rid = None
    template = None
    for it in msgs:
        try:
            arr = json.loads(it.get("text", ""))
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        idx, p = _find_cmd_payload(arr)
        if not isinstance(p, dict):
            continue
        cmd = p.get("cmd")
        # danh sách bàn: cmd=300 recv -> rs[]
        if cmd == 300 and isinstance(p.get("rs"), list):
            for r in p["rs"]:
                if isinstance(r, dict) and isinstance(r.get("rid"), (int, float)):
                    rid = int(r["rid"])
                    rooms[rid] = {
                        "rid": rid,
                        "rn": r.get("rn"),
                        "uC": r.get("uC"),
                        "b": r.get("b"),
                        "gid": r.get("gid"),
                        "Mu": r.get("Mu"),
                    }
        # room id hiện tại: cmd=305/308 recv -> ri.rid
        if cmd in (305, 308) and isinstance(p.get("ri"), dict):
            r = p["ri"].get("rid")
            if isinstance(r, (int, float)) and r > 0:
                last_rid = int(r)
        # template join: cmd=308 SEND (bản gốc, chưa thay rid)
        if it.get("dir") in ("send", "inject") and cmd == 308:
            raw = dict(p)
            raw.pop("rid", None)
            raw["rid"] = "{room_id}"
            new_arr = list(arr)
            new_arr[idx] = raw
            template = json.dumps(new_arr, ensure_ascii=False)
    return {
        "message_count": len(msgs),
        "rooms": list(rooms.values()),
        "last_room_id": last_rid,
        "join_template": template,
        "has_template": template is not None,
    }


# ---- liệt kê bàn qua WS phụ (KHÔNG reload, không động session login) ----
@router.get("/api/autoplay/list-rooms")
async def autoplay_list_rooms(request: Request, profile_name: str = "", gid: int = 1):
    """Liệt kê các bàn (cmd=300) của profile đã login, dùng WS phụ — không reload."""
    if not profile_name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    adapter = _active_adapter(request)
    page = await adapter._page(profile_name)
    if not page:
        raise HTTPException(status_code=400, detail=f"Không mở được profile {profile_name}")
    result = await adapter.list_rooms_side(profile_name, gid=gid)
    return result


# ---- buộc game mở lại WS (offline->online) để bắt socket thật, KHÔNG reload ----
@router.post("/api/autoplay/reconnect-ws")
async def autoplay_reconnect_ws(body: dict, request: Request):
    """Buộc game mở lại WS bằng cách toggle offline->online.

    Game đang login giữ WS của nó được tạo TRƯỚC khi ta cắm hook, nên không bắt
    được. Toggle offline làm WS rớt; khi online game tự reconnect bằng session của
    nó -> socket mới được wrapper (window.__ws_map/__ws_last) bắt, ta gửi lệnh
    join qua chính socket authenticated đó. KHÔNG reload, KHÔNG logout.
    """
    name = (body.get("profile_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    manager = request.app.state.manager
    session = None
    for s in manager.sessions.values():
        if s.account and s.account.get("name") == name and s.page:
            session = s
            break
    if not session:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy profile {name}")
    page = session.page
    ctx = page.context
    # bảo đảm hook Playwright + wrapper WebSocket live đã active (bắt socket MỚI)
    try:
        from game_sim.ws_sniffer import WsSniffer
        from models.config_model import DATA_DIR as _DATA

        sniffer = WsSniffer(_DATA / "game_sim_debug")
        await sniffer.inject_playwright(page)
        await sniffer.inject_init(page)
    except Exception as e:
        diag_ = {"inject_err": str(e)[:100]}
    try:
        await page.evaluate(
            """() => {
                if (window.__ws_live_hooked) return true;
                window.__ws_live_hooked = true;
                window.__ws_map = window.__ws_map || {};
                const orig = window.__ws_orig || WebSocket;
                window.__ws_orig = orig;
                window.WebSocket = function(url, protocols) {
                    const ws = protocols ? new orig(url, protocols) : new orig(url);
                    try { window.__ws_map[url] = ws; window.__ws_last = ws; } catch(e) {}
                    return ws;
                };
                window.WebSocket.prototype = orig.prototype;
                return true;
            }"""
        )
    except Exception:
        pass
    diag = {}
    try:
        await ctx.setOffline(True)
        diag["offline_set"] = True
    except Exception as e:
        diag["offline_err"] = str(e)[:100]
    await asyncio.sleep(2)
    try:
        await ctx.setOffline(False)
        diag["online_restored"] = True
    except Exception as e:
        diag["online_err"] = str(e)[:100]
    await asyncio.sleep(10)
    try:
        diag["captured_urls"] = await page.evaluate("() => Object.keys(window.__ws_map || {})")
    except Exception as e:
        diag["captured_err"] = str(e)[:100]
    return {"profile": name, "diag": diag}


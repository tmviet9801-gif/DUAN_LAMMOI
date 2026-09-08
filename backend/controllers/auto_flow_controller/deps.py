"""Phụ thuộc dùng chung: đọc config game, dựng adapter, phát toast realtime."""
import json
import logging

from models.config_model import load_accounts

from .constants import AUTOPLAY_CONFIG_FILE

log = logging.getLogger("auto_flow_controller")


def _load_game_config() -> dict:
    try:
        if AUTOPLAY_CONFIG_FILE.exists():
            data = json.loads(AUTOPLAY_CONFIG_FILE.read_text(encoding="utf-8"))
            return data.get("game", {}) or {}
    except Exception:
        pass
    return {}


async def _notify_all(ext_hub, text, type_="info", title="AutoTool"):
    """Kênh báo realtime TỪ SERVER tới MỌI extension đang online (không phụ thuộc
    Extension của Account chính có báo sự kiện hay không). Server luôn biết chính
    xác Account chính đang làm gì -> gửi TOAST (2.5s tự xoá) để Account phụ thấy."""
    if not text:
        return
    if ext_hub is None:
        return
    sockets = getattr(ext_hub, "active_sockets", None)
    if not sockets:
        return
    for p_name in list(sockets.keys()):
        try:
            await ext_hub.send_command(p_name, "TOAST", {
                "title": title,
                "text": text,
                "type": type_,
                "source_profile": "server",
                "duration": 2500,
            })
        except Exception:
            pass


def _build_adapter(request, config):
    from game_sim.adapters.hitclub import HitClubAdapter
    from services.page_pool import PagePool

    bm = getattr(request.app.state, "manager", None)
    if bm is None:
        from services.browser_service import BrowserManager
        from models.config_model import load_config
        bm = BrowserManager(load_config())
        request.app.state.manager = bm
    page_pool = PagePool(bm)
    accounts = load_accounts()
    lookup = {}
    for a in accounts:
        if not a:
            continue
        name = a.get("name")
        if name:
            lookup[name] = a
            lookup[name.replace(" ", "")] = a
            lookup[name.lower()] = a
            lookup[name.replace(" ", "").lower()] = a
        uname = a.get("username")
        if uname:
            lookup[uname] = a
            lookup[uname.lower()] = a
        aid = a.get("id")
        if aid:
            lookup[aid] = a
    return HitClubAdapter(config, account_lookup=lookup, page_pool=page_pool)


# ---- gửi raw WS / join bàn theo rid (để 2 tài khoản vào CÙNG 1 bàn) ----
def _active_adapter(request):
    """Dùng adapter của capture/autoplay run đang chạy (có sẵn sniffer đã hook
    socket Playwright). Fallback: build mới nếu chưa có run nào."""
    af = getattr(request.app.state, "auto_flow", None)
    if af and af.get("adapter") is not None:
        return af["adapter"]
    return _build_adapter(request, {"game": {"adapter": "hitclub", "clicks": {}}})

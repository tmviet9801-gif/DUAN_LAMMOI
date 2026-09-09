"""Ngu canh cua mot luot GOM BAN: tham so, trang, va cac helper dung chung.

Tach khoi matching.py de than vong lap chinh gon lai va de doc. Cac helper o
day chinh la nhung closure truoc kia nam trong ham 1300 dong; gio thanh phuong
thuc cua MatchContext nen truyen di duoc, kiem thu duoc.

`ext_hub` co tinh la PROPERTY chu khong phai gia tri gan mot lan: nut Dung
thay the doi tuong hub tren app.state, doc lai moi lan dung moi thay thay doi.
"""
import json as _json
import logging
import uuid
from pathlib import Path

from core.page_world import eval_page

from .constants import BET_RATIOS, FIXED_TABLE_RIDS
from .lobby import _ensure_in_tldl_lobby_util, _is_in_tldl_lobby_util

log = logging.getLogger("auto_flow_controller")


def resolve_profile_name(p, accounts):
    """Chuan hoa ten profile ve dung account["name"].

    Khop rong (bo dau cach, thuong hoa, theo username/id) vi UI va extension
    goi ten khac nhau, nhung KHONG suy doan theo chu so 1/2 trong ten — dieu do
    tung lam dao chieu anchor/sub.
    """
    p = str(p or "").strip()
    if not p:
        return ""
    matched_name = None
    for a in accounts:
        if not a:
            continue
        candidates = [
            a.get("name") or "",
            (a.get("name") or "").replace(" ", ""),
            (a.get("name") or "").lower(),
            (a.get("name") or "").replace(" ", "").lower(),
            a.get("username") or "",
            (a.get("username") or "").lower(),
            # Ten in-game (dn) va game_username: extension bao ten nay, khong
            # phai username dang nhap. Thieu chung thi resolve tra ve chuoi tho
            # -> adapter._page() khong tim ra session -> profile bi bo qua ca
            # luot chay. (_match_account o account_controller da khop ca hai.)
            a.get("character_name") or "",
            (a.get("character_name") or "").lower(),
            a.get("game_username") or "",
            (a.get("game_username") or "").lower(),
            a.get("id") or "",
        ]
        if p in candidates or p.lower() in candidates or p.replace(" ", "").lower() in candidates:
            matched_name = a.get("name")
            break
    return matched_name or p


def load_extension_scripts():
    """Doc card_logic.js roi content_main.js, DUNG THU TU DO.

    card_logic.js cung cap AutoToolCards (phan ra toi uu, dem bai) ma nhanh xa
    bai cua content_main.js goi toi.
    """
    scripts = []
    try:
        from models.bundled_model import get_extension_dir
        ext_dir = get_extension_dir()
        fallback_dir = Path(__file__).resolve().parent.parent / "extension"
        for fname in ("card_logic.js", "content_main.js"):
            f = Path(ext_dir or "") / fname
            if not f.exists():
                f = fallback_dir / fname
            if f.exists():
                scripts.append((fname, f.read_text(encoding="utf-8")))
    except Exception:
        pass
    return scripts


class MatchContext:
    """State dung chung cua mot luot gom ban."""

    def __init__(self, request, adapter, pages, profiles_input, body):
        self.request = request
        self.adapter = adapter
        self.pages = pages
        self.profiles_input = profiles_input

        self.gid = int(body.get("gid", 1))
        target_bet = int(body.get("target_bet", 100) or 100)
        self.target_mu = int(body.get("mu", 2) or 2)
        self.bet_val = target_bet if target_bet in BET_RATIOS else 100
        # RID co dinh xac minh tu frame cmd=300. Bat buoc gui rid: chi gui b/Mu
        # thi server co the dung lua chon ban con luu trong client -> vao $500.
        self.requested_rid = FIXED_TABLE_RIDS.get(f"{self.bet_val}_{self.target_mu}")

        self.auto_xa = bool(body.get("auto_xa", True))
        self.auto_start_guest_ss = bool(body.get("auto_start_guest_ss", True))
        self.auto_leave_after = bool(body.get("auto_leave_after", True))

        # Moi cap giu token dung rieng theo epoch. Khong reset co toan cuc:
        # reset do tung khien pair thu hai lam pair thu nhat tu dung.
        self.stop_epoch = int(getattr(request.app.state, "gom_ban_stop_epoch", 0))
        self.run_id = f"gom_{uuid.uuid4().hex[:8]}"

    @property
    def ext_hub(self):
        return getattr(self.request.app.state, "ext_hub", None)

    def should_stop(self):
        return int(getattr(self.request.app.state, "gom_ban_stop_epoch", 0)) != self.stop_epoch

    async def screen_size(self, p):
        try:
            sz = await eval_page(p, "({w: window.innerWidth, h: window.innerHeight})")
            return int(sz.get("w") or 784), int(sz.get("h") or 505)
        except Exception:
            return 784, 505

    async def in_lobby(self, p):
        return await _is_in_tldl_lobby_util(p)

    async def ensure_lobby(self, p, name="Profile"):
        return await _ensure_in_tldl_lobby_util(p, name=name, target_mu=self.target_mu)

    async def set_hud(self, p, msg):
        if not p:
            return
        try:
            await eval_page(p, f"window.__autotool_hud_status = {_json.dumps(msg)};")
        except Exception:
            pass

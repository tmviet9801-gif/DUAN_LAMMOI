"""Controller: Auto Flow (tìm nhau + xả bài).

Trước đây là một file 2959 dòng. Nay tách theo vai trò; `router` gộp lại
các sub-router THEO ĐÚNG THỨ TỰ đăng ký cũ để không đổi thứ tự match route.
"""
from fastapi import APIRouter

from .constants import AUTOPLAY_CONFIG_FILE, BET_RATIOS, FIXED_TABLE_RIDS
from .deps import _active_adapter, _build_adapter, _load_game_config, _notify_all
from .lobby import (
    _clear_hunt_state,
    _do_leave_room,
    _ensure_in_tldl_lobby_util,
    _get_screen_size_util,
    _is_in_tldl_lobby_util,
    _match_template_cv,
)
from . import matching, routes_basic, routes_debug

router = APIRouter()
router.include_router(routes_basic.router)
router.include_router(matching.router)
router.include_router(routes_debug.router)

__all__ = [
    "router",
    "AUTOPLAY_CONFIG_FILE",
    "BET_RATIOS",
    "FIXED_TABLE_RIDS",
    "_active_adapter",
    "_build_adapter",
    "_clear_hunt_state",
    "_do_leave_room",
    "_ensure_in_tldl_lobby_util",
    "_get_screen_size_util",
    "_is_in_tldl_lobby_util",
    "_load_game_config",
    "_match_template_cv",
    "_notify_all",
    "matching",
    "routes_basic",
    "routes_debug",
]

"""Controller: cấu hình lưới, antidetect (locale)."""
import logging

from fastapi import APIRouter, Request

from models.config_model import load_config, save_config

log = logging.getLogger("config_controller")
router = APIRouter()


@router.get("/api/config")
async def get_config():
    return load_config()


@router.post("/api/config")
async def set_config(cfg: dict, request: Request):
    manager = request.app.state.manager
    current = load_config()
    if "grid" in cfg:
        current["grid"] = {**current["grid"], **cfg["grid"]}
    if "window" in cfg:
        current["window"] = {**current["window"], **cfg["window"]}
    if "anti_detect" in cfg:
        current["anti_detect"] = {**current["anti_detect"], **cfg["anti_detect"]}
    if "open_direction" in cfg:
        current["open_direction"] = cfg["open_direction"]
    if "default_count" in cfg:
        current["default_count"] = int(cfg["default_count"])
    if "auto_layout" in cfg:
        current["auto_layout"] = bool(cfg["auto_layout"])
    if "mute_all_sites" in cfg:
        current["mute_all_sites"] = bool(cfg["mute_all_sites"])
    if "default_url" in cfg:
        current["default_url"] = (cfg["default_url"] or "").strip()
    save_config(current)
    manager.config = current
    if current.get("auto_layout", True):
        await manager.apply_layout()
    # Áp dụng mute ngay lập tức cho các tab đang mở khi user đổi cấu hình.
    await manager.sync_mute()
    return current


@router.get("/api/antidetect")
async def get_antidetect_options():
    return {
        "locale": [
            "random",
            "en-US",
            "vi-VN",
            "zh-CN",
            "ja-JP",
            "ko-KR",
            "th-TH",
            "id-ID",
            "en-GB",
            "de-DE",
            "fr-FR",
        ],
    }
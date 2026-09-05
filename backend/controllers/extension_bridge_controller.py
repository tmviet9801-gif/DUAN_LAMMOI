"""Extension Bridge Controller — Endpoint WebSocket và REST API cho Chrome Extension Bridge V3."""
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

log = logging.getLogger("extension_bridge")
router = APIRouter()


@router.websocket("/ws/bridge")
async def websocket_bridge(
    websocket: WebSocket,
    profile: Optional[str] = Query(None),
):
    """Kênh kết nối WebSocket 2 chiều thời gian thực giữa Chrome Extension và Backend.

    Mỗi Chrome Profile khi khởi chạy sẽ tự động kết nối về:
    ws://127.0.0.1:8000/ws/bridge?profile=<Tên_Profile>
    """
    await websocket.accept()

    ext_hub = getattr(websocket.app.state, "ext_hub", None)
    if not ext_hub:
        await websocket.close(code=1011, reason="ExtensionHub not initialized")
        return

    profile_name = (profile or "").strip()

    # Nếu query param chưa có tên profile, chờ gói tin INIT đầu tiên từ Extension
    if not profile_name:
        try:
            init_text = await websocket.receive_text()
            init_data = json.loads(init_text)
            profile_name = (init_data.get("profile_name") or init_data.get("profile") or "").strip()
        except Exception:
            pass

    if not profile_name:
        profile_name = f"Profile_Anonymous_{id(websocket)}"

    await ext_hub.register(profile_name, websocket)

    try:
        # Gửi lời chào xác nhận kết nối thành công về cho Extension
        await websocket.send_text(json.dumps({
            "action": "WELCOME",
            "version": "3.0.0",
            "profile_name": profile_name,
            "message": "Connected to AutoTool Extension Hub V3",
        }))

        # Vòng lặp nhận dữ liệu liên tục từ Extension
        while True:
            raw = await websocket.receive_text()
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception:
                data = {"raw": raw}

            # Phản hồi ping keep-alive tức thì để giữ socket luôn hoạt động
            if data.get("action") == "PING" or data.get("type") == "PING":
                await websocket.send_text(json.dumps({"action": "PONG", "ts": data.get("ts")}))
                continue

            # Đẩy vào hub xử lý gói tin game
            ext_hub.handle_message(profile_name, data)

    except WebSocketDisconnect:
        log.info("websocket_bridge: Profile '%s' đã ngắt kết nối bình thường.", profile_name)
    except Exception as e:
        log.warning("websocket_bridge: Lỗi kết nối cho profile '%s': %s", profile_name, e)
    finally:
        await ext_hub.unregister(profile_name, websocket)


@router.get("/api/bridge/status")
async def get_bridge_status(request: Request):
    """Lấy trạng thái toàn bộ kết nối Extension Hub hiện tại."""
    ext_hub = getattr(request.app.state, "ext_hub", None)
    if not ext_hub:
        return {"ok": False, "error": "ExtensionHub chưa được khởi tạo"}
    return {"ok": True, **ext_hub.get_status()}


@router.post("/api/bridge/command")
async def post_bridge_command(body: dict, request: Request):
    """Gửi lệnh tức thì xuống tab game của một Profile qua Extension Bridge."""
    profile_name = (body.get("profile_name") or "").strip()
    action = (body.get("action") or "").strip()
    data = body.get("data") or {}

    if not profile_name:
        raise HTTPException(status_code=400, detail="Thiếu profile_name")
    if not action:
        raise HTTPException(status_code=400, detail="Thiếu action")

    ext_hub = getattr(request.app.state, "ext_hub", None)
    if not ext_hub:
        raise HTTPException(status_code=500, detail="ExtensionHub chưa được khởi tạo")

    ok = await ext_hub.send_command(profile_name, action, data)
    return {
        "ok": ok,
        "profile_name": profile_name,
        "action": action,
        "message": "Lệnh đã được gửi xuống tab game qua Extension" if ok else "Profile chưa kết nối Extension",
    }

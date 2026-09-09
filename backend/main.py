"""Entry point FastAPI: tạo app, lifespan khởi tạo manager/hub, mount routers."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys

# Ép buộc gắn vào desktop vật lý 'Default' của người dùng (màn hình hiển thị thật)
try:
    import ctypes
    user32 = ctypes.windll.user32
    h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if h_desk:
        user32.SetThreadDesktop(h_desk)
except Exception:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.events import EventHub, UIEventEmitter
from core.logging_setup import setup_logging
from models.config_model import load_config
from services.browser_service import BrowserManager
from services.extension_hub import ExtensionHubManager

from controllers import (
    account_controller,
    auto_flow_controller,
    browser_controller,
    config_controller,
    extension_bridge_controller,
    game_sim_controller,
    info_controller,
    license_controller,
    proxy_controller,
    ws_controller,
)

# Đảm bảo import được khi chạy từ mọi cwd
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

log = setup_logging()


async def _browser_watchdog(manager: "BrowserManager"):
    """Định kỳ: prune session chết + auto-save localStorage + đồng bộ mute."""
    i = 0
    while True:
        await asyncio.sleep(5)
        i += 1
        try:
            manager.prune_dead_sessions()
            await manager.sync_mute()
            if i % 2 == 0:  # mỗi ~10s
                await manager.save_open_sessions_storage()
        except Exception:
            pass


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub = EventHub()
        emitter = UIEventEmitter(hub=hub)
        manager = BrowserManager(load_config(), on_event=emitter.publish)
        ext_hub = ExtensionHubManager(on_event=emitter.publish)
        from game_sim.manager import GameSimManager

        app.state.hub = hub
        app.state.manager = manager
        app.state.events = emitter
        app.state.ext_hub = ext_hub
        gs = GameSimManager(browser_manager=manager)
        gs.set_event_sink(emitter.publish)
        app.state.game_sim = gs

        # Migration: bật lưu session (save_session) cho mọi profile cũ + tạo
        # profile_dir nếu thiếu, để login được giữ lại khi mở lại.
        from models.config_model import (
            ensure_accounts_save_session,
            ensure_profile_dirs_current,
            load_accounts,
            save_accounts,
        )

        try:
            migrated_accounts, n = ensure_accounts_save_session(load_accounts())
            # Dự án đổi chỗ (đổi tên/di chuyển thư mục) làm profile_dir tuyệt đối
            # chết theo -> Chromium tạo profile rỗng, mất session đăng nhập.
            migrated_accounts, n_dir = ensure_profile_dirs_current(migrated_accounts)
            if n_dir:
                log.warning("đã nắn %d profile_dir về thư mục profiles hiện tại", n_dir)
            if n or n_dir:
                save_accounts(migrated_accounts)
                log.info("migrated %d accounts (save_session) + %d profile_dir", n, n_dir)
        except Exception:
            log.exception("migrate accounts save_session failed")

        # Gộp kho token về khoá `account.id`. Kho từng tích tụ 9 khoá cho 5
        # account: `bulk_names` sinh tên liền ("Account01"), người dùng đổi tên
        # thành "Account 01" mà khoá cũ không di trú theo, và có đường ghi dùng
        # cả tên đăng nhập làm khoá. Migration idempotent, giữ nguyên khoá nhập
        # nhằng/không chủ, và chỉ sao lưu khi thật sự có gì để gộp.
        try:
            from game_sim.token_store import TokenStore
            from models.config_model import DATA_DIR

            bc = TokenStore(DATA_DIR / "game_sim_token.json").migrate(
                load_accounts(),
                backup_path=DATA_DIR / "game_sim_token.pre-migrate.json")
            if bc.get("gop"):
                log.info("kho token: gộp %d khoá -> %d (sao lưu: %s)",
                         bc["truoc"], bc["sau"], bc.get("backup"))
            for x in bc.get("giu_nhap_nhang", []):
                log.warning("kho token: giữ nguyên khoá nhập nhằng — %s", x)
        except Exception:
            log.exception("migrate token store failed")

        # Dọn process chrome mồ côi để lại từ lần chạy trước (restart/kill cứng).
        # Phải chạy TRƯỚC khi mở trình duyệt mới để không tự kill chính mình.
        from services.browser_service import reap_orphan_chrome

        try:
            reap_orphan_chrome()
        except Exception:
            log.exception("reap orphan chrome failed")

        watchdog = asyncio.create_task(_browser_watchdog(manager))
        log.info("Backend ready (manager + hub + game_sim + ext_hub v3 initialized)")
        try:
            yield
        finally:
            watchdog.cancel()
            # đóng graceful: flush cookie xuống profile_dir để login được giữ lại
            try:
                await manager.close_all()
                log.info("All browser sessions closed gracefully")
            except Exception:
                log.exception("graceful shutdown failed")

    app = FastAPI(title="Tab Manager", lifespan=lifespan)
    app.state.ext_hub = ExtensionHubManager()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
        allow_private_network=True,
    )

    app.include_router(info_controller.router)
    app.include_router(config_controller.router)
    app.include_router(game_sim_controller.router)
    app.include_router(account_controller.router)
    app.include_router(browser_controller.router)
    app.include_router(auto_flow_controller.router)
    app.include_router(extension_bridge_controller.router)
    app.include_router(proxy_controller.router)
    app.include_router(license_controller.router)
    app.include_router(ws_controller.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=17832, log_level="info")

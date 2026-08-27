"""Entry point FastAPI: tạo app, lifespan khởi tạo manager/hub, mount routers."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.events import EventHub, UIEventEmitter
from core.logging_setup import setup_logging
from models.config_model import load_config
from services.browser_service import BrowserManager

from controllers import (
    account_controller,
    auto_flow_controller,
    browser_controller,
    config_controller,
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
    """Định kỳ: prune session chết + auto-save localStorage (giữ login mới nhất)."""
    i = 0
    while True:
        await asyncio.sleep(5)
        i += 1
        try:
            manager.prune_dead_sessions()
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
        from game_sim.manager import GameSimManager

        app.state.hub = hub
        app.state.manager = manager
        app.state.events = emitter
        game_sim = GameSimManager(browser_manager=manager)
        game_sim.set_event_sink(lambda ev: emitter.publish(ev))
        app.state.game_sim = game_sim

        # Dọn process camoufox mồ côi để lại từ lần chạy trước (restart/kill cứng).
        # Phải chạy TRƯỚC khi mở trình duyệt mới để không tự kill chính mình.
        from services.browser_service import reap_orphan_camoufox

        try:
            reap_orphan_camoufox()
        except Exception:
            log.exception("reap orphan camoufox failed")

        watchdog = asyncio.create_task(_browser_watchdog(manager))
        log.info("Backend ready (manager + hub + game_sim initialized)")
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(info_controller.router)
    app.include_router(config_controller.router)
    app.include_router(account_controller.router)
    app.include_router(browser_controller.router)
    app.include_router(game_sim_controller.router)
    app.include_router(auto_flow_controller.router)
    app.include_router(proxy_controller.router)
    app.include_router(license_controller.router)
    app.include_router(ws_controller.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

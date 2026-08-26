"""Entry point FastAPI: tạo app, lifespan khởi tạo manager/hub, mount routers."""
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
        log.info("Backend ready (manager + hub + game_sim initialized)")
        yield
        log.info("Backend shutdown")

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

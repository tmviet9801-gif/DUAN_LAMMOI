import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from models import config_model as config


@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    """Cô lập toàn bộ dữ liệu (data dir, accounts, config) vào thư mục tạm."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", data_dir / "config.json")
    monkeypatch.setattr(config, "ACCOUNTS_FILE", data_dir / "accounts.json")
    monkeypatch.setattr(config, "PROFILES_DIR", config.get_profiles_dir())
    return config


@pytest.fixture()
def client(tmp_config):
    """TestClient của FastAPI app, dùng data dir tạm."""
    import main as main_module

    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as c:
        yield c
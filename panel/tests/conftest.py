from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hermes_panel.auth import hash_password
from hermes_panel.config import Settings
from hermes_panel.deps import get_rate_limiter, get_settings_dep
from hermes_panel.main import create_app

PASSWORD = "matkhau-test"
# Cổng sidecar cố tình không dùng để test "sidecar không chạy" luôn tất định.
UNUSED_SIDECAR_PORT = 39999


@pytest.fixture
def password() -> str:
    return PASSWORD


@pytest.fixture
def settings(tmp_path) -> Settings:
    home = tmp_path / "hermes"
    home.mkdir()
    env_file = tmp_path / "opt-hermes.env"
    env_file.write_text(
        f"HERMES_HOME={home}\nZALO_PERSONAL_SIDECAR_PORT={UNUSED_SIDECAR_PORT}\n",
        encoding="utf-8",
    )
    return Settings(
        env_file=env_file,
        hermes_home=home,
        hermes_bin=tmp_path / "bin" / "hermes",
        zalo_plugin_dir=home / "plugins" / "zalo-personal",
        panel_port=8088,
        dashboard_port=9119,
        chat_url="",
        admin_user="admin",
        password_hash=hash_password(PASSWORD),
        session_secret="s" * 32,
    )


@pytest.fixture
def client(settings):
    app = create_app()
    app.dependency_overrides[get_settings_dep] = lambda: settings
    get_rate_limiter.cache_clear()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client):
    resp = client.post("/api/login", json={"username": "admin", "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return client

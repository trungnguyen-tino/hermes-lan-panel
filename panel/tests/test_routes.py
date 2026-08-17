from __future__ import annotations

import pytest

from hermes_panel.envfile import read_env
from hermes_panel.hermes_config import CODEX_DEFAULT_MODEL, CODEX_PROVIDER, get_model

PROTECTED = [
    "/api/me",
    "/api/status",
    "/api/info",
    "/api/model",
    "/api/providers",
    "/api/codex/status",
    "/api/zalo/status",
]


@pytest.fixture
def no_restart(monkeypatch):
    """Chặn systemctl thật trong test — chỉ đếm số lần gọi."""
    calls: list[str] = []

    async def fake_restart(service, allowed):
        calls.append(service)

    monkeypatch.setattr("hermes_panel.routes.model.restart", fake_restart)
    monkeypatch.setattr("hermes_panel.routes.codex.restart", fake_restart)
    return calls


def test_health_is_public(client):
    assert client.get("/health").json()["ok"] is True


def test_index_serves_gui(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Hermes Panel" in resp.text
    assert resp.headers["cache-control"] == "no-cache"


def test_static_assets_are_revalidated(client):
    """Sau khi nâng cấp panel, trình duyệt không được dùng JS/CSS cũ trong cache."""
    for asset in ("/static/app.js", "/static/features.js", "/static/style.css"):
        resp = client.get(asset)
        assert resp.status_code == 200, asset
        assert resp.headers["cache-control"] == "no-cache", asset


@pytest.mark.parametrize("path", PROTECTED)
def test_endpoints_require_session(client, path):
    resp = client.get(path)
    assert resp.status_code == 401
    assert resp.json()["ok"] is False


def test_login_rejects_wrong_password(client):
    resp = client.post("/api/login", json={"username": "admin", "password": "sai"})
    assert resp.status_code == 401


def test_login_rate_limited_after_10_failures(client, password):
    for _ in range(10):
        client.post("/api/login", json={"username": "admin", "password": "sai"})
    resp = client.post("/api/login", json={"username": "admin", "password": password})
    assert resp.status_code == 429


def test_rate_limit_not_bypassed_by_forged_forwarded_for(client, password):
    """Đổi X-Forwarded-For mỗi lần thử vẫn không thoát được giới hạn."""
    for i in range(10):
        client.post(
            "/api/login",
            json={"username": "admin", "password": "sai"},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
    resp = client.post(
        "/api/login",
        json={"username": "admin", "password": password},
        headers={"X-Forwarded-For": "10.0.0.250"},
    )
    assert resp.status_code == 429


def test_login_then_me_then_logout(client, password):
    assert client.post("/api/login", json={"username": "admin", "password": password}).status_code == 200
    assert client.get("/api/me").json()["data"]["username"] == "admin"
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401


def test_status_lists_three_services(auth_client):
    data = auth_client.get("/api/status").json()["data"]
    names = [svc["name"] for svc in data["services"]]
    assert names == ["hermes-gateway", "hermes-dashboard", "hermes-panel"]
    # Panel không được tự khởi động lại chính nó từ GUI.
    assert [svc["controllable"] for svc in data["services"]] == [True, True, False]


def test_service_action_rejects_panel_and_unknown(auth_client):
    assert auth_client.post("/api/services/hermes-panel/restart").status_code == 400
    assert auth_client.post("/api/services/nginx/restart").status_code == 400


def test_service_action_restarts_gateway(auth_client, monkeypatch):
    called: list[tuple[str, str]] = []

    async def fake_control(service, action, allowed):
        called.append((service, action))

    monkeypatch.setattr("hermes_panel.routes.system.control", fake_control)
    resp = auth_client.post("/api/services/hermes-gateway/restart")
    assert resp.status_code == 200
    assert called == [("hermes-gateway", "restart")]


def test_logs_rejects_service_outside_allowlist(auth_client):
    assert auth_client.get("/api/logs?service=sshd").status_code == 400


def test_logs_returns_lines(auth_client, monkeypatch):
    async def fake_journal(service, allowed, lines):
        return "dòng 1\ndòng 2"

    monkeypatch.setattr("hermes_panel.routes.system.journal", fake_journal)
    data = auth_client.get("/api/logs?service=hermes-gateway&lines=100").json()["data"]
    assert data["lines"] == ["dòng 1", "dòng 2"]


def test_providers_include_codex_and_current_model(auth_client, settings):
    data = auth_client.get("/api/providers").json()["data"]
    ids = [p["id"] for p in data["providers"]]
    assert CODEX_PROVIDER in ids and "deepseek" in ids
    assert data["current"] == {"provider": "", "model": ""}


def test_update_model_writes_config_and_restarts(auth_client, settings, no_restart):
    resp = auth_client.put("/api/model", json={"provider": "deepseek", "model": "deepseek-chat"})
    assert resp.json()["data"] == {"provider": "deepseek", "model": "deepseek-chat"}
    assert get_model(settings.hermes_home) == {"provider": "deepseek", "model": "deepseek-chat"}
    assert no_restart == ["hermes-gateway"]


def test_update_model_clamps_codex_slug(auth_client, settings, no_restart):
    resp = auth_client.put("/api/model", json={"provider": "codex", "model": "gpt-5.1-codex-max"})
    assert resp.json()["data"] == {"provider": CODEX_PROVIDER, "model": CODEX_DEFAULT_MODEL}


def test_api_key_saved_to_both_env_stores(auth_client, settings, no_restart):
    resp = auth_client.put("/api/api-key", json={"provider": "deepseek", "api_key": "sk-test-1234"})
    assert resp.json()["data"]["key"] == "DEEPSEEK_API_KEY"
    assert read_env(settings.env_file)["DEEPSEEK_API_KEY"] == "sk-test-1234"
    assert read_env(settings.hermes_env_file)["DEEPSEEK_API_KEY"] == "sk-test-1234"

    listed = auth_client.get("/api/providers").json()["data"]["providers"]
    deepseek = next(p for p in listed if p["id"] == "deepseek")
    assert deepseek["key_set"] is True
    assert deepseek["key_masked"] == "****1234"  # không lộ key đầy đủ


def test_api_key_deleted_from_both_env_stores(auth_client, settings, no_restart):
    auth_client.put("/api/api-key", json={"provider": "deepseek", "api_key": "sk-test-1234"})
    resp = auth_client.request("DELETE", "/api/api-key?provider=deepseek")
    assert resp.json()["data"]["removed"] is True
    assert "DEEPSEEK_API_KEY" not in read_env(settings.env_file)
    assert "DEEPSEEK_API_KEY" not in read_env(settings.hermes_env_file)


def test_codex_status_disconnected_without_token(auth_client):
    assert auth_client.get("/api/codex/status").json()["data"]["status"] == "disconnected"


def test_zalo_status_reports_sidecar_down(auth_client):
    data = auth_client.get("/api/zalo/status").json()["data"]
    assert data == {
        "status": "disconnected",
        "bot_uid": None,
        "name": None,
        "sidecar": False,
        "owner_set": False,
    }


def test_zalo_set_owner_requires_phone_or_uid(auth_client):
    assert auth_client.post("/api/zalo/set-owner", json={}).status_code == 400


def test_zalo_set_owner_by_uid_persists_and_hands_over(auth_client, settings, monkeypatch):
    handovers: list[str] = []

    async def fake_handover(_settings):
        handovers.append("done")

    monkeypatch.setattr("hermes_panel.routes.zalo._handover", fake_handover)
    resp = auth_client.post("/api/zalo/set-owner", json={"uid": "12345"})
    assert resp.json()["data"] == {"owner_uid": "12345", "owner_set": True}
    assert read_env(settings.env_file)["ZALO_PERSONAL_OWNER_UID"] == "12345"
    assert read_env(settings.hermes_env_file)["ZALO_PERSONAL_OWNER_UID"] == "12345"
    assert handovers == ["done"]
    assert auth_client.get("/api/zalo/owner").json()["data"]["owner_set"] is True


def test_zalo_status_revives_sidecar_when_a_login_is_saved(auth_client, settings, monkeypatch, tmp_path):
    """Panel/gateway restart giết sidecar; phiên vẫn còn thì phải bật lại, không bắt quét QR lại."""
    session_dir = tmp_path / "zalo-session"
    session_dir.mkdir()
    (session_dir / "session.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("hermes_panel.routes.zalo._session_dir", lambda _s: session_dir)
    monkeypatch.setattr("hermes_panel.routes.zalo._last_respawn", 0.0)

    tried: list[str] = []

    async def fake_ensure(_settings):
        tried.append("spawn")
        return False  # không lên được → vẫn báo disconnected, nhưng đã thử

    monkeypatch.setattr("hermes_panel.routes.zalo._ensure_sidecar", fake_ensure)
    data = auth_client.get("/api/zalo/status").json()["data"]
    assert tried == ["spawn"]
    assert data["status"] == "disconnected"


def test_zalo_status_does_not_spawn_without_a_saved_login(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr("hermes_panel.routes.zalo._session_dir", lambda _s: tmp_path / "trống")
    monkeypatch.setattr("hermes_panel.routes.zalo._last_respawn", 0.0)

    async def fail(_settings):
        raise AssertionError("không được spawn khi chưa từng đăng nhập")

    monkeypatch.setattr("hermes_panel.routes.zalo._ensure_sidecar", fail)
    assert auth_client.get("/api/zalo/status").json()["data"]["sidecar"] is False

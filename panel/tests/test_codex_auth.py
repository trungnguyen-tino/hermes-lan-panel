from __future__ import annotations

import json

from hermes_panel.codex_auth import (
    clear_codex,
    contains_codex_entry,
    has_codex_token,
    import_auth,
    sync_active_provider,
)
from hermes_panel.hermes_config import CODEX_PROVIDER


def _write(home, data):
    (home / "auth.json").write_text(json.dumps(data), encoding="utf-8")


def test_has_codex_token_missing_or_broken(tmp_path):
    assert has_codex_token(tmp_path) is False
    (tmp_path / "auth.json").write_text("không-phải-json", encoding="utf-8")
    assert has_codex_token(tmp_path) is False


def test_has_codex_token_across_auth_json_shapes(tmp_path):
    _write(tmp_path, {"codex": {"token": "x"}})
    assert has_codex_token(tmp_path) is True

    _write(tmp_path, {"providers": {"openai-codex": {"token": "x"}}})
    assert has_codex_token(tmp_path) is True

    _write(tmp_path, {"version": 1, "credential_pool": {"openai-codex": [{"t": 1}]}})
    assert has_codex_token(tmp_path) is True


def test_empty_credential_pool_is_not_a_token(tmp_path):
    _write(tmp_path, {"credential_pool": {"openai-codex": []}})
    assert has_codex_token(tmp_path) is False


def test_sync_active_provider_sets_codex_when_token_present(tmp_path):
    _write(tmp_path, {"credential_pool": {"openai-codex": [{"t": 1}]}, "active_provider": None})
    sync_active_provider(tmp_path, CODEX_PROVIDER)
    data = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))
    assert data["active_provider"] == CODEX_PROVIDER


def test_sync_active_provider_clears_codex_for_api_key_provider(tmp_path):
    _write(tmp_path, {"credential_pool": {"openai-codex": [{"t": 1}]}, "active_provider": "openai-codex"})
    sync_active_provider(tmp_path, "deepseek")
    data = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))
    assert data["active_provider"] is None
    # Thông tin đăng nhập vẫn còn — chọn lại ChatGPT không phải OAuth lần nữa.
    assert data["credential_pool"]["openai-codex"]


def test_sync_active_provider_noop_without_auth_file(tmp_path):
    sync_active_provider(tmp_path, CODEX_PROVIDER)
    assert not (tmp_path / "auth.json").exists()


def test_clear_codex_removes_every_shape(tmp_path):
    _write(tmp_path, {
        "codex": {"t": 1},
        "providers": {"openai-codex": {"t": 1}, "deepseek": {"t": 2}},
        "credential_pool": {"codex-oauth": [{"t": 1}]},
        "active_provider": "openai-codex",
    })
    clear_codex(tmp_path)
    data = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))
    assert has_codex_token(tmp_path) is False
    assert data["providers"] == {"deepseek": {"t": 2}}
    assert data["active_provider"] is None


def test_contains_codex_entry():
    assert contains_codex_entry({"credential_pool": {"openai-codex": [1]}}) is True
    assert contains_codex_entry({"providers": {"deepseek": {}}}) is False
    assert contains_codex_entry({}) is False


def test_import_auth_writes_private_file(tmp_path):
    import_auth(tmp_path, {"credential_pool": {"openai-codex": [{"t": 1}]}})
    assert has_codex_token(tmp_path) is True
    assert oct((tmp_path / "auth.json").stat().st_mode)[-3:] == "600"

from __future__ import annotations

import yaml

from hermes_panel.hermes_config import (
    CODEX_DEFAULT_MODEL,
    CODEX_PROVIDER,
    enable_zalo,
    get_model,
    read_config,
    resolve_codex_model,
    set_model,
    unset_codex_model,
    write_config,
    zalo_plugin_key,
)


def test_read_config_on_missing_or_broken_file(tmp_path):
    assert read_config(tmp_path) == {}
    (tmp_path / "config.yaml").write_text("::: không phải yaml :::", encoding="utf-8")
    assert read_config(tmp_path) == {}


def test_resolve_codex_model_clamps_unknown_slugs():
    assert resolve_codex_model("gpt-5.5") == "gpt-5.5"
    assert resolve_codex_model("gpt-5.1-codex-max") == CODEX_DEFAULT_MODEL
    assert resolve_codex_model("") == CODEX_DEFAULT_MODEL


def test_set_model_normalises_codex_alias_and_model(tmp_path):
    result = set_model(tmp_path, "codex", "model-đã-chết")
    assert result == {"provider": CODEX_PROVIDER, "model": CODEX_DEFAULT_MODEL}
    assert get_model(tmp_path) == {"provider": CODEX_PROVIDER, "model": CODEX_DEFAULT_MODEL}


def test_set_model_keeps_other_config_keys(tmp_path):
    write_config(tmp_path, {"cron": {"wrap_response": False}, "model": {"default": "cũ"}})
    set_model(tmp_path, "deepseek", "deepseek-chat")
    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["cron"] == {"wrap_response": False}
    assert data["model"] == {"default": "deepseek-chat", "provider": "deepseek"}


def test_set_model_without_model_keeps_existing_default(tmp_path):
    set_model(tmp_path, "deepseek", "deepseek-chat")
    set_model(tmp_path, "deepseek", "")
    assert get_model(tmp_path)["model"] == "deepseek-chat"


def test_unset_codex_model_drops_codex_only_slug(tmp_path):
    set_model(tmp_path, CODEX_PROVIDER, "gpt-5.5")
    unset_codex_model(tmp_path, "deepseek")
    assert get_model(tmp_path) == {"provider": "deepseek", "model": ""}


def test_unset_codex_model_is_noop_for_other_providers(tmp_path):
    set_model(tmp_path, "deepseek", "deepseek-chat")
    unset_codex_model(tmp_path, "openai")
    assert get_model(tmp_path) == {"provider": "deepseek", "model": "deepseek-chat"}


def test_zalo_plugin_key_reads_manifest(tmp_path):
    plugin_dir = tmp_path / "zalo-personal"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text("name: zalo-personal-platform\nversion: 1\n", encoding="utf-8")
    assert zalo_plugin_key(plugin_dir) == "zalo-personal-platform"
    assert zalo_plugin_key(tmp_path / "không-có") == "zalo-personal-platform"


def test_enable_zalo_sets_plugin_and_platform(tmp_path):
    plugin_dir = tmp_path / "plugins" / "zalo-personal"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text("name: zalo-personal-platform\n", encoding="utf-8")

    enable_zalo(tmp_path, plugin_dir)
    enable_zalo(tmp_path, plugin_dir)  # idempotent

    data = read_config(tmp_path)
    assert data["plugins"]["enabled"] == ["zalo-personal-platform"]
    assert data["platforms"]["zalo-personal"]["enabled"] is True

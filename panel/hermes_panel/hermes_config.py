"""Read/write helpers for Hermes' own config.yaml ($HERMES_HOME/config.yaml)."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CODEX_PROVIDER = "openai-codex"
# "codex" was the legacy alias — recognise it when reading, always write the new id.
CODEX_ALIASES = ("codex", "openai-codex")
# Codex with a ChatGPT account only accepts slugs from its own catalog; an empty
# model.default additionally crashes every cron job ("'model' must be a non-empty
# string"), so we always pin a known-good default.
CODEX_DEFAULT_MODEL = "gpt-5.5"
CODEX_SUPPORTED_MODELS = {
    "gpt-5.5", "gpt-5.5-pro", "gpt-5.6-sol", "gpt-5.6-sol-pro", "gpt-5.6-terra",
    "gpt-5.6-terra-pro", "gpt-5.6-luna", "gpt-5.6-luna-pro", "gpt-5.4",
    "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5-mini", "gpt-5.3-codex",
    "gpt-4.1", "gpt-4o", "gpt-4o-mini",
}

ZALO_PLATFORM_ID = "zalo-personal"
ZALO_PLUGIN_FALLBACK_KEY = "zalo-personal-platform"


def config_path(home: Path) -> Path:
    return home / "config.yaml"


def read_config(home: Path) -> dict:
    path = config_path(home)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Không đọc được %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def write_config(home: Path, data: dict) -> None:
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def resolve_codex_model(requested: str) -> str:
    """Clamp a requested Codex model to the supported catalog."""
    req = (requested or "").strip()
    return req if req in CODEX_SUPPORTED_MODELS else CODEX_DEFAULT_MODEL


def get_model(home: Path) -> dict:
    model = read_config(home).get("model")
    if not isinstance(model, dict):
        return {"provider": "", "model": ""}
    return {
        "provider": str(model.get("provider") or ""),
        "model": str(model.get("default") or ""),
    }


def set_model(home: Path, provider: str, model: str) -> dict:
    """Write model.provider + model.default. Codex models are clamped."""
    is_codex = provider in CODEX_ALIASES
    provider = CODEX_PROVIDER if is_codex else provider
    model = resolve_codex_model(model) if is_codex else (model or "").strip()

    data = read_config(home)
    entry = data.get("model")
    if not isinstance(entry, dict):
        entry = {}
    entry["provider"] = provider
    if model:
        entry["default"] = model
    data["model"] = entry
    write_config(home, data)
    return {"provider": provider, "model": model}


def unset_codex_model(home: Path, to_provider: str = "") -> None:
    """Point config.yaml away from Codex so another provider can take over."""
    data = read_config(home)
    entry = data.get("model")
    if not isinstance(entry, dict) or entry.get("provider") not in CODEX_ALIASES:
        return
    if to_provider:
        entry["provider"] = to_provider
    else:
        entry.pop("provider", None)
    # Never let the next provider inherit a Codex-only slug.
    if entry.get("default") in CODEX_SUPPORTED_MODELS:
        entry.pop("default", None)
    data["model"] = entry
    write_config(home, data)


def zalo_plugin_key(plugin_dir: Path) -> str:
    """Registry key Hermes matches = the `name:` field of plugin.yaml."""
    try:
        for line in (plugin_dir / "plugin.yaml").read_text(encoding="utf-8").splitlines():
            if line.startswith("name:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    except OSError:
        pass
    return ZALO_PLUGIN_FALLBACK_KEY


def enable_zalo(home: Path, plugin_dir: Path) -> None:
    """Enable the Zalo plugin AND its platform entry (both are required).

    plugins.enabled only makes the gateway LOAD the adapter; it starts the
    platform (and spawns the sidecar) only when platforms.<id>.enabled is true.
    """
    data = read_config(home)

    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    key = zalo_plugin_key(plugin_dir)
    if key not in enabled:
        enabled.append(key)
    plugins["enabled"] = enabled
    plugins.setdefault("disabled", [])
    data["plugins"] = plugins

    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        platforms = {}
    entry = platforms.get(ZALO_PLATFORM_ID)
    if not isinstance(entry, dict):
        entry = {}
    entry["enabled"] = True
    platforms[ZALO_PLATFORM_ID] = entry
    data["platforms"] = platforms

    write_config(home, data)

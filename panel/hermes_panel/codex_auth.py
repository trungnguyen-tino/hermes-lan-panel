"""$HERMES_HOME/auth.json helpers for the ChatGPT (Codex) OAuth credential.

Hermes prefers auth.json's `active_provider` over config.yaml's model.provider,
so every provider switch must touch this file too — otherwise selecting an
API-key provider silently keeps routing through Codex.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from hermes_panel.hermes_config import CODEX_ALIASES, CODEX_PROVIDER

logger = logging.getLogger(__name__)

# Keys an auth.json entry may use across Hermes versions.
CODEX_AUTH_KEYS = ("codex", "openai-codex", "codex-oauth")


def auth_path(home: Path) -> Path:
    return home / "auth.json"


def _load(home: Path) -> dict:
    path = auth_path(home)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(home: Path, data: dict) -> None:
    path = auth_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)


def has_codex_token(home: Path) -> bool:
    """True when auth.json holds a Codex credential, in any known shape.

    Shapes seen in the wild:
      {"codex": {...}}                              legacy top-level
      {"providers": {"openai-codex": {...}}}        providers map
      {"credential_pool": {"openai-codex": [...]}}  v1 pool
    """
    data = _load(home)
    if not data:
        return False
    candidates = set(data.keys())
    providers = data.get("providers")
    if isinstance(providers, dict):
        candidates |= set(providers.keys())
    pool = data.get("credential_pool")
    if isinstance(pool, dict):
        candidates |= {k for k, v in pool.items() if v}
    return any(key in candidates for key in CODEX_AUTH_KEYS)


def sync_active_provider(home: Path, provider: str) -> None:
    """Align auth.json's active_provider with the chosen chat provider."""
    data = _load(home)
    if not data:
        return
    active = data.get("active_provider")
    changed = False
    if provider in CODEX_ALIASES:
        if has_codex_token(home) and active not in CODEX_AUTH_KEYS:
            data["active_provider"] = CODEX_PROVIDER
            changed = True
    elif active in CODEX_AUTH_KEYS:
        data["active_provider"] = None
        changed = True
    if changed:
        _save(home, data)
        logger.info("auth.json active_provider -> %s", data.get("active_provider"))


def clear_codex(home: Path) -> None:
    """Drop every Codex credential shape + reset active_provider."""
    data = _load(home)
    if not data:
        return
    providers = data.get("providers")
    if isinstance(providers, dict):
        for key in CODEX_AUTH_KEYS:
            providers.pop(key, None)
    pool = data.get("credential_pool")
    if isinstance(pool, dict):
        for key in CODEX_AUTH_KEYS:
            pool.pop(key, None)
    for key in CODEX_AUTH_KEYS:
        data.pop(key, None)
    if data.get("active_provider") in CODEX_AUTH_KEYS:
        data["active_provider"] = None
    _save(home, data)


def import_auth(home: Path, parsed: dict) -> None:
    """Store an auth.json captured elsewhere (Codex CLI / another machine)."""
    _save(home, parsed)


def contains_codex_entry(parsed: dict) -> bool:
    """Validate a pasted auth.json before it overwrites the real one."""
    keys = set(parsed.keys())
    for section in ("providers", "credential_pool"):
        value = parsed.get(section)
        if isinstance(value, dict):
            keys |= set(value.keys())
    return any(key in keys for key in CODEX_AUTH_KEYS)

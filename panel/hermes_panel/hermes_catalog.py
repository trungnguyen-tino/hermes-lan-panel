"""Đọc danh mục provider/model TỪ CHÍNH Hermes, không tự chép tay.

Panel chạy trong venv riêng nên không import được `hermes_cli`; ta gọi Python
của Hermes như một tiến trình con và lấy JSON. Nguồn dữ liệu:

- `hermes_cli.provider_catalog.provider_catalog()` — đúng danh sách provider mà
  `hermes model` hiển thị, kèm biến môi trường chứa API key của từng cái.
- `hermes_cli.models.cached_provider_model_ids(slug)` — danh sách model của
  provider (curated hoặc lấy live từ /v1/models), đã có cache đĩa của Hermes.

Danh sách tự chép tay sẽ lệch theo thời gian: bản 0.20 dùng `deepseek-v4-pro`
trong khi tài liệu cũ ghi `deepseek-chat`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from hermes_panel.config import Settings

logger = logging.getLogger(__name__)

_TIMEOUT = 25.0
_TTL = 300.0  # giây — đủ để bấm qua lại trong GUI mà không spawn Python liên tục
_cache: dict[str, tuple[float, object]] = {}


class CatalogError(RuntimeError):
    pass


def _hermes_paths(settings: Settings) -> tuple[Path, Path]:
    """(python của venv Hermes, thư mục mã nguồn) — suy ra từ symlink `hermes`."""
    real = Path(os.path.realpath(settings.hermes_bin))          # …/.venv/bin/hermes
    python = real.parent / "python"
    source_dir = real.parents[2] if len(real.parents) >= 3 else real.parent
    if not python.exists():
        raise CatalogError("Chưa cài Hermes Agent trên máy này.")
    return python, source_dir


async def _run(settings: Settings, script: str) -> object:
    python, source_dir = _hermes_paths(settings)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(settings.hermes_home)
    env.setdefault("HOME", "/root")
    try:
        proc = await asyncio.create_subprocess_exec(
            str(python), "-c", script,
            cwd=str(source_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as exc:
        raise CatalogError(f"Không đọc được danh mục từ Hermes: {exc}")
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace").strip().splitlines()[-1:] or [""]
        raise CatalogError(f"Hermes trả lỗi khi đọc danh mục: {detail[0][:200]}")
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError as exc:
        raise CatalogError(f"Danh mục Hermes không phải JSON hợp lệ: {exc}")


_PROVIDERS_SCRIPT = """
import json
from hermes_cli.provider_catalog import provider_catalog
print(json.dumps([
    {
        "id": p.slug,
        "label": p.label,
        "description": p.description,
        "auth_type": p.auth_type,
        "tab": p.tab,
        "env_key": p.api_key_env_vars[0] if p.api_key_env_vars else "",
        "signup_url": p.signup_url,
        "order": p.order,
    }
    for p in provider_catalog()
]))
"""

_MODELS_SCRIPT = """
import json, sys
from hermes_cli.models import cached_provider_model_ids, get_default_model_for_provider
slug = sys.argv[1] if len(sys.argv) > 1 else ""
force = sys.argv[2] == "1" if len(sys.argv) > 2 else False
try:
    ids = cached_provider_model_ids(slug, force_refresh=force)
except Exception:
    ids = []
try:
    default = get_default_model_for_provider(slug)
except Exception:
    default = ""
print(json.dumps({"models": list(ids), "default": default}))
"""


async def providers(settings: Settings) -> list[dict]:
    cached = _cache.get("providers")
    if cached and time.monotonic() - cached[0] < _TTL:
        return cached[1]  # type: ignore[return-value]
    data = await _run(settings, _PROVIDERS_SCRIPT)
    if not isinstance(data, list):
        raise CatalogError("Danh mục provider của Hermes có định dạng lạ.")
    _cache["providers"] = (time.monotonic(), data)
    return data


async def models(settings: Settings, provider: str, *, refresh: bool = False) -> dict:
    key = f"models:{provider}"
    cached = _cache.get(key)
    if cached and not refresh and time.monotonic() - cached[0] < _TTL:
        return cached[1]  # type: ignore[return-value]
    script = _MODELS_SCRIPT.replace(
        'sys.argv[1] if len(sys.argv) > 1 else ""', json.dumps(provider)
    ).replace('sys.argv[2] == "1" if len(sys.argv) > 2 else False', "True" if refresh else "False")
    data = await _run(settings, script)
    if not isinstance(data, dict):
        raise CatalogError("Danh sách model của Hermes có định dạng lạ.")
    _cache[key] = (time.monotonic(), data)
    return data


def clear_cache() -> None:
    _cache.clear()

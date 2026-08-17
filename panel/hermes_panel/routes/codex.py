"""ChatGPT (OpenAI Codex) OAuth — device-code login driven from the GUI.

`hermes auth add openai-codex --type oauth --no-browser` prints a URL + a short
code, then keeps polling OpenAI until the user finishes in a browser and the
token lands in $HERMES_HOME/auth.json. We spawn it, scrape the URL + code, and
leave it running in the background; the GUI polls /status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status

from hermes_panel.codex_auth import (
    clear_codex,
    contains_codex_entry,
    has_codex_token,
    import_auth,
    sync_active_provider,
)
from hermes_panel.config import Settings
from hermes_panel.deps import get_settings_dep, require_session
from hermes_panel.hermes_config import (
    CODEX_ALIASES,
    CODEX_PROVIDER,
    CODEX_SUPPORTED_MODELS,
    get_model,
    resolve_codex_model,
    set_model,
    unset_codex_model,
)
from hermes_panel.models import ApiResponse
from hermes_panel.sysctl import ServiceError, restart

logger = logging.getLogger(__name__)

router = APIRouter(tags=["codex"], dependencies=[Depends(require_session)])

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_URL_RE = re.compile(r"https://\S+")
_CODE_RE = re.compile(r"\b([A-Z0-9]{3,5}-[A-Z0-9]{3,5})\b")
_SCRAPE_TIMEOUT = 15.0

# One device flow at a time; the subprocess keeps polling after we return.
_flow: dict = {"proc": None, "url": None, "code": None, "started": 0.0}

_GATEWAY = "hermes-gateway"


async def _restart_gateway(settings: Settings) -> None:
    try:
        await restart(_GATEWAY, (_GATEWAY,))
    except ServiceError as exc:
        logger.error("restart gateway sau bước Codex thất bại: %s", exc)


def _cli_env(settings: Settings) -> dict[str, str]:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(settings.hermes_home)
    env.setdefault("HOME", "/root")
    env["PYTHONUNBUFFERED"] = "1"
    return env


@router.post("/api/codex/start", response_model=ApiResponse)
async def codex_start(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    """Start the device-code login and return {url, code} to show the user."""
    existing = _flow.get("proc")
    if existing is not None and existing.returncode is None and _flow.get("url"):
        return ApiResponse(
            ok=True,
            data={"status": "pending", "url": _flow["url"], "code": _flow["code"]},
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            str(settings.hermes_bin), "auth", "add", CODEX_PROVIDER,
            "--type", "oauth", "--no-browser",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            env=_cli_env(settings),
        )
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Không chạy được hermes CLI: {exc}",
        )

    _flow.update({"proc": proc, "url": None, "code": None, "started": time.time()})

    url = code = None
    buf = ""
    deadline = time.time() + _SCRAPE_TIMEOUT
    while time.time() < deadline and proc.stdout is not None:
        try:
            chunk = await asyncio.wait_for(proc.stdout.read(256), timeout=2.0)
        except asyncio.TimeoutError:
            chunk = b""
        if chunk:
            buf += chunk.decode(errors="replace")
            clean = _ANSI_RE.sub("", buf)
            if url is None:
                match = _URL_RE.search(clean)
                if match:
                    url = match.group(0).rstrip(".,)")
            if code is None:
                match = _CODE_RE.search(clean)
                if match:
                    code = match.group(1)
        if url and code:
            break
        if proc.returncode is not None:
            break

    _flow["url"], _flow["code"] = url, code
    if not url:
        return ApiResponse(
            ok=False,
            data={"status": "error", "raw": buf[-500:]},
            error="Không đọc được link đăng nhập từ hermes CLI. Xem 'raw' để biết lý do.",
        )
    return ApiResponse(ok=True, data={"status": "pending", "url": url, "code": code})


@router.get("/api/codex/status", response_model=ApiResponse)
async def codex_status(
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ApiResponse:
    """Report Codex state. Pins the model only when that cannot fight the user.

    The GUI polls this, so it must not overwrite an explicit provider choice:
    a Codex token can sit in auth.json while an API-key provider is selected.
    """
    if not has_codex_token(settings.hermes_home):
        proc = _flow.get("proc")
        if proc is not None and proc.returncode is None:
            return ApiResponse(
                ok=True,
                data={"status": "pending", "url": _flow.get("url"), "code": _flow.get("code")},
            )
        return ApiResponse(ok=True, data={"status": "disconnected"})

    current = get_model(settings.hermes_home)
    is_codex_cfg = current["provider"] in CODEX_ALIASES
    already = current["provider"] == CODEX_PROVIDER and current["model"] in CODEX_SUPPORTED_MODELS
    flow_completed = _flow.get("proc") is not None
    should_pin = not already and (flow_completed or not current["provider"] or is_codex_cfg)

    if should_pin:
        set_model(settings.hermes_home, CODEX_PROVIDER, resolve_codex_model(current["model"]))
        sync_active_provider(settings.hermes_home, CODEX_PROVIDER)
        _flow["proc"] = None  # consume the flow so later polls stay passive
        background_tasks.add_task(_restart_gateway, settings)

    return ApiResponse(
        ok=True,
        data={
            "status": "connected",
            "model_set": should_pin or already,
            "active": should_pin or is_codex_cfg,
            "model": get_model(settings.hermes_home)["model"],
        },
    )


@router.post("/api/codex/import", response_model=ApiResponse)
async def codex_import(
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    body: dict = Body(...),
) -> ApiResponse:
    """Fallback: paste an auth.json from the Codex CLI / another machine."""
    raw = body.get("auth_json")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"auth.json không phải JSON hợp lệ: {exc}",
            )
    elif isinstance(raw, dict):
        parsed = raw
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Thiếu auth_json.")

    if not contains_codex_entry(parsed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="auth.json không chứa thông tin đăng nhập ChatGPT/Codex.",
        )

    import_auth(settings.hermes_home, parsed)
    set_model(settings.hermes_home, CODEX_PROVIDER, resolve_codex_model(""))
    sync_active_provider(settings.hermes_home, CODEX_PROVIDER)
    background_tasks.add_task(_restart_gateway, settings)
    return ApiResponse(ok=True, data={"status": "connected", "imported": True})


@router.post("/api/codex/disable", response_model=ApiResponse)
async def codex_disable(
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    body: dict = Body(default={}),
) -> ApiResponse:
    """Disconnect ChatGPT so an API-key provider can take over."""
    try:
        proc = await asyncio.create_subprocess_exec(
            str(settings.hermes_bin), "auth", "remove", CODEX_PROVIDER,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            env=_cli_env(settings),
        )
        await asyncio.wait_for(proc.communicate(), timeout=20)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.warning("hermes auth remove lỗi (vẫn dọn tiếp bằng tay): %s", exc)

    clear_codex(settings.hermes_home)
    to_provider = str(body.get("to_provider") or "").strip()
    unset_codex_model(settings.hermes_home, to_provider)
    _flow["proc"] = None
    background_tasks.add_task(_restart_gateway, settings)
    return ApiResponse(ok=True, data={"status": "disconnected", "to_provider": to_provider or None})

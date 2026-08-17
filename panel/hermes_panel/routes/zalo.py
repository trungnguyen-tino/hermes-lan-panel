"""Zalo bot control — QR login + owner setup, proxied to the Node sidecar.

The Zalo plugin ships a Node sidecar (zca-js) bound to 127.0.0.1 that the
gateway normally spawns. Chicken-and-egg: the plugin only starts it once
ZALO_PERSONAL_OWNER_UID is known, but that UID can only be resolved AFTER a QR
login. So the panel spawns the sidecar itself for the QR step, then — once the
owner is set — enables the plugin and restarts the gateway, which takes over
(the session file on disk survives the handover).

Bot vs owner: the QR-scanned account is the BOT (use a secondary number). The
owner is the boss's own Zalo account, resolved from a phone number.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import time
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response

from hermes_panel.config import Settings
from hermes_panel.deps import get_settings_dep, require_session
from hermes_panel.envfile import set_env
from hermes_panel.hermes_config import enable_zalo
from hermes_panel.models import ApiResponse, OwnerRequest
from hermes_panel.sysctl import ServiceError, restart

logger = logging.getLogger(__name__)

router = APIRouter(tags=["zalo"], dependencies=[Depends(require_session)])

OWNER_UID_KEY = "ZALO_PERSONAL_OWNER_UID"
SIDECAR_PORT_KEY = "ZALO_PERSONAL_SIDECAR_PORT"
SESSION_DIR_KEY = "ZALO_PERSONAL_SESSION_DIR"
DEFAULT_SIDECAR_PORT = 3838
DEFAULT_SESSION_DIR = "/opt/data/zalo"
SIDECAR_TIMEOUT = 8.0
_GATEWAY = "hermes-gateway"
# Không tự bật lại sidecar dày hơn mức này (GUI poll 8 giây một lần).
_RESPAWN_COOLDOWN = 60.0
_last_respawn = 0.0


def _sidecar_port(settings: Settings) -> int:
    raw = settings.merged_env().get(SIDECAR_PORT_KEY, "").strip()
    try:
        return int(raw) if raw else DEFAULT_SIDECAR_PORT
    except ValueError:
        return DEFAULT_SIDECAR_PORT


def _base_url(settings: Settings) -> str:
    return f"http://127.0.0.1:{_sidecar_port(settings)}"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _owner_uid(settings: Settings) -> str:
    return settings.merged_env().get(OWNER_UID_KEY, "").strip()


def _session_dir(settings: Settings) -> Path:
    raw = settings.merged_env().get(SESSION_DIR_KEY, "").strip()
    return Path(raw or DEFAULT_SESSION_DIR)


def _has_saved_login(settings: Settings) -> bool:
    """Đã từng quét QR thành công? (sidecar lưu phiên ra đĩa)"""
    return (_session_dir(settings) / "session.json").exists()


def _unreachable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Sidecar Zalo chưa sẵn sàng. Kiểm tra plugin đã cài và thử lại sau vài giây.",
    )


async def _ensure_sidecar(settings: Settings) -> bool:
    """Start the Node sidecar for the QR step when nothing holds its port."""
    port = _sidecar_port(settings)
    if _port_open(port):
        return True

    server_js = settings.zalo_plugin_dir / "sidecar" / "server.js"
    if not server_js.exists():
        logger.error("Không tìm thấy sidecar Zalo tại %s", server_js)
        return False

    env = os.environ.copy()
    merged = settings.merged_env()
    for key in (SIDECAR_PORT_KEY, SESSION_DIR_KEY, "ZALO_PERSONAL_PROXY", "HOME"):
        if merged.get(key):
            env[key] = merged[key]
    env.setdefault("HOME", "/root")

    # Chạy trong scope systemd riêng: nếu để nó là con của panel, systemd giết cả
    # cgroup khi `systemctl restart hermes-panel` và người dùng vừa quét QR xong
    # lại thấy "chưa kết nối". Không có systemd-run thì chạy trực tiếp.
    command: list[str] = ["node", str(server_js)]
    if shutil.which("systemd-run"):
        command = [
            "systemd-run", "--scope", "--quiet", "--collect",
            "--unit", "hermes-zalo-sidecar", *command,
        ]

    # Log ra đĩa thay vì /dev/null — không có log thì mọi lỗi đăng nhập Zalo
    # đều biến thành "sidecar chưa sẵn sàng" mà không biết vì sao.
    log_path = _session_dir(settings) / "sidecar.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "ab")
    except OSError:
        log_file = None

    try:
        await asyncio.create_subprocess_exec(
            *command,
            cwd=str(server_js.parent),
            env=env,
            stdout=log_file or asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT if log_file else asyncio.subprocess.DEVNULL,
            start_new_session=True,  # detach so it outlives this request
        )
    except (FileNotFoundError, OSError) as exc:
        logger.error("Không spawn được sidecar Zalo: %s", exc)
        return False
    finally:
        if log_file is not None:
            log_file.close()

    for _ in range(20):
        if _port_open(port):
            return True
        await asyncio.sleep(0.5)
    return _port_open(port)


async def _sidecar(settings: Settings, method: str, path: str, **kwargs) -> httpx.Response:
    timeout = kwargs.pop("timeout", SIDECAR_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(method, f"{_base_url(settings)}{path}", **kwargs)


async def _handover(settings: Settings) -> None:
    """Owner is known → enable the plugin and let the gateway own the sidecar."""
    try:
        enable_zalo(settings.hermes_home, settings.zalo_plugin_dir)
    except OSError as exc:
        logger.error("Bật plugin Zalo trong config.yaml thất bại: %s", exc)
    try:
        await restart(_GATEWAY, (_GATEWAY,))
    except ServiceError as exc:
        logger.error("restart gateway sau khi set owner Zalo thất bại: %s", exc)


@router.get("/api/zalo/status", response_model=ApiResponse)
async def zalo_status(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    """status ∈ disconnected | pending | scanned | connected | error."""
    global _last_respawn
    owner_set = bool(_owner_uid(settings))
    try:
        resp = await _sidecar(settings, "GET", "/health")
    except httpx.RequestError:
        # Sidecar tắt nhưng phiên đăng nhập vẫn còn trên đĩa (thường do panel hoặc
        # gateway vừa khởi động lại) → bật lại để đọc trạng thái, đừng báo người
        # dùng là "chưa kết nối" và bắt họ quét QR lần nữa.
        revived = False
        if _has_saved_login(settings) and time.monotonic() - _last_respawn > _RESPAWN_COOLDOWN:
            _last_respawn = time.monotonic()
            revived = await _ensure_sidecar(settings)
        if revived:
            try:
                resp = await _sidecar(settings, "GET", "/health")
            except httpx.RequestError:
                revived = False
        if not revived:
            return ApiResponse(
                ok=True,
                data={"status": "disconnected", "bot_uid": None, "name": None,
                      "sidecar": False, "owner_set": owner_set},
            )
    if resp.status_code != 200:
        return ApiResponse(
            ok=True,
            data={"status": "disconnected", "bot_uid": None, "name": None,
                  "sidecar": True, "owner_set": owner_set},
        )
    health = resp.json()
    return ApiResponse(
        ok=True,
        data={
            "status": health.get("status", "disconnected"),
            "bot_uid": health.get("uid"),
            "name": health.get("name"),
            "error": health.get("error"),
            "sidecar": True,
            "owner_set": owner_set,
        },
    )


@router.post("/api/zalo/connect", response_model=ApiResponse)
async def zalo_connect(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    """Start QR login; the GUI then polls /status and renders /api/zalo/qr."""
    if not await _ensure_sidecar(settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Không khởi động được sidecar Zalo (Node.js). Kiểm tra plugin và node.",
        )
    try:
        resp = await _sidecar(settings, "POST", "/login/qr")
    except httpx.RequestError:
        raise _unreachable()
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sidecar lỗi khi bắt đầu đăng nhập QR (HTTP {resp.status_code}).",
        )
    body = resp.json()
    if body.get("status") == "already_connected":
        return ApiResponse(ok=True, data={"status": "connected", "bot_uid": body.get("uid")})
    return ApiResponse(ok=True, data={"status": "pending", "qr_url": "/api/zalo/qr"})


@router.get("/api/zalo/qr")
async def zalo_qr(settings: Annotated[Settings, Depends(get_settings_dep)]) -> Response:
    """Raw QR PNG so the GUI can use it as <img src>."""
    try:
        resp = await _sidecar(settings, "GET", "/qr.png")
    except httpx.RequestError:
        raise _unreachable()
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mã QR chưa sẵn sàng, thử lại sau 1-2 giây.",
        )
    return Response(content=resp.content, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.get("/api/zalo/owner", response_model=ApiResponse)
async def zalo_owner(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    uid = _owner_uid(settings)
    return ApiResponse(ok=True, data={"owner_uid": uid or None, "owner_set": bool(uid)})


@router.post("/api/zalo/set-owner", response_model=ApiResponse)
async def zalo_set_owner(
    body: OwnerRequest,
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ApiResponse:
    """Set the boss's account as owner, by phone number (or an explicit UID)."""
    uid = body.uid.strip()
    phone = body.phone.strip()

    if not uid and phone:
        try:
            resp = await _sidecar(
                settings, "POST", "/users/by-phones", json={"phones": [phone]}, timeout=15.0
            )
        except httpx.RequestError:
            raise _unreachable()
        if resp.status_code == 503:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bot Zalo chưa đăng nhập — quét QR trước rồi mới tra số của sếp.",
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Không tra được số điện thoại (HTTP {resp.status_code}).",
            )
        users = resp.json().get("users") or []
        if not users or not users[0].get("uid"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy tài khoản Zalo cho số {phone}.",
            )
        uid = str(users[0]["uid"])

    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cần số Zalo của sếp (phone) hoặc uid.",
        )

    set_env(settings.hermes_env_file, OWNER_UID_KEY, uid)
    set_env(settings.env_file, OWNER_UID_KEY, uid)
    background_tasks.add_task(_handover, settings)
    return ApiResponse(ok=True, data={"owner_uid": uid, "owner_set": True})


@router.post("/api/zalo/disconnect", response_model=ApiResponse)
async def zalo_disconnect(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    try:
        resp = await _sidecar(settings, "POST", "/logout")
    except httpx.RequestError:
        raise _unreachable()
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sidecar lỗi khi đăng xuất (HTTP {resp.status_code}).",
        )
    return ApiResponse(ok=True, data={"status": "disconnected"})

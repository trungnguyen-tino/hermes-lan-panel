"""Service status, start/stop/restart, journal logs and host info."""

from __future__ import annotations

import asyncio
import logging
import shutil
import socket
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from hermes_panel import __version__
from hermes_panel.config import ALLOWED_SERVICES, Settings
from hermes_panel.deps import get_settings_dep, require_session
from hermes_panel.models import ApiResponse
from hermes_panel.sysctl import ServiceError, control, is_active, journal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"], dependencies=[Depends(require_session)])

# Services rendered in the GUI. The panel itself is listed (and log-readable)
# but never restartable from here — that would kill the request mid-flight.
SERVICES = ("hermes-gateway", "hermes-dashboard", "hermes-panel")
CONTROLLABLE = ("hermes-gateway", "hermes-dashboard")


def _host_stats() -> dict:
    stats: dict = {}
    try:
        stats["load_avg"] = [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
    except (OSError, ValueError):
        stats["load_avg"] = []
    try:
        mem = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            mem[key] = int(rest.strip().split()[0]) * 1024
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        stats["memory"] = {
            "total": total,
            "available": available,
            "percent": round((total - available) / total * 100, 1) if total else 0.0,
        }
    except (OSError, ValueError, IndexError):
        stats["memory"] = {}
    try:
        usage = shutil.disk_usage("/")
        stats["disk"] = {
            "total": usage.total,
            "used": usage.used,
            "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        }
    except OSError:
        stats["disk"] = {}
    try:
        stats["uptime_seconds"] = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        stats["uptime_seconds"] = 0.0
    return stats


async def _hermes_version(settings: Settings) -> str:
    if not settings.hermes_bin.exists():
        return "chưa cài"
    try:
        proc = await asyncio.create_subprocess_exec(
            str(settings.hermes_bin), "version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={"HERMES_HOME": str(settings.hermes_home), "HOME": "/root", "PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.warning("hermes version failed: %s", exc)
        return "không đọc được"
    return out.decode(errors="replace").strip().splitlines()[0] if out else "không rõ"


def _lan_ip() -> str:
    """Primary outbound-interface IP (no packet is actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect(("8.8.8.8", 53))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@router.get("/api/info", response_model=ApiResponse)
async def info(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    ip = _lan_ip()
    return ApiResponse(
        ok=True,
        data={
            "hostname": socket.gethostname(),
            "ip": ip,
            "panel_version": __version__,
            "hermes_version": await _hermes_version(settings),
            "chat_url": settings.chat_url or f"http://{ip}:{settings.dashboard_port}",
            "hermes_home": str(settings.hermes_home),
        },
    )


@router.get("/api/status", response_model=ApiResponse)
async def get_status() -> ApiResponse:
    states = await asyncio.gather(*(is_active(svc) for svc in SERVICES))
    return ApiResponse(
        ok=True,
        data={
            "services": [
                {"name": svc, "state": state, "controllable": svc in CONTROLLABLE}
                for svc, state in zip(SERVICES, states)
            ],
            "host": _host_stats(),
        },
    )


@router.post("/api/services/{service}/{action}", response_model=ApiResponse)
async def service_action(service: str, action: str) -> ApiResponse:
    if service not in CONTROLLABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Không điều khiển được service '{service}' từ panel.",
        )
    try:
        await control(service, action, CONTROLLABLE)
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    return ApiResponse(ok=True, data={"service": service, "action": action})


@router.get("/api/logs", response_model=ApiResponse)
async def get_logs(
    service: str = Query(default="hermes-gateway"),
    lines: int = Query(default=200, ge=10, le=2000),
) -> ApiResponse:
    try:
        text = await journal(service, ALLOWED_SERVICES, lines)
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ApiResponse(ok=True, data={"service": service, "lines": text.splitlines()})

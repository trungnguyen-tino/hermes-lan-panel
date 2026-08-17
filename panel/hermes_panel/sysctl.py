"""systemctl / journalctl wrappers.

Every unit name is checked against an allowlist before it reaches a subprocess,
so a malformed request can never touch an unrelated service.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0
ACTIONS = ("start", "stop", "restart")


class ServiceError(RuntimeError):
    pass


def _check(service: str, allowed: tuple[str, ...]) -> str:
    if service not in allowed:
        raise ServiceError(f"Service không được phép: {service}")
    return service


async def _run(*args: str, timeout: float = _TIMEOUT) -> tuple[int, str, str]:
    binary = shutil.which(args[0])
    if binary is None:
        raise ServiceError(f"Không tìm thấy lệnh '{args[0]}' trên hệ thống.")
    proc = await asyncio.create_subprocess_exec(
        binary, *args[1:],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ServiceError(f"Lệnh '{' '.join(args)}' quá thời gian chờ ({timeout:.0f}s).")
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def is_active(service: str) -> str:
    """Return systemd's state word (active / inactive / failed / unknown)."""
    try:
        _, out, _ = await _run("systemctl", "is-active", service, timeout=10)
    except ServiceError:
        return "unknown"
    return out.strip() or "unknown"


async def control(service: str, action: str, allowed: tuple[str, ...]) -> None:
    if action not in ACTIONS:
        raise ServiceError(f"Hành động không hợp lệ: {action}")
    _check(service, allowed)
    code, _, err = await _run("systemctl", action, service, timeout=60)
    if code != 0:
        raise ServiceError(f"systemctl {action} {service} lỗi: {err.strip()[:300]}")


async def restart(service: str, allowed: tuple[str, ...]) -> None:
    await control(service, "restart", allowed)


async def journal(service: str, allowed: tuple[str, ...], lines: int = 200) -> str:
    _check(service, allowed)
    lines = max(10, min(int(lines), 2000))
    code, out, err = await _run(
        "journalctl", "-u", service, "-n", str(lines), "--no-pager", "--output", "short-iso",
    )
    if code != 0:
        raise ServiceError(f"journalctl lỗi: {err.strip()[:300]}")
    return out

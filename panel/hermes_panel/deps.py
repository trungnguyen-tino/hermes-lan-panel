"""FastAPI dependencies: settings injection + session gate."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from hermes_panel.auth import SESSION_COOKIE, LoginRateLimiter, verify_session
from hermes_panel.config import Settings, get_settings


def get_settings_dep() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def get_rate_limiter() -> LoginRateLimiter:
    return LoginRateLimiter()


def socket_ip(request: Request) -> str:
    """IP của kết nối TCP — không giả mạo được bằng header."""
    return request.client.host if request.client else "unknown"


def client_ip(request: Request) -> str:
    """IP người dùng thật khi đứng sau Nginx Proxy Manager."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return socket_ip(request)


def login_ips(request: Request) -> set[str]:
    """Cả hai IP đều bị tính vào rate limit.

    Chỉ đếm theo X-Forwarded-For thì kẻ tấn công đổi header mỗi lần thử là thoát
    giới hạn; chỉ đếm theo socket thì mọi người sau NPM dùng chung một hạn mức.
    """
    return {client_ip(request), socket_ip(request)}


def require_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> str:
    username = verify_session(request.cookies.get(SESSION_COOKIE, ""), settings.session_secret)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa đăng nhập hoặc phiên đã hết hạn.",
        )
    return username

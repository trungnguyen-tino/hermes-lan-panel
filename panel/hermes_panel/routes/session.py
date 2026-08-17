"""Login / logout / whoami."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from hermes_panel.auth import SESSION_COOKIE, create_session, verify_password
from hermes_panel.config import Settings
from hermes_panel.deps import get_rate_limiter, get_settings_dep, login_ips, require_session
from hermes_panel.models import ApiResponse, LoginRequest

router = APIRouter(tags=["session"])


def _https(request: Request) -> bool:
    """True when the browser is on HTTPS (directly or via a proxy header)."""
    if request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https":
        return True
    return request.url.scheme == "https"


@router.post("/api/login", response_model=ApiResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ApiResponse:
    limiter = get_rate_limiter()
    ips = login_ips(request)
    if any(limiter.blocked(ip) for ip in ips):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Sai mật khẩu quá nhiều lần. Thử lại sau 15 phút.",
        )

    ok = body.username == settings.admin_user and verify_password(
        body.password, settings.password_hash
    )
    if not ok:
        for ip in ips:
            limiter.record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tài khoản hoặc mật khẩu.",
        )

    for ip in ips:
        limiter.reset(ip)
    token, expiry = create_session(body.username, settings.session_secret, settings.session_ttl)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl,
        httponly=True,
        samesite="lax",
        secure=_https(request),
        path="/",
    )
    return ApiResponse(ok=True, data={"username": body.username, "expires_at": expiry})


@router.post("/api/logout", response_model=ApiResponse)
async def logout(response: Response) -> ApiResponse:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return ApiResponse(ok=True, data={"logged_out": True})


@router.get("/api/me", response_model=ApiResponse)
async def me(username: Annotated[str, Depends(require_session)]) -> ApiResponse:
    return ApiResponse(ok=True, data={"username": username})

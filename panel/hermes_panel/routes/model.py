"""Chọn provider/model và quản lý API key — danh mục lấy từ chính Hermes.

Keys được ghi vào CẢ HAI kho env: /opt/hermes/.env (systemd nạp cho gateway) và
$HERMES_HOME/.env (Hermes CLI đọc).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from hermes_panel import hermes_catalog
from hermes_panel.codex_auth import sync_active_provider
from hermes_panel.config import Settings
from hermes_panel.deps import get_settings_dep, require_session
from hermes_panel.envfile import delete_env, mask_value, set_env
from hermes_panel.hermes_config import get_model, set_model
from hermes_panel.models import ApiKeyRequest, ApiResponse, ModelRequest
from hermes_panel.sysctl import ServiceError, restart

logger = logging.getLogger(__name__)

router = APIRouter(tags=["model"], dependencies=[Depends(require_session)])

_GATEWAY = "hermes-gateway"


async def _env_key(settings: Settings, provider: str) -> str:
    """Biến môi trường chứa API key của provider, theo đúng khai báo của Hermes."""
    try:
        for entry in await hermes_catalog.providers(settings):
            if entry.get("id") == provider and entry.get("env_key"):
                return str(entry["env_key"])
    except hermes_catalog.CatalogError as exc:
        logger.warning("Không đọc được danh mục provider: %s", exc)
    return f"{provider.upper().replace('-', '_')}_API_KEY"


async def _restart_gateway() -> None:
    try:
        await restart(_GATEWAY, (_GATEWAY,))
    except ServiceError as exc:
        logger.error("restart gateway thất bại: %s", exc)


@router.get("/api/providers", response_model=ApiResponse)
async def list_providers(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    """Toàn bộ provider Hermes hỗ trợ + provider nào đã có key."""
    env = settings.merged_env()
    current = get_model(settings.hermes_home)
    try:
        catalog = await hermes_catalog.providers(settings)
    except hermes_catalog.CatalogError as exc:
        return ApiResponse(ok=True, data={"providers": [], "current": current, "warning": str(exc)})

    providers = []
    for entry in catalog:
        env_key = str(entry.get("env_key") or "")
        value = env.get(env_key, "") if env_key else ""
        providers.append({
            **entry,
            "key_set": bool(value),
            "key_masked": mask_value(env_key, value) if value else "",
        })
    return ApiResponse(ok=True, data={"providers": providers, "current": current})


@router.get("/api/models", response_model=ApiResponse)
async def list_models(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: str = Query(...),
    refresh: bool = Query(default=False),
) -> ApiResponse:
    """Model của provider — do Hermes cung cấp (curated hoặc live /v1/models)."""
    try:
        data = await hermes_catalog.models(settings, provider.strip(), refresh=refresh)
    except hermes_catalog.CatalogError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return ApiResponse(ok=True, data={"provider": provider, **data})


@router.get("/api/model", response_model=ApiResponse)
async def read_model(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    return ApiResponse(ok=True, data=get_model(settings.hermes_home))


@router.put("/api/model", response_model=ApiResponse)
async def update_model(
    body: ModelRequest,
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ApiResponse:
    result = set_model(settings.hermes_home, body.provider.strip(), body.model.strip())
    # auth.json active_provider được Hermes ưu tiên hơn config.yaml — không đồng bộ
    # thì việc đổi provider âm thầm không có tác dụng khi còn token Codex.
    sync_active_provider(settings.hermes_home, result["provider"])
    background_tasks.add_task(_restart_gateway)
    return ApiResponse(ok=True, data=result)


@router.put("/api/api-key", response_model=ApiResponse)
async def save_api_key(
    body: ApiKeyRequest,
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ApiResponse:
    provider = body.provider.strip()
    key = await _env_key(settings, provider)
    set_env(settings.env_file, key, body.api_key.strip())
    set_env(settings.hermes_env_file, key, body.api_key.strip())
    background_tasks.add_task(_restart_gateway)
    return ApiResponse(ok=True, data={"provider": provider, "key": key})


@router.delete("/api/api-key", response_model=ApiResponse)
async def remove_api_key(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: str = Query(...),
) -> ApiResponse:
    key = await _env_key(settings, provider.strip())
    removed = delete_env(settings.env_file, key)
    removed = delete_env(settings.hermes_env_file, key) or removed
    return ApiResponse(ok=True, data={"removed": removed, "key": key})

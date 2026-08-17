"""Provider + model selection and API-key management.

Keys are written to BOTH env stores: /opt/hermes/.env (systemd injects it into
the gateway process) and $HERMES_HOME/.env (what the Hermes CLI reads).
"""

from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from hermes_panel.codex_auth import sync_active_provider
from hermes_panel.config import Settings
from hermes_panel.deps import get_settings_dep, require_session
from hermes_panel.envfile import delete_env, mask_value, set_env
from hermes_panel.hermes_config import CODEX_PROVIDER, get_model, set_model
from hermes_panel.models import ApiKeyRequest, ApiResponse, ModelRequest
from hermes_panel.sysctl import ServiceError, restart

logger = logging.getLogger(__name__)

router = APIRouter(tags=["model"], dependencies=[Depends(require_session)])

_GATEWAY = "hermes-gateway"

# Providers offered in the GUI. `test_url` is a cheap authenticated GET used to
# validate a key before saving it; None means "no test available".
PROVIDERS: list[dict] = [
    {"id": CODEX_PROVIDER, "label": "ChatGPT (đăng nhập OAuth)", "env_key": "",
     "test_url": None, "models": ["gpt-5.5", "gpt-5.5-pro", "gpt-5.4", "gpt-5.4-mini"]},
    {"id": "openai", "label": "OpenAI (API key)", "env_key": "OPENAI_API_KEY",
     "test_url": "https://api.openai.com/v1/models", "models": ["gpt-5.5", "gpt-4.1", "gpt-4o-mini"]},
    {"id": "anthropic", "label": "Anthropic Claude", "env_key": "ANTHROPIC_API_KEY",
     "test_url": "https://api.anthropic.com/v1/models",
     "models": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"]},
    {"id": "deepseek", "label": "DeepSeek", "env_key": "DEEPSEEK_API_KEY",
     "test_url": "https://api.deepseek.com/v1/models", "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"id": "google", "label": "Google Gemini", "env_key": "GOOGLE_API_KEY",
     "test_url": "https://generativelanguage.googleapis.com/v1beta/models",
     "models": ["gemini-3-pro", "gemini-3-flash"]},
    {"id": "openrouter", "label": "OpenRouter", "env_key": "OPENROUTER_API_KEY",
     "test_url": "https://openrouter.ai/api/v1/models", "models": ["openai/gpt-5.5", "anthropic/claude-sonnet-5"]},
    {"id": "groq", "label": "Groq", "env_key": "GROQ_API_KEY",
     "test_url": "https://api.groq.com/openai/v1/models", "models": ["llama-3.3-70b-versatile"]},
    {"id": "xai", "label": "xAI Grok", "env_key": "XAI_API_KEY",
     "test_url": "https://api.x.ai/v1/models", "models": ["grok-4"]},
]

_BY_ID = {p["id"]: p for p in PROVIDERS}


def _env_key(provider: str) -> str:
    entry = _BY_ID.get(provider)
    if entry and entry["env_key"]:
        return str(entry["env_key"])
    return f"{provider.upper().replace('-', '_')}_API_KEY"


async def _restart_gateway() -> None:
    try:
        await restart(_GATEWAY, (_GATEWAY,))
    except ServiceError as exc:
        logger.error("restart gateway thất bại: %s", exc)


@router.get("/api/providers", response_model=ApiResponse)
async def list_providers(settings: Annotated[Settings, Depends(get_settings_dep)]) -> ApiResponse:
    env = settings.merged_env()
    providers = []
    for entry in PROVIDERS:
        key = str(entry["env_key"])
        value = env.get(key, "") if key else ""
        providers.append({
            **entry,
            "key_set": bool(value),
            "key_masked": mask_value(key, value) if value else "",
        })
    return ApiResponse(ok=True, data={"providers": providers, "current": get_model(settings.hermes_home)})


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
    # auth.json's active_provider outranks config.yaml — align it or the switch
    # silently has no effect while a Codex token is still stored.
    sync_active_provider(settings.hermes_home, result["provider"])
    background_tasks.add_task(_restart_gateway)
    return ApiResponse(ok=True, data=result)


@router.put("/api/api-key", response_model=ApiResponse)
async def save_api_key(
    body: ApiKeyRequest,
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ApiResponse:
    key = _env_key(body.provider.strip())
    set_env(settings.env_file, key, body.api_key.strip())
    set_env(settings.hermes_env_file, key, body.api_key.strip())
    background_tasks.add_task(_restart_gateway)
    return ApiResponse(ok=True, data={"provider": body.provider, "key": key})


@router.delete("/api/api-key", response_model=ApiResponse)
async def remove_api_key(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: str = Query(...),
) -> ApiResponse:
    key = _env_key(provider.strip())
    removed = delete_env(settings.env_file, key)
    removed = delete_env(settings.hermes_env_file, key) or removed
    return ApiResponse(ok=True, data={"removed": removed, "key": key})


@router.post("/api/test-key", response_model=ApiResponse)
async def test_api_key(body: ApiKeyRequest) -> ApiResponse:
    entry = _BY_ID.get(body.provider.strip())
    if not entry or not entry["test_url"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Không hỗ trợ kiểm tra key cho provider '{body.provider}'.",
        )
    headers = {"Authorization": f"Bearer {body.api_key.strip()}"}
    if body.provider.strip() == "anthropic":
        headers = {"x-api-key": body.api_key.strip(), "anthropic-version": "2023-06-01"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(str(entry["test_url"]), headers=headers)
    except httpx.RequestError as exc:
        return ApiResponse(ok=False, error=f"Không gọi được provider: {exc}")
    ok = resp.status_code == 200
    return ApiResponse(
        ok=ok,
        data={"status_code": resp.status_code, "provider": body.provider},
        error=None if ok else f"Provider trả về HTTP {resp.status_code}",
    )

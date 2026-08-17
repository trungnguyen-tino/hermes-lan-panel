"""Shared response envelope + request schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    ok: bool = True
    data: Any | None = None
    error: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ModelRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(default="", max_length=128)


class ApiKeyRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=1, max_length=512)


class OwnerRequest(BaseModel):
    phone: str = Field(default="", max_length=32)
    uid: str = Field(default="", max_length=64)

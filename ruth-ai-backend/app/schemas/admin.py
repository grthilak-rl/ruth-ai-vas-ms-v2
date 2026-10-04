"""Schemas for /api/v1/admin (Model Management admin area)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    username: str


class AdminMeResponse(BaseModel):
    username: str
    role: str
    expires_at: datetime

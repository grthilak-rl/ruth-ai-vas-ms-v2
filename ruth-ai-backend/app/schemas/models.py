"""Pydantic schemas for AI models API.

Aligned with F6 §4.3 ModelsStatusResponse interface.
From API Contract - Models APIs.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ModelStatusInfo(BaseModel):
    """Individual model status info.

    Aligned with F6 §4.3 ModelStatusInfo interface.
    """

    model_id: str = Field(..., description="Machine identifier (e.g., 'fall_detection')")
    version: str = Field(..., description="Semver version")
    status: str = Field(
        ..., description="Operational status: active, idle, starting, stopping, error"
    )
    health: str = Field(
        ..., description="Health status: healthy, degraded, unhealthy"
    )
    cameras_active: int = Field(
        default=0, description="Count of cameras using this model"
    )
    last_inference_at: datetime | None = Field(
        None, description="Last inference timestamp"
    )
    started_at: datetime | None = Field(None, description="When model started")


class ModelsStatusResponse(BaseModel):
    """Response schema for GET /api/v1/models/status.

    Aligned with F6 ModelsStatusResponse interface.
    """

    models: list[ModelStatusInfo] = Field(..., description="List of model statuses")

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

    # Uploaded (model store) models only. Built-in entries never set these,
    # and the route omits unset fields, so built-in entries are unchanged.
    source: str | None = Field(None, description="'store' for uploaded models")
    display_name: str | None = Field(None, description="Name to show (store models)")
    zone_required_rules: list[str] | None = Field(
        None, description="Rules that fire only inside a zone of their type"
    )
    all_rules_need_zone: bool | None = Field(
        None, description="True when the model can raise nothing without a zone"
    )
    reports_ppe: bool | None = Field(
        None, description="Reports missing PPE, like the built-in ppe_detection"
    )


class ModelsStatusResponse(BaseModel):
    """Response schema for GET /api/v1/models/status.

    Aligned with F6 ModelsStatusResponse interface.
    """

    models: list[ModelStatusInfo] = Field(..., description="List of model statuses")

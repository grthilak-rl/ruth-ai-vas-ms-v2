"""Pydantic schemas for the bookmark analysis API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# Mirrors models.enums.BookmarkAnalysisState. Kept as a Literal here
# rather than importing the enum so the OpenAPI schema renders as a
# clean string enum without Python type leakage.
BookmarkAnalysisStateName = Literal["pending", "running", "completed", "failed"]


class BookmarkAnalysisSubmitRequest(BaseModel):
    """Request body for POST /api/v1/bookmark-analyses."""

    vas_bookmark_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="VAS bookmark UUID to analyse.",
    )
    model_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="AI model identifier. Same vocabulary as stream_sessions.model_id.",
    )
    model_version: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "Specific model version. Omit to use the model's registered "
            "current version at run time."
        ),
    )
    parameters: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Model-specific parameters (e.g. tank_corners, capacity_liters, "
            "alert_threshold for tank_overflow_monitoring). Passed verbatim "
            "to the analysis worker."
        ),
    )


class BookmarkAnalysisResponse(BaseModel):
    """Full bookmark analysis record returned by GET and POST endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vas_bookmark_id: str
    model_id: str
    model_version: str | None
    parameters: dict[str, Any] | None
    state: BookmarkAnalysisStateName
    summary: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    submitted_by: str | None


class BookmarkAnalysisListItem(BaseModel):
    """Lightweight item shape for list endpoints.

    Excludes the (potentially large) summary blob and the parameters
    blob; callers fetch the full record via GET /{id} when they need it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vas_bookmark_id: str
    model_id: str
    model_version: str | None
    state: BookmarkAnalysisStateName
    created_at: datetime
    completed_at: datetime | None


class BookmarkAnalysisListResponse(BaseModel):
    """List response wrapper used by both list endpoints."""

    items: list[BookmarkAnalysisListItem]
    total: int

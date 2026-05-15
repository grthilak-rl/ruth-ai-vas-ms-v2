"""Pydantic schemas for the bookmark analysis API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Mirrors models.enums.BookmarkAnalysisState. Kept as a Literal here
# rather than importing the enum so the OpenAPI schema renders as a
# clean string enum without Python type leakage.
BookmarkAnalysisStateName = Literal["pending", "running", "completed", "failed"]


# Sampling rate bounds for the analyses worker. Below 0.1 fps is too
# coarse to call "analysis"; above 10 fps is wasteful (tank overflow
# is classical CV but each frame still costs an HTTP roundtrip).
SAMPLING_FPS_MIN = 0.1
SAMPLING_FPS_MAX = 10.0
SAMPLING_FPS_DEFAULT = 1.0


def _validate_tank_corners(value: Any) -> None:
    """Tank overflow needs four [x, y] points to crop the tank ROI.

    Pydantic raises ValueError with the message; the route layer maps
    that to HTTP 400 via the existing validation-error handler.
    """
    if value is None:
        raise ValueError(
            "tank_overflow_monitoring requires parameters.tank_corners "
            "(four [x, y] points defining the tank ROI)."
        )
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(
            "tank_corners must be a list of exactly four [x, y] points."
        )
    for i, pt in enumerate(value):
        if (
            not isinstance(pt, list)
            or len(pt) != 2
            or not all(isinstance(c, (int, float)) for c in pt)
        ):
            raise ValueError(
                f"tank_corners[{i}] must be a [x, y] pair of numbers."
            )


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
            "alert_threshold for tank_overflow_monitoring; sampling_fps for "
            "all models). Passed verbatim to the analysis worker."
        ),
    )

    @model_validator(mode="after")
    def _validate_parameters(self) -> "BookmarkAnalysisSubmitRequest":
        params = self.parameters or {}

        # sampling_fps is universal across models. Validate range here so
        # we don't waste a worker startup on bad input.
        sampling_fps = params.get("sampling_fps", SAMPLING_FPS_DEFAULT)
        if not isinstance(sampling_fps, (int, float)):
            raise ValueError("parameters.sampling_fps must be a number.")
        if not (SAMPLING_FPS_MIN <= float(sampling_fps) <= SAMPLING_FPS_MAX):
            raise ValueError(
                f"parameters.sampling_fps must be between "
                f"{SAMPLING_FPS_MIN} and {SAMPLING_FPS_MAX}."
            )

        # Model-specific required parameters. Structured so adding more
        # models later is straightforward — extend with another branch.
        if self.model_id == "tank_overflow_monitoring":
            _validate_tank_corners(params.get("tank_corners"))

        return self


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

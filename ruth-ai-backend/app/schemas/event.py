"""Pydantic schemas for event API endpoints.

From API Contract - Event APIs.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BoundingBoxInput(BaseModel):
    """Bounding box from AI inference.

    Note: Input uses 'w' and 'h' for width/height as per payload spec.
    """

    x: int = Field(..., description="X coordinate of top-left corner")
    y: int = Field(..., description="Y coordinate of top-left corner")
    w: int = Field(..., alias="w", description="Width of bounding box")
    h: int = Field(..., alias="h", description="Height of bounding box")

    model_config = {"populate_by_name": True}


class BoundingBoxResponse(BaseModel):
    """Bounding box in response format."""

    x: int = Field(..., description="X coordinate")
    y: int = Field(..., description="Y coordinate")
    width: int = Field(..., description="Width")
    height: int = Field(..., description="Height")
    label: str | None = Field(None, description="Detection label")
    confidence: float | None = Field(None, description="Detection confidence")


class EventIngestRequest(BaseModel):
    """Request schema for POST /internal/events.

    Simulates AI Runtime inference payload.
    """

    device_id: uuid.UUID = Field(..., description="Device/camera UUID")
    stream_session_id: uuid.UUID | None = Field(
        None, description="Stream session UUID (optional)"
    )
    vas_stream_id: str | None = Field(
        None, description="VAS stream ID for snapshot capture (optional)"
    )
    event_type: str = Field(..., description="Event type (e.g., fall_detected)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    timestamp: datetime = Field(..., description="Event timestamp (ISO 8601)")
    model_id: str = Field(..., description="AI model identifier")
    model_version: str = Field(..., description="AI model version")
    bounding_boxes: list[BoundingBoxInput] | None = Field(
        None, description="Detected object bounding boxes"
    )


class EventResponse(BaseModel):
    """Response schema for a single event."""

    id: uuid.UUID = Field(..., description="Event UUID")
    device_id: uuid.UUID = Field(..., description="Device/camera UUID")
    stream_session_id: uuid.UUID | None = Field(None, description="Stream session UUID")
    event_type: str = Field(..., description="Event type")
    confidence: float = Field(..., description="Detection confidence")
    timestamp: datetime = Field(..., description="Event timestamp")
    model_id: str = Field(..., description="AI model identifier")
    model_version: str = Field(..., description="AI model version")
    bounding_boxes: list[dict] | None = Field(None, description="Bounding boxes")
    frame_id: str | None = Field(None, description="Frame reference")
    inference_time_ms: int | None = Field(None, description="Inference time in ms")
    violation_id: uuid.UUID | None = Field(
        None, description="Associated violation UUID"
    )
    created_at: datetime = Field(..., description="Record creation timestamp")

    model_config = {"from_attributes": True}


class EventListResponse(BaseModel):
    """Response schema for GET /api/v1/events."""

    events: list[EventResponse] = Field(..., description="List of events")
    total: int = Field(..., description="Total count of events")


class EventQueryParams(BaseModel):
    """Query parameters for GET /api/v1/events."""

    device_id: uuid.UUID | None = Field(None, description="Filter by device")
    event_type: str | None = Field(None, description="Filter by event type")
    since: datetime | None = Field(None, description="Filter by timestamp (after)")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")

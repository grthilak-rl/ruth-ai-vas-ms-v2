"""Pydantic schemas for device API endpoints.

Aligned with F6 Frontend Data Contracts.
From API Contract - Device & Stream APIs.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DeviceStreaming(BaseModel):
    """Streaming status for a device.

    Aligned with F6 §4.4 DeviceStreaming interface.
    Note: vas_stream_id exposed to enable frontend video playback via VAS HLS/WebRTC.
    """

    active: bool = Field(..., description="Whether stream is active")
    stream_id: str | None = Field(None, description="VAS stream ID for video playback")
    state: str | None = Field(None, description="Stream state (live, stopped, etc.)")
    ai_enabled: bool = Field(False, description="Whether AI detection is enabled")
    model_id: str | None = Field(None, description="AI model being used")


class Device(BaseModel):
    """Device/Camera entity.

    Aligned with F6 §4.4 Device interface.
    Note: vas_device_id is intentionally excluded from public API
    per API Contract - "These endpoints do NOT expose VAS internals."
    """

    id: uuid.UUID = Field(..., description="Ruth AI internal device UUID")
    name: str = Field(..., description="Device display name")
    is_active: bool = Field(..., description="Whether device is active")
    streaming: DeviceStreaming = Field(..., description="Streaming and inference status")

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    """Response schema for GET /api/v1/devices.

    Aligned with F6 DevicesListResponse interface.
    """

    items: list[Device] = Field(..., description="List of devices")
    total: int = Field(..., description="Total count of devices")


# Legacy response for internal use (preserves additional fields)
class DeviceDetailResponse(BaseModel):
    """Response schema for GET /api/v1/devices/{id}.

    Extended device info with additional metadata.
    """

    id: uuid.UUID = Field(..., description="Ruth AI internal device UUID")
    name: str = Field(..., description="Device display name")
    description: str | None = Field(None, description="Device description")
    location: str | None = Field(None, description="Physical location")
    is_active: bool = Field(..., description="Whether device is active")
    streaming: DeviceStreaming = Field(..., description="Streaming and inference status")
    last_synced_at: datetime | None = Field(
        None, description="Last VAS sync timestamp"
    )
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record update timestamp")


class InferenceStartRequest(BaseModel):
    """Request schema for POST /api/v1/devices/{id}/start-inference."""

    model_id: str = Field(
        default="fall_detection",
        description="AI model to use for inference",
    )
    model_version: str | None = Field(
        None, description="Specific model version (optional)"
    )
    inference_fps: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Frames per second for inference",
    )
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold",
    )


class InferenceStartResponse(BaseModel):
    """Response schema for POST /api/v1/devices/{id}/start-inference.

    Note: vas_stream_id is intentionally excluded from public API
    per API Contract - "No VAS-internal details exposed."
    """

    session_id: uuid.UUID = Field(..., description="Stream session UUID")
    device_id: uuid.UUID = Field(..., description="Device UUID")
    state: str = Field(..., description="Stream state (live, starting, etc.)")
    model_id: str = Field(..., description="AI model being used")
    started_at: datetime = Field(..., description="Session start timestamp")


class InferenceStopResponse(BaseModel):
    """Response schema for POST /api/v1/devices/{id}/stop-inference."""

    session_id: uuid.UUID = Field(..., description="Stream session UUID")
    device_id: uuid.UUID = Field(..., description="Device UUID")
    state: str = Field(..., description="Stream state (stopped)")
    stopped_at: datetime | None = Field(None, description="Session stop timestamp")

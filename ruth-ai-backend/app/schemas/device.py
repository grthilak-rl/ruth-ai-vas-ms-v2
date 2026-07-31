"""Pydantic schemas for device API endpoints.

Aligned with F6 Frontend Data Contracts.
From API Contract - Device & Stream APIs.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceStreaming(BaseModel):
    """Streaming status for a device.

    Aligned with F6 §4.4 DeviceStreaming interface.
    Note: vas_stream_id exposed to enable frontend video playback via VAS HLS/WebRTC.

    Two status dimensions:
    - video_live: Whether VAS video stream is live (from VAS)
    - ai_enabled: Whether AI detection inference is running (from Ruth AI session)
    """

    # VAS video stream status
    video_live: bool = Field(False, description="Whether VAS video stream is live")
    stream_id: str | None = Field(None, description="VAS stream ID for video playback")

    # AI inference status (Ruth AI session)
    active: bool = Field(..., description="Whether AI inference session is active")
    state: str | None = Field(None, description="AI session state (live, stopped, etc.)")
    ai_enabled: bool = Field(False, description="Whether AI detection is enabled")
    model_id: str | None = Field(None, description="AI model being used")
    # Note: Named ai_model_config to avoid conflict with Pydantic's reserved 'model_config'
    # but serialized as 'model_config' in JSON for API compatibility
    ai_model_config: dict | None = Field(
        None,
        description="Model-specific configuration (e.g., zones for geo_fencing)",
        serialization_alias="model_config",
    )


class Device(BaseModel):
    """Device/Camera entity.

    Aligned with F6 §4.4 Device interface.
    Note: vas_device_id is intentionally excluded from public API
    per API Contract - "These endpoints do NOT expose VAS internals."
    """

    id: uuid.UUID = Field(..., description="Ruth AI internal device UUID")
    name: str = Field(..., description="Stable device identifier (e.g. CUG3PTZ10072)")
    display_name: str | None = Field(
        None,
        description=(
            "Operator-facing name from VAS, derived as "
            "<manway>_<IN|OUT>_<identifier>. NULL for devices not yet re-synced "
            "since structured naming shipped; clients should render "
            "`display_name or name`."
        ),
    )
    manway: str | None = Field(None, description="Grouping key from VAS, e.g. TANK5")
    in_out: str | None = Field(None, description="IN or OUT, if set in VAS")
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
    config: dict | None = Field(
        None,
        description="Model-specific configuration (e.g., tank_corners for tank monitoring, ROI zones for PPE detection)",
        examples=[
            {
                "tank_corners": [[316, 382], [291, 531], [384, 591], [465, 464]],
                "capacity_liters": 1000,
                "alert_threshold": 90
            }
        ],
        alias="model_config",
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


class ModelConfigUpdateRequest(BaseModel):
    """Request schema for PATCH /api/v1/devices/{id}/model-config."""

    config: dict = Field(
        ...,
        description="Model-specific configuration (e.g., zones for geo_fencing, tank_corners for tank monitoring)",
        examples=[
            {
                "zones": [
                    {
                        "id": "zone_1",
                        "name": "Restricted Zone",
                        "points": [[100, 100], [500, 100], [500, 400], [100, 400]],
                        "type": "restricted"
                    }
                ]
            }
        ],
        alias="model_config",
    )


class ModelConfigUpdateResponse(BaseModel):
    """Response schema for PATCH /api/v1/devices/{id}/model-config."""

    session_id: uuid.UUID = Field(..., description="Stream session UUID")
    device_id: uuid.UUID = Field(..., description="Device UUID")
    model_id: str = Field(..., description="AI model ID")
    config_updated: bool = Field(..., description="Whether config was updated")


class DeviceNamingUpdateRequest(BaseModel):
    """Request schema for PATCH /api/v1/devices/{id}/naming.

    Structured naming fields, written through to VAS (the source of truth).
    Ruth does not own these values — it forwards them and mirrors the result.

    Both fields are optional and distinguishable three ways, which is why the
    endpoint inspects ``model_fields_set`` rather than checking for None:

        omitted        leave the field as it is in VAS
        explicit null  clear the field
        value          set the field

    ``display_name`` is deliberately absent: it is DERIVED by VAS from these
    two fields plus the device identifier, and is never client-supplied.
    """

    manway: str | None = Field(
        None,
        max_length=64,
        description="Grouping key, e.g. TANK5. Null clears it. Uppercased by VAS.",
    )
    in_out: Literal["IN", "OUT"] | None = Field(
        None,
        description="Which side of the manway the camera watches. Null clears it.",
    )


class DeviceNamingUpdateResponse(BaseModel):
    """Response schema for PATCH /api/v1/devices/{id}/naming.

    Values are echoed back as VAS returned them (manway normalized,
    display_name re-derived), so the client renders what VAS actually stored
    rather than its own optimistic guess.
    """

    device_id: uuid.UUID = Field(..., description="Ruth AI internal device UUID")
    name: str = Field(..., description="Stable device identifier, unchanged")
    manway: str | None = Field(None, description="Grouping key as stored by VAS")
    in_out: str | None = Field(None, description="IN or OUT as stored by VAS")
    display_name: str = Field(..., description="Name derived by VAS")


class ManwayListResponse(BaseModel):
    """Response schema for GET /api/v1/devices/manways."""

    manways: list[str] = Field(
        default_factory=list,
        description="Distinct manway values in use, for autocomplete",
    )

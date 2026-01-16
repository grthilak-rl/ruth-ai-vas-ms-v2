"""VAS API response models.

Pydantic models for VAS API responses with strict validation.
All models use lowercase enum values to match actual VAS behavior.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Enums (lowercase to match VAS actual behavior)
# -----------------------------------------------------------------------------


class StreamState(str, Enum):
    """Stream lifecycle states.

    Note: VAS returns lowercase values despite docs showing uppercase.
    """

    INITIALIZING = "initializing"
    READY = "ready"
    LIVE = "live"
    ERROR = "error"
    STOPPED = "stopped"
    CLOSED = "closed"

    # Also accept uppercase for compatibility
    @classmethod
    def _missing_(cls, value: str) -> "StreamState | None":
        if isinstance(value, str):
            lower = value.lower()
            for member in cls:
                if member.value == lower:
                    return member
        return None


class BookmarkStatus(str, Enum):
    """Bookmark processing status."""

    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SnapshotStatus(str, Enum):
    """Snapshot processing status."""

    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SnapshotSource(str, Enum):
    """Snapshot source type."""

    LIVE = "live"
    HISTORICAL = "historical"


class BookmarkSource(str, Enum):
    """Bookmark source type."""

    LIVE = "live"
    HISTORICAL = "historical"


# -----------------------------------------------------------------------------
# Authentication Models
# -----------------------------------------------------------------------------


class TokenResponse(BaseModel):
    """Response from POST /v2/auth/token."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Token lifetime in seconds")
    refresh_token: str | None = None
    scopes: list[str] = Field(default_factory=list)


class TokenRefreshResponse(BaseModel):
    """Response from POST /v2/auth/token/refresh."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scopes: list[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Device Models (V1 API)
# -----------------------------------------------------------------------------


class DeviceStreamingStatus(BaseModel):
    """Streaming status within device status response."""

    active: bool
    room_id: str | None = None
    started_at: datetime | None = None


class Device(BaseModel):
    """Device resource from VAS API."""

    id: str
    name: str
    description: str | None = None
    rtsp_url: str | None = None
    is_active: bool = False
    location: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DeviceStatus(BaseModel):
    """Response from GET /api/v1/devices/{id}/status."""

    device_id: str
    name: str
    description: str | None = None
    location: str | None = None
    rtsp_url: str | None = None
    is_active: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    streaming: DeviceStreamingStatus | None = None


class StreamStartResponse(BaseModel):
    """Response from POST /api/v1/devices/{id}/start-stream."""

    status: str
    device_id: str
    room_id: str | None = None
    transport_id: str | None = None
    producers: dict[str, str] | None = None
    stream: dict[str, Any] | None = None
    v2_stream_id: str | None = None
    reconnect: bool = False


class StreamStopResponse(BaseModel):
    """Response from POST /api/v1/devices/{id}/stop-stream."""

    status: str
    device_id: str
    stopped: bool = True


# -----------------------------------------------------------------------------
# Stream Models (V2 API)
# -----------------------------------------------------------------------------


class StreamEndpoints(BaseModel):
    """Stream endpoint URLs."""

    webrtc: str | None = None
    hls: str | None = None
    health: str | None = None


class StreamProducer(BaseModel):
    """MediaSoup producer info."""

    id: str | None = None
    mediasoup_id: str | None = None
    state: str | None = None
    ssrc: int | None = None


class StreamConsumerStats(BaseModel):
    """Consumer statistics for a stream."""

    count: int = 0
    active: int = 0


class StreamCodecConfig(BaseModel):
    """Stream codec configuration."""

    video: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None


class Stream(BaseModel):
    """Stream resource from V2 API."""

    id: str
    name: str | None = None
    camera_id: str | None = None
    state: StreamState
    codec_config: StreamCodecConfig | None = None
    producer: StreamProducer | None = None
    consumers: StreamConsumerStats | None = None
    endpoints: StreamEndpoints | None = None
    created_at: datetime | None = None
    uptime_seconds: int | None = None


class StreamListPagination(BaseModel):
    """Pagination info for stream list."""

    total: int = 0
    limit: int = 50
    offset: int = 0


class StreamListResponse(BaseModel):
    """Response from GET /v2/streams."""

    streams: list[Stream] = Field(default_factory=list)
    pagination: StreamListPagination | None = None


class StreamHealthMetrics(BaseModel):
    """Health metrics for a stream."""

    bitrate_kbps: int | None = None
    fps: int | None = None
    packet_loss: float | None = None
    jitter_ms: float | None = None


class StreamHealth(BaseModel):
    """Response from GET /v2/streams/{id}/health."""

    stream_id: str
    state: StreamState
    is_healthy: bool
    uptime_seconds: int | None = None
    metrics: StreamHealthMetrics | None = None
    last_error: str | None = None
    checked_at: datetime | None = None


# -----------------------------------------------------------------------------
# Snapshot Models
# -----------------------------------------------------------------------------


class Snapshot(BaseModel):
    """Snapshot resource from VAS API."""

    id: str
    stream_id: str
    timestamp: datetime | None = None
    source: SnapshotSource | None = None
    created_by: str | None = None
    format: str | None = None
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    image_url: str | None = None
    metadata: dict[str, Any] | None = None
    status: SnapshotStatus | None = None
    error: str | None = None
    created_at: datetime | None = None


class SnapshotListResponse(BaseModel):
    """Response from GET /v2/snapshots."""

    snapshots: list[Snapshot] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class SnapshotCreateRequest(BaseModel):
    """Request body for POST /v2/streams/{id}/snapshots."""

    source: SnapshotSource = SnapshotSource.LIVE
    timestamp: datetime | None = None
    created_by: str | None = None
    metadata: dict[str, Any] | None = None


# -----------------------------------------------------------------------------
# Bookmark Models
# -----------------------------------------------------------------------------


class Bookmark(BaseModel):
    """Bookmark resource from VAS API."""

    id: str
    stream_id: str
    center_timestamp: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: float | None = None
    source: BookmarkSource | None = None
    label: str | None = None
    created_by: str | None = None
    event_type: str | None = None
    confidence: float | None = None
    tags: list[str] | None = None
    video_url: str | None = None
    thumbnail_url: str | None = None
    status: BookmarkStatus | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class BookmarkListResponse(BaseModel):
    """Response from GET /v2/bookmarks."""

    bookmarks: list[Bookmark] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class BookmarkCreateRequest(BaseModel):
    """Request body for POST /v2/streams/{id}/bookmarks."""

    source: BookmarkSource = BookmarkSource.LIVE
    label: str | None = None
    event_type: str | None = None
    confidence: float | None = None
    before_seconds: int = 5
    after_seconds: int = 10
    center_timestamp: datetime | None = None
    tags: list[str] | None = None
    created_by: str | None = None
    metadata: dict[str, Any] | None = None


# -----------------------------------------------------------------------------
# Error Response Model
# -----------------------------------------------------------------------------


class VASErrorResponse(BaseModel):
    """Standardized VAS error response."""

    error: str
    error_description: str
    status_code: int
    details: dict[str, Any] | None = None
    request_id: str | None = None
    timestamp: datetime | None = None

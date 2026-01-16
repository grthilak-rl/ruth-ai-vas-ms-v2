"""Pydantic models for VAS-MS-V2 API responses"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class StreamState(str, Enum):
    # Support both uppercase (documented) and lowercase (actual API)
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    LIVE = "LIVE"
    ERROR = "ERROR"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"
    # Lowercase variants (actual API returns these)
    initializing = "initializing"
    ready = "ready"
    live = "live"
    error = "error"
    stopped = "stopped"
    closed = "closed"

    @classmethod
    def normalize(cls, value: str) -> "StreamState":
        """Normalize state value to uppercase enum"""
        return cls(value.upper()) if value.lower() in [e.value.lower() for e in cls] else cls(value)


class SnapshotSource(str, Enum):
    LIVE = "live"
    HISTORICAL = "historical"


class BookmarkSource(str, Enum):
    LIVE = "live"
    HISTORICAL = "historical"


class ProcessingStatus(str, Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


# Authentication Models
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str
    scopes: List[str] = []


# Device Models (V1 API)
class Device(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    rtsp_url: str
    is_active: bool = True
    location: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class DeviceValidation(BaseModel):
    valid: bool
    rtsp_url: str
    ssrc: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


class StreamStartResponse(BaseModel):
    status: str
    device_id: str
    room_id: Optional[str] = None
    transport_id: Optional[str] = None
    producers: Optional[Dict[str, str]] = None
    stream: Optional[Dict[str, Any]] = None
    v2_stream_id: Optional[str] = None
    reconnect: bool = False

    @property
    def effective_stream_id(self) -> Optional[str]:
        """Get stream ID regardless of field name used"""
        if self.v2_stream_id:
            return self.v2_stream_id
        if self.stream and "stream_id" in self.stream:
            return self.stream["stream_id"]
        if self.stream and "id" in self.stream:
            return self.stream["id"]
        return None


class StreamStopResponse(BaseModel):
    status: str
    device_id: str
    stopped: bool


# Stream Models (V2 API)
class StreamEndpoints(BaseModel):
    webrtc: Optional[str] = None
    hls: Optional[str] = None
    health: Optional[str] = None


class CodecConfig(BaseModel):
    codec: str = "H264"
    profile: Optional[str] = None
    payloadType: Optional[int] = None


class Producer(BaseModel):
    id: str
    mediasoup_id: Optional[str] = None
    state: str
    ssrc: Optional[int] = None


class ConsumerCount(BaseModel):
    count: int
    active: int


class Stream(BaseModel):
    id: str
    name: Optional[str] = None
    camera_id: str
    state: StreamState
    codec_config: Optional[Dict[str, Any]] = None
    producer: Optional[Producer] = None
    consumers: Optional[ConsumerCount] = None
    endpoints: Optional[StreamEndpoints] = None
    created_at: datetime
    uptime_seconds: Optional[int] = None


class StreamListResponse(BaseModel):
    streams: List[Stream]
    pagination: Dict[str, int]


class StreamHealth(BaseModel):
    """Stream health response - matches actual API response"""
    status: str  # "healthy", "degraded", "unhealthy"
    state: StreamState
    producer: Optional[Dict[str, Any]] = None
    consumers: Optional[Dict[str, Any]] = None
    ffmpeg: Optional[Dict[str, Any]] = None  # {'status': 'running'} or similar
    recording: Optional[Dict[str, Any]] = None
    # Legacy fields (optional for backwards compatibility)
    stream_id: Optional[str] = None
    is_healthy: Optional[bool] = None
    uptime_seconds: Optional[int] = None
    metrics: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None
    checked_at: Optional[datetime] = None

    @property
    def healthy(self) -> bool:
        """Check if stream is healthy based on status"""
        return self.status == "healthy"


# WebRTC Consumer Models
class ICECandidate(BaseModel):
    foundation: str
    priority: int
    ip: str
    port: int
    type: str
    protocol: str


class ICEParameters(BaseModel):
    usernameFragment: str
    password: str


class DTLSFingerprint(BaseModel):
    algorithm: str
    value: str


class DTLSParameters(BaseModel):
    role: str
    fingerprints: List[DTLSFingerprint]


class Transport(BaseModel):
    id: str
    ice_parameters: ICEParameters
    ice_candidates: List[ICECandidate]
    dtls_parameters: DTLSParameters


class RTPParameters(BaseModel):
    codecs: List[Dict[str, Any]]
    encodings: List[Dict[str, Any]]


class Consumer(BaseModel):
    consumer_id: str
    transport: Transport
    rtp_parameters: RTPParameters


class ConsumerInfo(BaseModel):
    id: str
    client_id: str
    state: str
    created_at: datetime
    last_seen_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class ConsumerListResponse(BaseModel):
    stream_id: str
    total_consumers: int
    active_consumers: int
    consumers: List[ConsumerInfo]


class ConnectResponse(BaseModel):
    status: str
    consumer_id: str
    transport_id: str


# Snapshot Models
class Snapshot(BaseModel):
    id: str
    stream_id: str
    timestamp: datetime
    source: SnapshotSource
    created_by: str
    format: str = "jpg"
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    image_url: Optional[str] = None
    metadata: Dict[str, Any] = {}
    status: ProcessingStatus = ProcessingStatus.PROCESSING
    created_at: datetime


class SnapshotListResponse(BaseModel):
    snapshots: List[Snapshot]
    pagination: Dict[str, int]


# Bookmark Models
class Bookmark(BaseModel):
    id: str
    stream_id: str
    center_timestamp: datetime
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    source: BookmarkSource
    label: Optional[str] = None  # Can be null in existing bookmarks
    created_by: Optional[str] = None
    event_type: Optional[str] = None  # Can be null in existing bookmarks
    confidence: Optional[float] = None
    tags: List[str] = []
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: ProcessingStatus = ProcessingStatus.PROCESSING
    metadata: Dict[str, Any] = {}
    created_at: datetime


class BookmarkListResponse(BaseModel):
    bookmarks: List[Bookmark]
    pagination: Dict[str, int]


# Error Models
class VASErrorDetails(BaseModel):
    error: str
    error_description: str
    status_code: int
    details: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
    timestamp: Optional[datetime] = None


class VASError(Exception):
    """Exception raised for VAS API errors"""

    def __init__(self, status_code: int, error: str, description: str, details: Optional[Dict] = None):
        self.status_code = status_code
        self.error = error
        self.description = description
        self.details = details or {}
        super().__init__(f"[{status_code}] {error}: {description}")

    @property
    def is_retryable(self) -> bool:
        """Check if this error is retryable based on status code"""
        return self.status_code in [401, 409, 429, 502, 503, 504]

    @property
    def needs_token_refresh(self) -> bool:
        """Check if error indicates token needs refresh"""
        return self.status_code == 401 and self.error in ["INVALID_TOKEN", "TOKEN_EXPIRED"]


# Router Capabilities Models
class RTPCodec(BaseModel):
    mimeType: str
    kind: str
    clockRate: int
    parameters: Dict[str, Any] = {}
    rtcpFeedback: List[Dict[str, str]] = []


class RouterCapabilities(BaseModel):
    codecs: List[RTPCodec]
    headerExtensions: List[Dict[str, Any]] = []

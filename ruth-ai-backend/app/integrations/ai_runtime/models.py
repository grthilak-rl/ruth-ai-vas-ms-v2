"""AI Runtime request/response models.

Pydantic models for AI Runtime API communication.
These models are transport-agnostic and represent the
logical contract between backend and AI Runtime.

The backend treats these as opaque data structures -
it does not interpret inference results beyond routing
them to the appropriate handlers.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class HardwareType(str, Enum):
    """Hardware type reported by AI Runtime.

    Backend uses this ONLY for logging/metrics - never for branching logic.
    """

    CPU = "cpu"
    GPU = "gpu"
    JETSON = "jetson"
    UNKNOWN = "unknown"


class RuntimeStatus(str, Enum):
    """AI Runtime operational status."""

    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    DEGRADED = "degraded"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class InferenceStatus(str, Enum):
    """Status of an inference request."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ModelStatus(str, Enum):
    """Status of a model on the runtime."""

    LOADING = "loading"
    READY = "ready"
    ERROR = "error"
    UNLOADED = "unloaded"


# -----------------------------------------------------------------------------
# Capability Models
# -----------------------------------------------------------------------------


class ModelCapability(BaseModel):
    """Capability declaration for a single model."""

    model_id: str = Field(description="Unique model identifier")
    version: str = Field(description="Model version string")
    status: ModelStatus = Field(default=ModelStatus.READY)
    input_types: list[str] = Field(
        default_factory=lambda: ["frame_reference"],
        description="Supported input types",
    )
    output_types: list[str] = Field(
        default_factory=lambda: ["detections"],
        description="Output types produced",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Model-specific metadata",
    )


class RuntimeCapabilities(BaseModel):
    """AI Runtime capability declaration.

    This is registered by the runtime with the backend.
    Backend caches and uses this to route requests appropriately.
    """

    runtime_id: str = Field(description="Unique runtime instance identifier")
    hardware_type: HardwareType = Field(
        default=HardwareType.UNKNOWN,
        description="Hardware type (for logging only)",
    )
    max_fps: int = Field(
        default=30,
        ge=1,
        le=1000,
        description="Maximum frames per second capacity",
    )
    max_concurrent_streams: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Maximum concurrent stream processing",
    )
    batch_size: int = Field(
        default=1,
        ge=1,
        le=64,
        description="Optimal batch size for inference",
    )
    supported_models: list[ModelCapability] = Field(
        default_factory=list,
        description="List of available models",
    )
    registered_at: datetime | None = Field(
        default=None,
        description="When capabilities were registered",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional runtime metadata",
    )

    def has_model(self, model_id: str, version: str | None = None) -> bool:
        """Check if runtime supports a specific model."""
        for model in self.supported_models:
            if model.model_id == model_id:
                if version is None or model.version == version:
                    return model.status == ModelStatus.READY
        return False

    def get_model(self, model_id: str) -> ModelCapability | None:
        """Get model capability by ID."""
        for model in self.supported_models:
            if model.model_id == model_id:
                return model
        return None


class CapabilityRegistrationRequest(BaseModel):
    """Request to register runtime capabilities."""

    capabilities: RuntimeCapabilities


class CapabilityRegistrationResponse(BaseModel):
    """Response to capability registration."""

    success: bool
    runtime_id: str
    registered_at: datetime
    message: str | None = None


# -----------------------------------------------------------------------------
# Inference Models
# -----------------------------------------------------------------------------


class BoundingBox(BaseModel):
    """Bounding box for a detection."""

    x: int = Field(ge=0, description="Left edge x coordinate")
    y: int = Field(ge=0, description="Top edge y coordinate")
    width: int = Field(gt=0, description="Box width")
    height: int = Field(gt=0, description="Box height")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Detection confidence",
    )


class Detection(BaseModel):
    """Single detection result from inference.

    Backend treats this as opaque data - it does not
    interpret the detection beyond routing to handlers.
    """

    detection_id: str = Field(description="Unique detection identifier")
    class_name: str = Field(description="Detected class/label")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Detection confidence score",
    )
    bounding_box: BoundingBox | None = Field(
        default=None,
        description="Detection bounding box if applicable",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional detection attributes",
    )


class InferenceRequest(BaseModel):
    """Request to submit inference to AI Runtime.

    The backend submits frame references, NOT raw frames.
    Frame references are opaque identifiers managed by VAS.
    """

    request_id: UUID = Field(description="Unique request identifier")
    stream_id: UUID = Field(description="Source stream identifier")
    device_id: UUID | None = Field(
        default=None,
        description="Source device identifier",
    )
    frame_reference: str = Field(
        description="Opaque frame reference (VAS-managed)",
    )
    timestamp: datetime = Field(description="Frame timestamp")
    model_id: str = Field(
        default="fall_detection",
        description="Target model identifier",
    )
    model_version: str | None = Field(
        default=None,
        description="Specific model version (optional)",
    )
    priority: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Request priority (0=normal, 10=highest)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional request metadata",
    )


class InferenceResponse(BaseModel):
    """Response from AI Runtime inference.

    Backend receives this and routes to event ingestion.
    """

    request_id: UUID = Field(description="Original request identifier")
    stream_id: UUID = Field(description="Source stream identifier")
    device_id: UUID | None = Field(default=None)
    status: InferenceStatus = Field(description="Inference status")
    timestamp: datetime = Field(description="Frame timestamp")
    processed_at: datetime | None = Field(
        default=None,
        description="When inference completed",
    )
    model_id: str = Field(description="Model that performed inference")
    model_version: str | None = Field(default=None)
    detections: list[Detection] = Field(
        default_factory=list,
        description="Detection results",
    )
    inference_time_ms: float | None = Field(
        default=None,
        ge=0,
        description="Inference duration in milliseconds",
    )
    error: str | None = Field(
        default=None,
        description="Error message if status is FAILED",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional response metadata",
    )

    @property
    def has_detections(self) -> bool:
        """Check if inference produced any detections."""
        return len(self.detections) > 0

    @property
    def max_confidence(self) -> float:
        """Get maximum confidence among all detections."""
        if not self.detections:
            return 0.0
        return max(d.confidence for d in self.detections)


# -----------------------------------------------------------------------------
# Health Models
# -----------------------------------------------------------------------------


class ModelHealth(BaseModel):
    """Health status for a single model."""

    model_id: str
    version: str
    status: ModelStatus
    loaded: bool = False
    last_inference_at: datetime | None = None
    inference_count: int = 0
    error_count: int = 0
    average_latency_ms: float | None = None


class RuntimeHealth(BaseModel):
    """AI Runtime health status.

    Used for health checks and monitoring.
    """

    runtime_id: str
    status: RuntimeStatus
    is_healthy: bool = Field(description="Overall health indicator")
    uptime_seconds: float | None = None
    hardware_type: HardwareType = HardwareType.UNKNOWN
    current_load: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Current load (0.0-1.0)",
    )
    active_streams: int = Field(default=0, ge=0)
    queue_depth: int = Field(default=0, ge=0)
    models: list[ModelHealth] = Field(default_factory=list)
    last_inference_at: datetime | None = None
    error: str | None = None
    checked_at: datetime | None = None


class HealthCheckRequest(BaseModel):
    """Request for health check."""

    include_models: bool = Field(
        default=True,
        description="Include individual model health",
    )


class HealthCheckResponse(BaseModel):
    """Response from health check."""

    health: RuntimeHealth

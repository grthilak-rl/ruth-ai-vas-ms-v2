"""Inference domain types.

These types represent the internal contract for inference results
flowing from the AI runtime into the event ingestion pipeline.
They are runtime-agnostic — the unified runtime client maps its
responses into these types before handing them to services.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class InferenceStatus(str, Enum):
    """Status of an inference request."""

    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class BoundingBox(BaseModel):
    """Bounding box for a detection."""

    x: float
    y: float
    width: float
    height: float
    confidence: float = 0.0


class Detection(BaseModel):
    """A single detection from an inference result."""

    detection_id: str = ""
    class_name: str
    confidence: float
    bounding_box: Optional[BoundingBox] = None


class InferenceResponse(BaseModel):
    """Normalized inference response from the AI runtime."""

    request_id: UUID
    stream_id: UUID
    device_id: Optional[UUID] = None
    status: InferenceStatus = InferenceStatus.COMPLETED
    timestamp: datetime
    model_id: str = "fall_detection"
    model_version: Optional[str] = "1.0.0"
    detections: list[Detection] = Field(default_factory=list)
    inference_time_ms: Optional[float] = None
    error: Optional[str] = None

    @property
    def has_detections(self) -> bool:
        """Check if there are any detections."""
        return len(self.detections) > 0

    @property
    def max_confidence(self) -> float:
        """Get maximum detection confidence."""
        if not self.detections:
            return 0.0
        return max(d.confidence for d in self.detections)

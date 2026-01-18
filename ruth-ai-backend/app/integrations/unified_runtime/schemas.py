"""
Unified Runtime API Schemas

Pydantic models for unified runtime requests and responses.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class UnifiedInferenceRequest(BaseModel):
    """Request schema for unified runtime inference endpoint."""

    stream_id: UUID = Field(description="Source stream UUID")
    device_id: Optional[UUID] = Field(None, description="Source device UUID")
    model_id: str = Field(description="Target model identifier")
    model_version: Optional[str] = Field(None, description="Specific model version")

    # Phase 2: Accept base64-encoded frame data instead of reference
    frame_base64: str = Field(description="Base64-encoded frame image data")
    frame_format: str = Field(default="jpeg", description="Image format: jpeg, png")
    frame_width: Optional[int] = Field(None, description="Image width in pixels")
    frame_height: Optional[int] = Field(None, description="Image height in pixels")

    timestamp: datetime = Field(description="Frame capture timestamp")
    priority: int = Field(default=0, ge=0, le=10, description="Request priority")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "stream_id": "550e8400-e29b-41d4-a716-446655440000",
                "device_id": "660e8400-e29b-41d4-a716-446655440001",
                "model_id": "fall_detection",
                "frame_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "frame_format": "jpeg",
                "frame_width": 1920,
                "frame_height": 1080,
                "timestamp": "2026-01-18T12:00:00Z",
                "priority": 5,
            }
        }


class UnifiedInferenceResponse(BaseModel):
    """Response schema from unified runtime inference endpoint."""

    request_id: UUID = Field(description="Unique request identifier")
    status: str = Field(description="Status: success or failed")
    model_id: str = Field(description="Model that processed the request")
    model_version: str = Field(description="Model version used")
    inference_time_ms: float = Field(description="Inference duration in milliseconds")
    result: Optional[Dict[str, Any]] = Field(None, description="Inference results")
    error: Optional[str] = Field(None, description="Error message if failed")

    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "770e8400-e29b-41d4-a716-446655440002",
                "status": "success",
                "model_id": "fall_detection",
                "model_version": "1.0.0",
                "inference_time_ms": 150.5,
                "result": {
                    "violation_detected": True,
                    "violation_type": "fall_detected",
                    "confidence": 0.92,
                    "detections": [],
                },
            }
        }

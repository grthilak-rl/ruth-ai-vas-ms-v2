"""
Ruth AI Unified Runtime - Inference Endpoint

Accepts base64-encoded frames and routes to appropriate models for inference.
"""

import base64
import io
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, status
from PIL import Image
from pydantic import BaseModel, Field

from ai.server.dependencies import get_pipeline, get_registry, get_sandbox_manager
from ai.runtime.errors import ModelError, PipelineError, ExecutionError
from ai.observability.logging import get_logger
from ai.observability.metrics import (
    record_inference,
    record_inference_latency,
    record_frame_decode_latency,
    record_frame_size,
)

router = APIRouter()
logger = get_logger(__name__)


class InferenceRequest(BaseModel):
    """Inference request from backend."""

    stream_id: str = Field(description="Source stream UUID")
    device_id: Optional[str] = Field(None, description="Source device UUID")

    # Phase 2: Accept base64-encoded frame data instead of reference
    frame_base64: str = Field(description="Base64-encoded frame image data")
    frame_format: str = Field(default="jpeg", description="Image format: jpeg, png")
    frame_width: Optional[int] = Field(None, description="Image width in pixels")
    frame_height: Optional[int] = Field(None, description="Image height in pixels")

    timestamp: datetime = Field(description="Frame capture timestamp")
    model_id: str = Field(default="fall_detection", description="Target model identifier")
    model_version: Optional[str] = Field(None, description="Specific model version (optional)")
    priority: int = Field(default=0, ge=0, le=10, description="Request priority (0-10)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    config: Optional[Dict[str, Any]] = Field(None, description="Model-specific configuration (e.g., tank corners, ROI)")

    class Config:
        json_schema_extra = {
            "example": {
                "stream_id": "550e8400-e29b-41d4-a716-446655440000",
                "device_id": "660e8400-e29b-41d4-a716-446655440001",
                "frame_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "frame_format": "jpeg",
                "frame_width": 1920,
                "frame_height": 1080,
                "timestamp": "2026-01-18T12:00:00Z",
                "model_id": "fall_detection",
                "model_version": "1.0.0",
                "priority": 5,
                "metadata": {},
            }
        }


class InferenceResponse(BaseModel):
    """Inference response to backend."""

    request_id: str = Field(description="Unique request identifier")
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
                    "event_type": "fall_detected",
                    "confidence": 0.92,
                    "bounding_boxes": [],
                },
                "error": None,
            }
        }


@router.post("", response_model=InferenceResponse, tags=["inference"])
async def submit_inference(request: InferenceRequest) -> InferenceResponse:
    """
    Submit inference request for a frame.

    Args:
        request: Inference request with base64 frame and model selection

    Returns:
        Inference results with detections

    Raises:
        404: Model not found
        503: Runtime not ready or overloaded
        500: Inference failed
    """
    registry = get_registry()
    sandbox_manager = get_sandbox_manager()

    if not registry or not sandbox_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime not initialized"
        )

    # Generate request ID
    request_id = uuid.uuid4()
    start_time = time.time()

    # Record frame size
    frame_size = len(request.frame_base64)
    record_frame_size(frame_size)

    logger.info("Inference request received", extra={
        "request_id": str(request_id),
        "model_id": request.model_id,
        "model_version": request.model_version,
        "frame_size_bytes": frame_size,
        "stream_id": request.stream_id
    })

    try:
        # Phase 2: Decode base64 to numpy array
        decode_start = time.time()
        frame = _decode_base64_frame(request.frame_base64, request.frame_format)
        decode_duration = time.time() - decode_start

        # Record decode latency
        record_frame_decode_latency(decode_duration)

        # Get model from registry
        model_key = f"{request.model_id}:{request.model_version or 'latest'}"
        model_version = None

        # Find matching model version
        for version in registry.get_all_versions():
            if version.model_id == request.model_id:
                if request.model_version and version.version != request.model_version:
                    continue
                model_version = version
                break

        if not model_version or not model_version.state.is_available():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model not found or not ready: {model_key}"
            )

        # Execute inference through sandbox manager
        # This provides proper isolation and error handling
        execution_result = sandbox_manager.execute(
            model_id=request.model_id,
            version=model_version.version,
            frame=frame,
            request_id=str(request_id),
            config=request.config,
        )

        if not execution_result.success:
            raise Exception(execution_result.error or "Inference failed")

        result = execution_result.output

        # Calculate inference time
        inference_time_ms = (time.time() - start_time) * 1000
        inference_time_seconds = inference_time_ms / 1000.0

        # Record metrics
        record_inference(model_id=request.model_id, status="success")
        record_inference_latency(model_id=request.model_id, duration_seconds=inference_time_seconds)

        # Log success
        logger.info("Inference completed successfully", extra={
            "request_id": str(request_id),
            "model_id": request.model_id,
            "model_version": model_version.version,
            "inference_time_ms": inference_time_ms,
            "detection_count": result.get("detection_count", 0) if result else 0,
            "violation_detected": result.get("violation_detected", False) if result else False
        })

        return InferenceResponse(
            request_id=str(request_id),
            status="success",
            model_id=request.model_id,
            model_version=model_version.version,
            inference_time_ms=inference_time_ms,
            result=result,
            error=None,
        )

    except HTTPException as e:
        # Record rejection metrics
        record_inference(model_id=request.model_id, status="rejected")

        logger.warning("Inference rejected", extra={
            "request_id": str(request_id),
            "model_id": request.model_id,
            "status_code": e.status_code,
            "detail": e.detail
        })
        raise

    except Exception as e:
        inference_time_ms = (time.time() - start_time) * 1000

        # Record failure metrics
        record_inference(model_id=request.model_id, status="failed")

        # Log error
        logger.error("Inference failed", extra={
            "request_id": str(request_id),
            "model_id": request.model_id,
            "inference_time_ms": inference_time_ms,
            "error": str(e)
        }, exc_info=True)

        return InferenceResponse(
            request_id=str(request_id),
            status="failed",
            model_id=request.model_id,
            model_version=request.model_version or "unknown",
            inference_time_ms=inference_time_ms,
            result=None,
            error=str(e),
        )


def _decode_base64_frame(base64_data: str, format: str = "jpeg") -> np.ndarray:
    """
    Decode base64 string to numpy array (BGR format for OpenCV).

    Args:
        base64_data: Base64-encoded image data
        format: Image format (jpeg, png)

    Returns:
        Numpy array in BGR format (H, W, 3)

    Raises:
        ValueError: If decoding fails
    """
    try:
        # Decode base64
        image_bytes = base64.b64decode(base64_data)

        # Convert to PIL Image
        image = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB numpy array
        frame_rgb = np.array(image)

        # Convert RGB to BGR for OpenCV
        if len(frame_rgb.shape) == 3 and frame_rgb.shape[2] == 3:
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        else:
            frame_bgr = frame_rgb

        return frame_bgr

    except Exception as e:
        raise ValueError(f"Failed to decode base64 frame: {e}")

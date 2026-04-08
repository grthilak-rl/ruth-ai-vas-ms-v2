"""
Ruth AI Unified Runtime - Inference Endpoint

Accepts base64-encoded frames and routes to appropriate models for inference.
Includes input validation for security hardening.
"""

import base64
import io
import re
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, status
from PIL import Image
from pydantic import BaseModel, Field, field_validator, model_validator

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


# =============================================================================
# VALIDATION CONSTANTS - Security and sanity limits
# =============================================================================

# Frame size limits
MAX_FRAME_BASE64_SIZE = 50 * 1024 * 1024  # 50MB max (base64 encoded)
MAX_FRAME_DECODED_SIZE = 100 * 1024 * 1024  # 100MB max (decoded)
MAX_FRAME_WIDTH = 7680  # 8K resolution
MAX_FRAME_HEIGHT = 4320
MIN_FRAME_WIDTH = 64
MIN_FRAME_HEIGHT = 64

# Metadata limits
MAX_METADATA_SIZE = 65536  # 64KB max for metadata dict
MAX_METADATA_DEPTH = 5  # Max nesting depth
MAX_STRING_LENGTH = 10000  # Max string length in metadata

# ID validation
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)
MODEL_ID_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')
VERSION_PATTERN = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9]+)?$')

# Timestamp limits
MAX_TIMESTAMP_DRIFT_SECONDS = 86400  # 24 hours max drift


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================


def validate_metadata_depth(obj: Any, depth: int = 0) -> bool:
    """
    Validate metadata nesting depth to prevent DoS via deep structures.

    Args:
        obj: Object to validate
        depth: Current depth

    Returns:
        True if valid

    Raises:
        ValueError: If depth exceeds limit
    """
    if depth > MAX_METADATA_DEPTH:
        raise ValueError(f"Metadata nesting depth exceeds limit ({MAX_METADATA_DEPTH})")

    if isinstance(obj, dict):
        for v in obj.values():
            validate_metadata_depth(v, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            validate_metadata_depth(item, depth + 1)
    elif isinstance(obj, str) and len(obj) > MAX_STRING_LENGTH:
        raise ValueError(f"String in metadata exceeds max length ({MAX_STRING_LENGTH})")

    return True


def validate_base64_frame(data: str) -> None:
    """
    Validate base64-encoded frame data.

    Args:
        data: Base64 string to validate

    Raises:
        ValueError: If validation fails
    """
    # Check size
    if len(data) > MAX_FRAME_BASE64_SIZE:
        raise ValueError(
            f"Frame data too large: {len(data)} bytes "
            f"(max: {MAX_FRAME_BASE64_SIZE} bytes)"
        )

    # Check for valid base64 characters
    # Remove whitespace and padding for validation
    clean_data = data.replace('\n', '').replace('\r', '').replace(' ', '')
    if not re.match(r'^[A-Za-z0-9+/]*={0,2}$', clean_data):
        raise ValueError("Invalid base64 encoding: contains illegal characters")


class InferenceRequest(BaseModel):
    """
    Inference request from backend.

    Includes comprehensive validation for security hardening:
    - UUID format validation for IDs
    - Frame size and format limits
    - Timestamp drift detection
    - Metadata depth and size limits
    """

    stream_id: str = Field(description="Source stream UUID")
    device_id: Optional[str] = Field(None, description="Source device UUID")

    # Phase 2: Accept base64-encoded frame data instead of reference
    frame_base64: str = Field(description="Base64-encoded frame image data")
    frame_format: str = Field(default="jpeg", description="Image format: jpeg, png")
    frame_width: Optional[int] = Field(None, ge=MIN_FRAME_WIDTH, le=MAX_FRAME_WIDTH, description="Image width in pixels")
    frame_height: Optional[int] = Field(None, ge=MIN_FRAME_HEIGHT, le=MAX_FRAME_HEIGHT, description="Image height in pixels")

    timestamp: datetime = Field(description="Frame capture timestamp")
    model_id: str = Field(default="fall_detection", description="Target model identifier")
    model_version: Optional[str] = Field(None, description="Specific model version (optional)")
    priority: int = Field(default=0, ge=0, le=10, description="Request priority (0-10)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    config: Optional[Dict[str, Any]] = Field(None, description="Model-specific configuration (e.g., tank corners, ROI)")

    @field_validator("stream_id")
    @classmethod
    def validate_stream_id(cls, v: str) -> str:
        """Validate stream_id is a valid UUID."""
        if not UUID_PATTERN.match(v):
            raise ValueError("stream_id must be a valid UUID")
        return v

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate device_id is a valid UUID if provided."""
        if v is not None and not UUID_PATTERN.match(v):
            raise ValueError("device_id must be a valid UUID")
        return v

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, v: str) -> str:
        """Validate model_id format."""
        if not MODEL_ID_PATTERN.match(v):
            raise ValueError(
                "model_id must start with a letter and contain only "
                "alphanumeric characters, underscores, and hyphens (max 64 chars)"
            )
        return v

    @field_validator("model_version")
    @classmethod
    def validate_model_version(cls, v: Optional[str]) -> Optional[str]:
        """Validate model_version is semver format if provided."""
        if v is not None and not VERSION_PATTERN.match(v):
            raise ValueError("model_version must be semantic version (e.g., 1.0.0)")
        return v

    @field_validator("frame_format")
    @classmethod
    def validate_frame_format(cls, v: str) -> str:
        """Validate frame_format is a supported image format."""
        allowed = {"jpeg", "jpg", "png", "webp"}
        if v.lower() not in allowed:
            raise ValueError(f"frame_format must be one of: {', '.join(allowed)}")
        return v.lower()

    @field_validator("frame_base64")
    @classmethod
    def validate_frame_base64(cls, v: str) -> str:
        """Validate base64 frame data."""
        validate_base64_frame(v)
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate metadata structure and depth."""
        # Check serialized size
        import json
        try:
            serialized = json.dumps(v)
            if len(serialized) > MAX_METADATA_SIZE:
                raise ValueError(
                    f"metadata too large: {len(serialized)} bytes "
                    f"(max: {MAX_METADATA_SIZE} bytes)"
                )
        except (TypeError, ValueError) as e:
            raise ValueError(f"metadata must be JSON-serializable: {e}")

        # Check nesting depth
        validate_metadata_depth(v)
        return v

    @field_validator("config")
    @classmethod
    def validate_config(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Validate config structure and depth."""
        if v is None:
            return v

        # Check serialized size
        import json
        try:
            serialized = json.dumps(v)
            if len(serialized) > MAX_METADATA_SIZE:
                raise ValueError(
                    f"config too large: {len(serialized)} bytes "
                    f"(max: {MAX_METADATA_SIZE} bytes)"
                )
        except (TypeError, ValueError) as e:
            raise ValueError(f"config must be JSON-serializable: {e}")

        # Check nesting depth
        validate_metadata_depth(v)
        return v

    @model_validator(mode="after")
    def validate_timestamp_drift(self) -> "InferenceRequest":
        """Validate timestamp is not too far in past or future."""
        now = datetime.now(timezone.utc)
        ts = self.timestamp

        # Make timestamp timezone-aware if it isn't
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        drift = abs((now - ts).total_seconds())
        if drift > MAX_TIMESTAMP_DRIFT_SECONDS:
            raise ValueError(
                f"timestamp drift too large: {drift:.0f}s "
                f"(max: {MAX_TIMESTAMP_DRIFT_SECONDS}s)"
            )
        return self

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

    Includes security validation:
    - Decoded size limits
    - Image dimension limits
    - Memory protection via PIL limits

    Args:
        base64_data: Base64-encoded image data
        format: Image format (jpeg, png)

    Returns:
        Numpy array in BGR format (H, W, 3)

    Raises:
        ValueError: If decoding fails or validation fails
    """
    try:
        # Decode base64
        image_bytes = base64.b64decode(base64_data)

        # Check decoded size
        if len(image_bytes) > MAX_FRAME_DECODED_SIZE:
            raise ValueError(
                f"Decoded frame too large: {len(image_bytes)} bytes "
                f"(max: {MAX_FRAME_DECODED_SIZE} bytes)"
            )

        # Set PIL limits to prevent decompression bombs
        Image.MAX_IMAGE_PIXELS = MAX_FRAME_WIDTH * MAX_FRAME_HEIGHT

        # Convert to PIL Image
        image = Image.open(io.BytesIO(image_bytes))

        # Validate dimensions
        width, height = image.size
        if width > MAX_FRAME_WIDTH or height > MAX_FRAME_HEIGHT:
            raise ValueError(
                f"Frame dimensions too large: {width}x{height} "
                f"(max: {MAX_FRAME_WIDTH}x{MAX_FRAME_HEIGHT})"
            )
        if width < MIN_FRAME_WIDTH or height < MIN_FRAME_HEIGHT:
            raise ValueError(
                f"Frame dimensions too small: {width}x{height} "
                f"(min: {MIN_FRAME_WIDTH}x{MIN_FRAME_HEIGHT})"
            )

        # Convert to RGB numpy array
        frame_rgb = np.array(image)

        # Validate array size
        if frame_rgb.nbytes > MAX_FRAME_DECODED_SIZE:
            raise ValueError(
                f"Decoded frame array too large: {frame_rgb.nbytes} bytes"
            )

        # Convert RGB to BGR for OpenCV
        if len(frame_rgb.shape) == 3 and frame_rgb.shape[2] == 3:
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        elif len(frame_rgb.shape) == 3 and frame_rgb.shape[2] == 4:
            # RGBA to BGR
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGBA2BGR)
        elif len(frame_rgb.shape) == 2:
            # Grayscale to BGR
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_GRAY2BGR)
        else:
            frame_bgr = frame_rgb

        return frame_bgr

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to decode base64 frame: {e}")

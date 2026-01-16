"""AI Runtime Integration Layer.

Provides async client for backend to communicate with AI Runtime service.
Supports gRPC (primary) and REST (fallback) transports.

The backend uses this client to:
- Register/refresh runtime capabilities
- Submit inference requests (frame references, NOT raw frames)
- Check runtime health

This is INTEGRATION GLUE ONLY - no AI logic exists here.

Usage:
    from app.integrations.ai_runtime import AIRuntimeClient

    async with AIRuntimeClient(runtime_url) as client:
        # Check if runtime is healthy
        health = await client.check_health()

        # Get capabilities
        caps = await client.get_capabilities()

        # Submit inference (frame reference, not raw frame)
        response = await client.submit_inference(
            stream_id=stream_uuid,
            frame_reference="vas://frame/abc123",  # Opaque VAS reference
            timestamp=frame_timestamp,
            model_id="fall_detection"
        )

        # Process response
        if response.has_detections:
            for detection in response.detections:
                print(f"Detected: {detection.class_name} ({detection.confidence})")

Exception Hierarchy:
    AIRuntimeError (base)
    ├── AIRuntimeConnectionError - Cannot establish connection
    ├── AIRuntimeUnavailableError - Service unreachable
    ├── AIRuntimeTimeoutError - Request timed out
    ├── AIRuntimeProtocolError - Transport/protocol failure
    ├── AIRuntimeInvalidResponseError - Malformed response
    ├── AIRuntimeCapabilityError - Capability mismatch
    ├── AIRuntimeModelNotFoundError - Model not available
    └── AIRuntimeOverloadedError - Runtime at capacity

Design Principles:
    - Backend NEVER sees raw frames
    - Backend NEVER imports AI libraries
    - Backend treats inference results as opaque data
    - Runtime can be swapped (CPU/GPU/Jetson) without backend changes
"""

from .client import AIRuntimeClient
from .exceptions import (
    AIRuntimeCapabilityError,
    AIRuntimeConnectionError,
    AIRuntimeError,
    AIRuntimeInvalidResponseError,
    AIRuntimeModelNotFoundError,
    AIRuntimeOverloadedError,
    AIRuntimeProtocolError,
    AIRuntimeTimeoutError,
    AIRuntimeUnavailableError,
)
from .models import (
    BoundingBox,
    CapabilityRegistrationRequest,
    CapabilityRegistrationResponse,
    Detection,
    HardwareType,
    HealthCheckRequest,
    HealthCheckResponse,
    InferenceRequest,
    InferenceResponse,
    InferenceStatus,
    ModelCapability,
    ModelHealth,
    ModelStatus,
    RuntimeCapabilities,
    RuntimeHealth,
    RuntimeStatus,
)

__all__ = [
    # Client
    "AIRuntimeClient",
    # Exceptions
    "AIRuntimeError",
    "AIRuntimeConnectionError",
    "AIRuntimeUnavailableError",
    "AIRuntimeTimeoutError",
    "AIRuntimeProtocolError",
    "AIRuntimeInvalidResponseError",
    "AIRuntimeCapabilityError",
    "AIRuntimeModelNotFoundError",
    "AIRuntimeOverloadedError",
    # Models - Enums
    "HardwareType",
    "RuntimeStatus",
    "InferenceStatus",
    "ModelStatus",
    # Models - Capability
    "ModelCapability",
    "RuntimeCapabilities",
    "CapabilityRegistrationRequest",
    "CapabilityRegistrationResponse",
    # Models - Inference
    "BoundingBox",
    "Detection",
    "InferenceRequest",
    "InferenceResponse",
    # Models - Health
    "ModelHealth",
    "RuntimeHealth",
    "HealthCheckRequest",
    "HealthCheckResponse",
]

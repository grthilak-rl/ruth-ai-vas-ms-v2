"""
AI Inference API Endpoints

Handles direct inference requests from frontend with base64-encoded frames.
Routes to unified AI runtime for model execution.
"""

from typing import Any, Dict, Optional
from uuid import uuid4
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.integrations.unified_runtime import UnifiedRuntimeClient

logger = get_logger(__name__)

router = APIRouter(tags=["ai"])


class InferenceRequest(BaseModel):
    """Request schema for direct AI inference."""

    model_id: str = Field(..., description="Model identifier (e.g., 'tank_overflow_monitoring')")
    version: Optional[str] = Field(default=None, description="Model version (defaults to latest)")
    frame: str = Field(..., description="Base64-encoded frame (JPEG or PNG)")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Model-specific configuration")


@router.post(
    "/ai/inference",
    summary="Submit AI inference request",
    description="Submit a base64-encoded frame for AI model inference. Used by frontend for client-side frame extraction.",
    response_model=Dict[str, Any],
)
async def submit_inference(request: InferenceRequest) -> Dict[str, Any]:
    """
    Submit inference request to unified AI runtime.

    This endpoint accepts base64-encoded frames from the frontend and routes them
    to the unified AI runtime for model execution. It's designed for client-side
    frame extraction patterns.

    Args:
        request: Inference request with model ID, frame data, and optional config

    Returns:
        Model inference results

    Raises:
        HTTPException: If model not found or inference fails
    """
    try:
        logger.info(
            "Received inference request",
            model_id=request.model_id,
            version=request.version,
            frame_size=len(request.frame),
            has_config=request.config is not None,
        )

        # Create unified runtime client
        runtime_client = UnifiedRuntimeClient()

        # Submit to unified runtime
        # Generate dummy stream_id since frontend doesn't have one
        dummy_stream_id = uuid4()

        response = await runtime_client.submit_inference(
            model_id=request.model_id,
            frame_base64=request.frame,
            stream_id=dummy_stream_id,
            device_id=None,
            model_version=request.version,
            config=request.config,
        )

        # Check for errors
        if response.status == "error":
            logger.error(
                "Inference failed",
                model_id=request.model_id,
                error=response.error,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Inference failed: {response.error}",
            )

        # Return inference results
        result = response.result or {}

        logger.info(
            "Inference completed",
            model_id=request.model_id,
            inference_time_ms=response.inference_time_ms,
            status=response.status,
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Inference request failed", model_id=request.model_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference request failed: {str(e)}",
        )

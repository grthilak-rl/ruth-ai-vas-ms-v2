"""
AI Inference API Endpoints

Handles direct inference requests from frontend with base64-encoded frames.
Routes built-in models to the unified AI runtime and uploaded (model store)
models, e.g. fall_pose, to the model store runtime.
"""

from typing import Any, Dict, Optional
from uuid import uuid4
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.v1.model_guard import MODEL_GUARD_RESPONSES, require_installed_model
from app.core.logging import get_logger
from app.integrations.unified_runtime import UnifiedRuntimeClient
from app.integrations.unified_runtime.config import get_unified_runtime_config
from app.services.model_store.enabled import enabled_store_models

logger = get_logger(__name__)

router = APIRouter(tags=["ai"])


class InferenceRequest(BaseModel):
    """Request schema for direct AI inference."""

    model_id: str = Field(..., description="Model identifier (e.g., 'tank_overflow_monitoring')")
    version: Optional[str] = Field(default=None, description="Model version (defaults to latest)")
    frame: str = Field(..., description="Base64-encoded frame (JPEG or PNG)")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Model-specific configuration")


def runtime_url_for(model_id: str) -> Optional[str]:
    """The runtime that serves ``model_id``: None means the unified runtime.

    Same membership test the inference loop and /models/status use
    (installed store manifests), so a store model is served here exactly
    where it is served live. Without a store runtime configured, or with an
    unreadable store, everything goes to the unified runtime as before.
    """
    store_url = get_unified_runtime_config().model_store_runtime_url
    if not store_url:
        return None
    try:
        if model_id in enabled_store_models():
            return store_url
    except Exception:  # noqa: BLE001 - never fail a request over routing
        logger.debug("Store model lookup failed; using unified runtime", model_id=model_id)
    return None


@router.post(
    "/ai/inference",
    summary="Submit AI inference request",
    description="Submit a base64-encoded frame for AI model inference. Used by frontend for client-side frame extraction.",
    response_model=Dict[str, Any],
    responses=MODEL_GUARD_RESPONSES,
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
        HTTPException: 422 if the model is retired or not installed, 500 if
        inference fails
    """
    # A retired or uninstalled model is the caller's mistake: 422 naming the
    # replacement, not a 500 from the runtime's "Model not found".
    await require_installed_model(request.model_id)

    try:
        logger.info(
            "Received inference request",
            model_id=request.model_id,
            version=request.version,
            frame_size=len(request.frame),
            has_config=request.config is not None,
        )

        # Unified runtime for built-in models, store runtime for store models
        runtime_client = UnifiedRuntimeClient(runtime_url=runtime_url_for(request.model_id))

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

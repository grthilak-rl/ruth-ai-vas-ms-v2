"""Models API endpoints.

From API Contract - Models APIs:
- GET    /models/status

Provides AI model status information for the frontend.
Aligned with F6 §4.3 Models Domain.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.core.logging import get_logger
from app.deps import DBSession
from app.models import StreamSession, StreamState
from app.schemas import ErrorResponse, ModelStatusInfo, ModelsStatusResponse
from app.integrations.unified_runtime.client import (
    UnifiedRuntimeClient,
    UnifiedRuntimeConnectionError,
)
from app.integrations.unified_runtime.config import get_unified_runtime_config

router = APIRouter(tags=["Models"])
logger = get_logger(__name__)


@router.get(
    "/models/status",
    response_model=ModelsStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get AI models status",
    description="Returns status of all registered AI models.",
    responses={
        200: {"model": ModelsStatusResponse, "description": "Models status"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_models_status(
    db: DBSession,
) -> ModelsStatusResponse:
    """Get status of all AI models.

    Returns operational status, health, and activity metrics for each
    registered AI model. Queries unified runtime for available models
    and enriches with usage data from stream sessions.

    Args:
        db: Database session

    Returns:
        List of model statuses
    """
    config = get_unified_runtime_config()
    models = []

    # Query unified runtime for available models
    runtime_models = {}
    if config.enable_unified_runtime:
        try:
            async with UnifiedRuntimeClient() as client:
                capabilities = await client.get_capabilities()
                runtime_models = {
                    model["model_id"]: model
                    for model in capabilities.get("models", [])
                }
                logger.info(
                    "Retrieved unified runtime models",
                    count=len(runtime_models),
                )
        except UnifiedRuntimeConnectionError as e:
            logger.warning(
                "Failed to connect to unified runtime",
                error=str(e),
            )
        except Exception as e:
            logger.error(
                "Unexpected error querying unified runtime",
                error=str(e),
            )

    # Filter out test/development models
    test_model_prefixes = ["broken_", "dummy_", "test_"]
    production_models = {
        model_id: model_info
        for model_id, model_info in runtime_models.items()
        if not any(model_id.startswith(prefix) for prefix in test_model_prefixes)
        and model_info.get("state") != "invalid"  # Also filter invalid models
    }

    logger.info(
        "Filtered models",
        total=len(runtime_models),
        production=len(production_models),
        filtered_out=len(runtime_models) - len(production_models),
    )

    # Build model status for each discovered model
    for model_id, model_info in production_models.items():
        # Count active cameras using this model
        active_sessions_stmt = (
            select(func.count())
            .select_from(StreamSession)
            .where(StreamSession.state == StreamState.LIVE)
            .where(StreamSession.model_id == model_id)
        )
        result = await db.execute(active_sessions_stmt)
        cameras_active = result.scalar() or 0

        # Get most recent inference time
        last_session_stmt = (
            select(StreamSession.started_at)
            .where(StreamSession.model_id == model_id)
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        result = await db.execute(last_session_stmt)
        last_started = result.scalar()

        # Map unified runtime state to API status
        runtime_state = model_info.get("state", "unknown")
        runtime_health = model_info.get("health", "unknown")

        # Determine status based on runtime state and activity
        if runtime_state == "ready":
            model_status = "active" if cameras_active > 0 else "idle"
        elif runtime_state == "loading":
            model_status = "starting"
        elif runtime_state == "failed":
            model_status = "error"
        else:
            model_status = "idle"

        # Map runtime health to API health
        if runtime_health == "healthy":
            health_status = "healthy"
        elif runtime_health == "degraded":
            health_status = "degraded"
        elif runtime_health == "unknown":
            # Unknown health treated as healthy if model is ready
            health_status = "healthy" if runtime_state == "ready" else "unhealthy"
        else:
            health_status = "unhealthy"

        models.append(
            ModelStatusInfo(
                model_id=model_id,
                version=model_info.get("version", "1.0.0"),
                status=model_status,
                health=health_status,
                cameras_active=cameras_active,
                last_inference_at=last_started,
                started_at=last_started,
            )
        )

    # Add legacy container models (always add them - they have different model_ids)
    legacy_models = ["fall_detection_container", "ppe_detection_container"]
    logger.info(
        "Adding legacy container models",
        legacy_models=legacy_models,
        runtime_models=list(runtime_models.keys()),
    )
    for model_id in legacy_models:
        # Count active sessions for legacy model
        active_sessions_stmt = (
            select(func.count())
            .select_from(StreamSession)
            .where(StreamSession.state == StreamState.LIVE)
            .where(StreamSession.model_id == model_id)
        )
        result = await db.execute(active_sessions_stmt)
        cameras_active = result.scalar() or 0

        # Get most recent inference time
        last_session_stmt = (
            select(StreamSession.started_at)
            .where(StreamSession.model_id == model_id)
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        result = await db.execute(last_session_stmt)
        last_started = result.scalar()

        model_status = "active" if cameras_active > 0 else "idle"

        models.append(
            ModelStatusInfo(
                model_id=model_id,
                version="1.0.0",
                status=model_status,
                health="healthy",
                cameras_active=cameras_active,
                last_inference_at=last_started,
                started_at=last_started,
            )
        )

    logger.info(
        "Retrieved model statuses",
        count=len(models),
        unified_runtime_count=len(runtime_models),
    )

    return ModelsStatusResponse(models=models)

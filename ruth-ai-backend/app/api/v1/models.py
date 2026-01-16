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
    registered AI model. For now, returns fall_detection model status
    based on active stream sessions.

    Args:
        db: Database session

    Returns:
        List of model statuses
    """
    # Count active cameras using fall_detection model
    active_sessions_stmt = (
        select(func.count())
        .select_from(StreamSession)
        .where(StreamSession.state == StreamState.LIVE)
        .where(StreamSession.model_id == "fall_detection")
    )
    result = await db.execute(active_sessions_stmt)
    cameras_active = result.scalar() or 0

    # Get most recent inference time for fall_detection
    last_session_stmt = (
        select(StreamSession.started_at)
        .where(StreamSession.model_id == "fall_detection")
        .order_by(StreamSession.started_at.desc())
        .limit(1)
    )
    result = await db.execute(last_session_stmt)
    last_started = result.scalar()

    # Determine model status based on activity
    model_status = "active" if cameras_active > 0 else "idle"

    # Build response
    models = [
        ModelStatusInfo(
            model_id="fall_detection",
            version="1.0.0",
            status=model_status,
            health="healthy",
            cameras_active=cameras_active,
            last_inference_at=last_started if last_started else None,
            started_at=last_started if last_started else None,
        )
    ]

    logger.info(
        "Retrieved model statuses",
        count=len(models),
        active_cameras=cameras_active,
    )

    return ModelsStatusResponse(models=models)

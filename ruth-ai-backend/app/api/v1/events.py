"""Event API endpoints.

From API Contract - Event APIs:
- GET    /events
- GET    /events/{id}

These endpoints provide read-only access to AI inference events.
Events are created by the internal event ingestion pipeline.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.logging import get_logger
from app.deps import DBSession, EventIngestionServiceDep
from app.models import Event
from app.schemas import (
    ErrorResponse,
    EventListResponse,
    EventResponse,
)

router = APIRouter(tags=["Events"])
logger = get_logger(__name__)


@router.get(
    "/events",
    response_model=EventListResponse,
    status_code=status.HTTP_200_OK,
    summary="List events",
    description="Returns AI inference events with optional filtering.",
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_events(
    db: DBSession,
    device_id: UUID | None = Query(None, description="Filter by device"),
    event_type: str | None = Query(None, description="Filter by event type"),
    since: datetime | None = Query(None, description="Events after this timestamp"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> EventListResponse:
    """List events with optional filtering.

    Args:
        db: Database session
        device_id: Filter by device UUID
        event_type: Filter by event type string
        since: Only events after this timestamp
        limit: Maximum results to return
        offset: Pagination offset

    Returns:
        List of events with total count
    """
    # Build query
    stmt = select(Event).order_by(Event.timestamp.desc())

    # Apply filters
    if device_id is not None:
        stmt = stmt.where(Event.device_id == device_id)

    if event_type is not None:
        stmt = stmt.where(Event.event_type == event_type)

    if since is not None:
        stmt = stmt.where(Event.timestamp >= since)

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    events = list(result.scalars().all())

    logger.info(
        "Listing events",
        total=total,
        returned=len(events),
        device_id=str(device_id) if device_id else None,
    )

    return EventListResponse(
        events=[
            EventResponse(
                id=e.id,
                device_id=e.device_id,
                stream_session_id=e.stream_session_id,
                event_type=e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
                confidence=e.confidence,
                timestamp=e.timestamp,
                model_id=e.model_id,
                model_version=e.model_version,
                bounding_boxes=e.bounding_boxes,
                frame_id=e.frame_id,
                inference_time_ms=e.inference_time_ms,
                violation_id=e.violation_id,
                created_at=e.created_at,
            )
            for e in events
        ],
        total=total,
    )


@router.get(
    "/events/{event_id}",
    response_model=EventResponse,
    status_code=status.HTTP_200_OK,
    summary="Get event details",
    description="Returns a single event by ID.",
    responses={
        404: {"model": ErrorResponse, "description": "Event not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_event(
    event_id: UUID,
    event_service: EventIngestionServiceDep,
) -> EventResponse:
    """Get event by ID.

    Args:
        event_id: Event UUID
        event_service: Injected EventIngestionService

    Returns:
        Event details

    Raises:
        HTTPException: 404 if event not found
    """
    event = await event_service.get_event_by_id(event_id)

    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "event_not_found",
                "message": f"Event {event_id} not found",
                "details": {"event_id": str(event_id)},
            },
        )

    logger.info("Retrieved event", event_id=str(event_id))

    return EventResponse(
        id=event.id,
        device_id=event.device_id,
        stream_session_id=event.stream_session_id,
        event_type=event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
        confidence=event.confidence,
        timestamp=event.timestamp,
        model_id=event.model_id,
        model_version=event.model_version,
        bounding_boxes=event.bounding_boxes,
        frame_id=event.frame_id,
        inference_time_ms=event.inference_time_ms,
        violation_id=event.violation_id,
        created_at=event.created_at,
    )

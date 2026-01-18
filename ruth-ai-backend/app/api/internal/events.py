"""Internal endpoints for Ruth AI Backend.

POST /internal/events - Simulates AI Runtime → Backend delivery.
POST /internal/sync/devices - Trigger device sync from VAS.

Task T3′ vertical slice:
- Accept minimal inference payload
- Persist Event
- Create Violation if event_type == "fall_detected"
- Auto-create Device/StreamSession stubs if missing
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.logging import get_logger
from app.deps import DeviceServiceDep, EvidenceServiceDep
from app.deps.db import DBSession
from app.models import (
    Device,
    Event,
    EventType,
    StreamSession,
    StreamState,
    Violation,
    ViolationStatus,
    ViolationType,
)
from app.schemas.event import EventIngestRequest, EventResponse
from app.services import DeviceSyncError
from app.services.exceptions import NoActiveStreamError, EvidenceVASError

router = APIRouter(tags=["Internal"])
logger = get_logger(__name__)


class SyncResponse(BaseModel):
    """Response for sync operations."""

    message: str
    devices_synced: int
    devices: list[dict[str, Any]]


@router.post(
    "/sync/devices",
    response_model=SyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync devices from VAS",
    description="Trigger synchronization of devices from VAS to local database.",
)
async def sync_devices(
    device_service: DeviceServiceDep,
) -> SyncResponse:
    """Sync all devices from VAS.

    This endpoint discovers devices from VAS and syncs them to the local database.
    """
    try:
        devices = await device_service.sync_devices_from_vas()
    except DeviceSyncError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "device_sync_failed",
                "message": str(e),
            },
        ) from e

    logger.info("Device sync completed", count=len(devices))

    return SyncResponse(
        message=f"Synced {len(devices)} devices from VAS",
        devices_synced=len(devices),
        devices=[
            {
                "id": str(d.id),
                "vas_device_id": d.vas_device_id,
                "name": d.name,
                "is_active": d.is_active,
            }
            for d in devices
        ],
    )


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest AI inference event",
    description="Internal endpoint for AI Runtime to submit inference results.",
)
async def ingest_event(
    request: EventIngestRequest,
    db: DBSession,
    device_service: DeviceServiceDep,
    evidence_service: EvidenceServiceDep,
) -> EventResponse:
    """Ingest an AI inference event and optionally create a violation.

    This endpoint:
    1. Ensures Device exists (fetches from VAS if missing)
    2. Ensures StreamSession exists (creates stub if missing)
    3. Persists the Event
    4. Creates a Violation if event_type is "fall_detected" or "ppe_violation"
    5. Links Event → Violation
    """
    logger.info(
        "Ingesting event",
        device_id=str(request.device_id),
        event_type=request.event_type,
        confidence=request.confidence,
        vas_stream_id=request.vas_stream_id,
    )

    # 1. Ensure Device exists (fetch from VAS if missing to get real name)
    try:
        device = await device_service.ensure_device_exists(str(request.device_id))
    except Exception as e:
        # Fall back to stub creation if VAS lookup fails
        logger.warning(
            "Failed to fetch device from VAS, creating stub",
            device_id=str(request.device_id),
            error=str(e),
        )
        device = await _ensure_device(db, request.device_id)

    # 2. Ensure StreamSession exists (create stub if missing)
    # If vas_stream_id is provided, use it when creating/updating the session
    stream_session = None
    if request.stream_session_id:
        stream_session = await _ensure_stream_session(
            db, request.stream_session_id, device.id, request.model_id,
            vas_stream_id=request.vas_stream_id
        )
    elif request.vas_stream_id:
        # No explicit session_id but we have vas_stream_id - find or create session
        stream_session = await _ensure_stream_session_by_vas_id(
            db, device.id, request.model_id, request.vas_stream_id
        )

    # 3. Validate and map event_type to enum
    try:
        event_type_enum = EventType(request.event_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event_type: {request.event_type}. "
            f"Valid values: {[e.value for e in EventType]}",
        )

    # 4. Convert bounding boxes to storage format
    bounding_boxes = None
    if request.bounding_boxes:
        bounding_boxes = [
            {"x": bb.x, "y": bb.y, "width": bb.w, "height": bb.h}
            for bb in request.bounding_boxes
        ]

    # 5. Create Event
    event = Event(
        device_id=device.id,
        stream_session_id=stream_session.id if stream_session else None,
        event_type=event_type_enum,
        confidence=request.confidence,
        timestamp=request.timestamp,
        model_id=request.model_id,
        model_version=request.model_version,
        bounding_boxes=bounding_boxes,
    )
    db.add(event)
    await db.flush()  # Get event.id without committing

    logger.info("Event persisted", event_id=str(event.id))

    # 6. Create Violation if fall_detected or ppe_violation
    violation = None
    if event_type_enum in (EventType.FALL_DETECTED, EventType.PPE_VIOLATION):
        # Determine violation type based on event type
        violation_type = (
            ViolationType.FALL_DETECTED
            if event_type_enum == EventType.FALL_DETECTED
            else ViolationType.PPE_VIOLATION
        )

        violation = Violation(
            device_id=device.id,
            stream_session_id=stream_session.id if stream_session else None,
            type=violation_type,
            status=ViolationStatus.OPEN,
            confidence=request.confidence,
            timestamp=request.timestamp,
            camera_name=device.name,
            model_id=request.model_id,
            model_version=request.model_version,
            bounding_boxes=bounding_boxes,
        )
        db.add(violation)
        await db.flush()  # Get violation.id

        # Link Event → Violation
        event.violation_id = violation.id

        logger.info(
            "Violation created",
            violation_id=str(violation.id),
            event_id=str(event.id),
            violation_type=violation_type.value,
        )

        # 7. Trigger evidence capture (fire-and-forget, don't block on failures)
        if stream_session and stream_session.vas_stream_id:
            try:
                evidence = await evidence_service.create_snapshot(
                    violation,
                    created_by="ruth-ai-auto",
                    allow_existing=True,
                )
                logger.info(
                    "Snapshot capture initiated",
                    violation_id=str(violation.id),
                    evidence_id=str(evidence.id),
                    evidence_status=evidence.status.value,
                )
            except (NoActiveStreamError, EvidenceVASError) as e:
                # Log but don't fail - evidence capture is best-effort
                logger.warning(
                    "Snapshot capture failed (non-fatal)",
                    violation_id=str(violation.id),
                    error=str(e),
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error during snapshot capture (non-fatal)",
                    violation_id=str(violation.id),
                    error=str(e),
                )
        else:
            logger.warning(
                "Skipping snapshot capture - no VAS stream ID available",
                violation_id=str(violation.id),
                has_session=stream_session is not None,
            )

    # Commit happens automatically via DBSession context manager

    return EventResponse(
        id=event.id,
        device_id=event.device_id,
        event_type=event.event_type.value,
        confidence=event.confidence,
        timestamp=event.timestamp,
        model_id=event.model_id,
        model_version=event.model_version,
        bounding_boxes=event.bounding_boxes,
        violation_id=event.violation_id,
        created_at=event.created_at,
    )


async def _ensure_device(db: DBSession, device_id) -> Device:
    """Ensure a device exists, creating a stub if missing.

    This is a fallback when VAS lookup fails. The stub will be updated
    with the real name when the device is synced from VAS.

    Args:
        db: Database session
        device_id: Could be either Ruth AI device UUID or VAS device ID
    """
    # First, check if this is a Ruth AI device ID (primary key lookup)
    try:
        stmt = select(Device).where(Device.id == device_id)
        result = await db.execute(stmt)
        device = result.scalar_one_or_none()
        if device is not None:
            logger.info(
                "Found device by Ruth AI ID (should use VAS device ID instead)",
                device_id=str(device.id),
                vas_device_id=device.vas_device_id,
                name=device.name
            )
            return device
    except Exception:
        pass  # Not a valid UUID for Ruth AI device, try VAS device ID

    # Query by VAS device ID
    stmt = select(Device).where(Device.vas_device_id == str(device_id))
    result = await db.execute(stmt)
    device = result.scalar_one_or_none()

    if device is None:
        # Create stub device - name will be updated when synced from VAS
        device = Device(
            vas_device_id=str(device_id),
            name=f"Camera {str(device_id)[:8]}",
            description="Pending sync from VAS",
            is_active=True,
        )
        db.add(device)
        await db.flush()
        logger.info("Created stub device (VAS lookup failed)", device_id=str(device.id))

    return device


async def _ensure_stream_session(
    db: DBSession, session_id, device_id, model_id: str, vas_stream_id: str | None = None
) -> StreamSession:
    """Ensure a stream session exists, creating a stub if missing."""
    stmt = select(StreamSession).where(StreamSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        # Create stub session with vas_stream_id
        session = StreamSession(
            id=session_id,
            device_id=device_id,
            model_id=model_id,
            model_version="1.0.0",
            state=StreamState.LIVE,
            started_at=datetime.now(timezone.utc),
            vas_stream_id=vas_stream_id,
        )
        db.add(session)
        await db.flush()
        logger.info("Created stub stream session", session_id=str(session.id), vas_stream_id=vas_stream_id)
    elif vas_stream_id and not session.vas_stream_id:
        # Update existing session with vas_stream_id if not set
        session.vas_stream_id = vas_stream_id
        logger.info("Updated stream session with VAS stream ID", session_id=str(session.id), vas_stream_id=vas_stream_id)

    return session


async def _ensure_stream_session_by_vas_id(
    db: DBSession, device_id, model_id: str, vas_stream_id: str
) -> StreamSession:
    """Find or create a stream session by VAS stream ID."""
    # First try to find existing session by vas_stream_id
    stmt = select(StreamSession).where(StreamSession.vas_stream_id == vas_stream_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        # Create new session with vas_stream_id
        session = StreamSession(
            device_id=device_id,
            model_id=model_id,
            model_version="1.0.0",
            state=StreamState.LIVE,
            started_at=datetime.now(timezone.utc),
            vas_stream_id=vas_stream_id,
        )
        db.add(session)
        await db.flush()
        logger.info("Created stream session from VAS stream ID", session_id=str(session.id), vas_stream_id=vas_stream_id)

    return session

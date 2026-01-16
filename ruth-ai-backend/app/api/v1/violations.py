"""Violation API endpoints.

From API Contract - Violation APIs:
- GET    /violations
- GET    /violations/{id}
- POST   /violations/{id}/snapshot
- GET    /violations/{id}/video

These endpoints delegate to ViolationService and EvidenceService.
No business logic is implemented here.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.deps import DBSession, EvidenceServiceDep, VASClientDep, ViolationServiceDep
from app.models import Evidence, EvidenceType, Violation
from app.schemas import (
    ErrorResponse,
    SnapshotCreateRequest,
    SnapshotResponse,
    VideoEvidenceResponse,
    ViolationDetailResponse,
    ViolationEvidenceSummary,
    ViolationListResponse,
    ViolationResponse,
    ViolationStatusUpdateRequest,
)
from app.services import (
    EvidenceVASError,
    NoActiveStreamError,
    ViolationNotFoundError,
    ViolationStateError,
    ViolationTerminalStateError,
)

router = APIRouter(tags=["Violations"])
logger = get_logger(__name__)


def build_evidence_summary(evidence_list: list[Evidence]) -> ViolationEvidenceSummary | None:
    """Build evidence summary from evidence records.

    Args:
        evidence_list: List of Evidence model instances

    Returns:
        ViolationEvidenceSummary with snapshot/bookmark info, or None if no evidence
    """
    if not evidence_list:
        return None

    snapshot_evidence = None
    bookmark_evidence = None

    for e in evidence_list:
        if e.evidence_type == EvidenceType.SNAPSHOT and snapshot_evidence is None:
            snapshot_evidence = e
        elif e.evidence_type == EvidenceType.BOOKMARK and bookmark_evidence is None:
            bookmark_evidence = e

    # If no evidence at all, return None
    if snapshot_evidence is None and bookmark_evidence is None:
        return None

    return ViolationEvidenceSummary(
        snapshot_id=snapshot_evidence.vas_snapshot_id if snapshot_evidence else None,
        snapshot_url=snapshot_evidence.snapshot_url if snapshot_evidence else None,
        snapshot_status=snapshot_evidence.status.value if snapshot_evidence else "pending",
        bookmark_id=bookmark_evidence.vas_bookmark_id if bookmark_evidence else None,
        bookmark_url=bookmark_evidence.bookmark_url if bookmark_evidence else None,
        bookmark_status=bookmark_evidence.status.value if bookmark_evidence else "pending",
        bookmark_duration_seconds=(
            bookmark_evidence.bookmark_duration_seconds if bookmark_evidence else None
        ),
    )


@router.get(
    "/violations",
    response_model=ViolationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List violations",
    description="Returns violations with optional filtering.",
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_violations(
    db: DBSession,
    violation_status: str | None = Query(None, alias="status", description="Filter by status"),
    device_id: UUID | None = Query(None, description="Filter by device"),
    since: datetime | None = Query(None, description="Violations after this timestamp"),
    until: datetime | None = Query(None, description="Violations before this timestamp"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> ViolationListResponse:
    """List all violations with optional filtering.

    Args:
        db: Database session
        violation_status: Filter by status
        device_id: Filter by device UUID
        since: Only violations after this timestamp
        until: Only violations before this timestamp
        limit: Maximum results to return
        offset: Pagination offset

    Returns:
        List of violations with total count
    """
    # Build query with eager loading of evidence
    stmt = (
        select(Violation)
        .options(selectinload(Violation.evidence))
        .order_by(Violation.timestamp.desc())
    )

    # Apply filters
    if violation_status is not None:
        stmt = stmt.where(Violation.status == violation_status)

    if device_id is not None:
        stmt = stmt.where(Violation.device_id == device_id)

    if since is not None:
        stmt = stmt.where(Violation.timestamp >= since)

    if until is not None:
        stmt = stmt.where(Violation.timestamp <= until)

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    violations = list(result.scalars().all())

    logger.info(
        "Listing violations",
        total=total,
        returned=len(violations),
        status=violation_status,
    )

    return ViolationListResponse(
        items=[
            ViolationResponse(
                id=v.id,
                type=v.type.value,
                status=v.status.value,
                camera_id=v.device_id,
                camera_name=v.camera_name,
                confidence=v.confidence,
                timestamp=v.timestamp,
                model_id=v.model_id,
                model_version=v.model_version,
                bounding_boxes=v.bounding_boxes,
                reviewed_by=v.reviewed_by,
                reviewed_at=v.reviewed_at,
                resolution_notes=v.resolution_notes,
                evidence=build_evidence_summary(list(v.evidence)),
                created_at=v.created_at,
                updated_at=v.updated_at,
            )
            for v in violations
        ],
        total=total,
    )


@router.get(
    "/violations/{violation_id}",
    response_model=ViolationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get violation details",
    description="Returns a single violation with associated evidence.",
    responses={
        404: {"model": ErrorResponse, "description": "Violation not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_violation(
    violation_id: UUID,
    violation_service: ViolationServiceDep,
    evidence_service: EvidenceServiceDep,
    db: DBSession,
) -> ViolationDetailResponse:
    """Get violation by ID with evidence.

    Args:
        violation_id: Violation UUID
        violation_service: Injected ViolationService
        db: Database session

    Returns:
        Violation details with evidence

    Raises:
        HTTPException: 404 if violation not found
    """
    try:
        violation = await violation_service.get_violation_by_id(violation_id)
    except ViolationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "violation_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Get evidence for violation
    evidence_stmt = (
        select(Evidence)
        .where(Evidence.violation_id == violation_id)
        .order_by(Evidence.requested_at.desc())
    )
    evidence_result = await db.execute(evidence_stmt)
    evidence_list = list(evidence_result.scalars().all())

    # Sync evidence status from VAS for any that are still processing
    for evidence in evidence_list:
        if evidence.status.value == "processing":
            try:
                await evidence_service.sync_evidence_status(evidence)
            except Exception as e:
                logger.warning(
                    "Failed to sync evidence status from VAS",
                    evidence_id=str(evidence.id),
                    error=str(e),
                )

    # Count events for violation
    event_count = await violation_service.count_events_for_violation(violation_id)

    logger.info("Retrieved violation", violation_id=str(violation_id))

    return ViolationDetailResponse(
        id=violation.id,
        type=violation.type.value,
        status=violation.status.value,
        camera_id=violation.device_id,
        camera_name=violation.camera_name,
        confidence=violation.confidence,
        timestamp=violation.timestamp,
        model_id=violation.model_id,
        model_version=violation.model_version,
        bounding_boxes=violation.bounding_boxes,
        reviewed_by=violation.reviewed_by,
        reviewed_at=violation.reviewed_at,
        resolution_notes=violation.resolution_notes,
        evidence=build_evidence_summary(evidence_list),
        event_count=event_count,
        created_at=violation.created_at,
        updated_at=violation.updated_at,
    )


@router.patch(
    "/violations/{violation_id}",
    response_model=ViolationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update violation status",
    description="Update violation status (mark reviewed, dismiss, or resolve).",
    responses={
        200: {"model": ViolationResponse, "description": "Violation updated"},
        400: {"model": ErrorResponse, "description": "Invalid status transition"},
        404: {"model": ErrorResponse, "description": "Violation not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def update_violation_status(
    violation_id: UUID,
    request: ViolationStatusUpdateRequest,
    violation_service: ViolationServiceDep,
) -> ViolationResponse:
    """Update violation status.

    Valid status transitions:
    - open -> reviewed, dismissed
    - reviewed -> dismissed, resolved
    - dismissed -> open (reopen)
    - resolved -> (terminal state, no transitions allowed)

    Args:
        violation_id: Violation UUID
        request: Status update request with new status
        violation_service: Injected ViolationService

    Returns:
        Updated violation

    Raises:
        HTTPException: 404 if violation not found, 400 if invalid transition
    """
    from app.models import ViolationStatus

    # Map status string to enum
    try:
        new_status = ViolationStatus(request.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_status",
                "message": f"Invalid status: {request.status}. Valid values: open, reviewed, dismissed, resolved",
                "details": {"provided_status": request.status},
            },
        )

    try:
        violation = await violation_service.transition_status(
            violation_id,
            new_status,
            reviewed_by=request.reviewed_by,
            resolution_notes=request.resolution_notes,
        )
    except ViolationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "violation_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e
    except ViolationTerminalStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "terminal_state",
                "message": str(e),
                "details": e.details,
            },
        ) from e
    except ViolationStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_transition",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    logger.info(
        "Updated violation status",
        violation_id=str(violation_id),
        new_status=new_status.value,
    )

    return ViolationResponse(
        id=violation.id,
        type=violation.type.value,
        status=violation.status.value,
        camera_id=violation.device_id,
        camera_name=violation.camera_name,
        confidence=violation.confidence,
        timestamp=violation.timestamp,
        model_id=violation.model_id,
        model_version=violation.model_version,
        bounding_boxes=violation.bounding_boxes,
        reviewed_by=violation.reviewed_by,
        reviewed_at=violation.reviewed_at,
        resolution_notes=violation.resolution_notes,
        evidence=None,  # Not needed for status update response
        created_at=violation.created_at,
        updated_at=violation.updated_at,
    )


@router.get(
    "/violations/{violation_id}/snapshot/image",
    summary="Get snapshot image",
    description="Proxy the snapshot image from VAS.",
    responses={
        200: {"description": "Image binary data", "content": {"image/jpeg": {}}},
        404: {"model": ErrorResponse, "description": "Snapshot not found or not ready"},
        502: {"model": ErrorResponse, "description": "VAS error"},
    },
)
async def get_snapshot_image(
    violation_id: UUID,
    evidence_service: EvidenceServiceDep,
    vas_client: VASClientDep,
) -> StreamingResponse:
    """Get the snapshot image for a violation.

    This endpoint proxies the image from VAS to the client.
    The snapshot must be in 'ready' status.

    Args:
        violation_id: Violation UUID
        evidence_service: Injected EvidenceService
        vas_client: Injected VAS client

    Returns:
        Streaming image response

    Raises:
        HTTPException: 404 if snapshot not found or not ready
    """
    # Get snapshot evidence for violation
    evidence_list = await evidence_service.get_evidence_for_violation(
        violation_id,
        evidence_type=EvidenceType.SNAPSHOT,
    )

    if not evidence_list:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "snapshot_not_found",
                "message": "No snapshot evidence found for this violation",
            },
        )

    evidence = evidence_list[0]  # Get most recent

    # Sync status from VAS if still processing
    if evidence.status.value == "processing":
        try:
            await evidence_service.sync_evidence_status(evidence)
        except Exception as e:
            logger.warning(
                "Failed to sync evidence status",
                evidence_id=str(evidence.id),
                error=str(e),
            )

    # Check if ready
    if evidence.status.value != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "snapshot_not_ready",
                "message": f"Snapshot is not ready (status: {evidence.status.value})",
                "status": evidence.status.value,
            },
        )

    if not evidence.vas_snapshot_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "snapshot_missing_vas_id",
                "message": "Snapshot has no VAS ID",
            },
        )

    logger.info(
        "Proxying VAS snapshot image",
        violation_id=str(violation_id),
        evidence_id=str(evidence.id),
        vas_snapshot_id=evidence.vas_snapshot_id,
    )

    # Stream the image from VAS
    try:
        async def stream_image():
            async with vas_client.download_snapshot_image(evidence.vas_snapshot_id) as response:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk

        return StreamingResponse(
            stream_image(),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=31536000",  # Cache for 1 year (immutable)
            },
        )
    except Exception as e:
        logger.error(
            "Failed to download snapshot from VAS",
            evidence_id=str(evidence.id),
            vas_snapshot_id=evidence.vas_snapshot_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "vas_error",
                "message": f"Failed to download snapshot from VAS: {e}",
            },
        ) from e


@router.post(
    "/violations/{violation_id}/snapshot",
    response_model=SnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create snapshot",
    description="Capture a snapshot for the violation. Idempotent - returns existing snapshot if already captured.",
    responses={
        201: {"model": SnapshotResponse, "description": "Snapshot created or returned"},
        404: {"model": ErrorResponse, "description": "Violation not found"},
        502: {"model": ErrorResponse, "description": "VAS error"},
        503: {"model": ErrorResponse, "description": "No active stream"},
    },
)
async def create_snapshot(
    violation_id: UUID,
    violation_service: ViolationServiceDep,
    evidence_service: EvidenceServiceDep,
    request: SnapshotCreateRequest | None = None,
) -> SnapshotResponse:
    """Create a snapshot for a violation.

    This endpoint is idempotent. If a snapshot already exists for the violation,
    it returns the existing snapshot information.

    Args:
        violation_id: Violation UUID
        violation_service: Injected ViolationService
        evidence_service: Injected EvidenceService
        request: Optional snapshot configuration

    Returns:
        Snapshot evidence information

    Raises:
        HTTPException: 404 if violation not found, 502 on VAS failure
    """
    # Get violation
    try:
        violation = await violation_service.get_violation_by_id(violation_id)
    except ViolationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "violation_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Create snapshot (idempotent - allow_existing=True)
    try:
        evidence = await evidence_service.create_snapshot(
            violation,
            allow_existing=True,
        )
    except NoActiveStreamError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "no_active_stream",
                "message": "No active stream available for snapshot capture",
                "details": e.details,
            },
        ) from e
    except EvidenceVASError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "vas_error",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    logger.info(
        "Created/retrieved snapshot",
        violation_id=str(violation_id),
        evidence_id=str(evidence.id),
        status=evidence.status.value,
    )

    return SnapshotResponse(
        evidence_id=evidence.id,
        violation_id=evidence.violation_id,
        status=evidence.status.value,
        vas_snapshot_id=evidence.vas_snapshot_id,
        requested_at=evidence.requested_at,
    )


@router.get(
    "/violations/{violation_id}/video",
    response_model=VideoEvidenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get video evidence",
    description="Get or create video evidence (bookmark) for a violation.",
    responses={
        200: {"model": VideoEvidenceResponse, "description": "Video evidence status"},
        404: {"model": ErrorResponse, "description": "Violation not found"},
        502: {"model": ErrorResponse, "description": "VAS error"},
        503: {"model": ErrorResponse, "description": "No active stream"},
    },
)
async def get_video_evidence(
    violation_id: UUID,
    violation_service: ViolationServiceDep,
    evidence_service: EvidenceServiceDep,
) -> VideoEvidenceResponse:
    """Get or create video evidence for a violation.

    Creates a bookmark (video clip) if one doesn't exist.
    Returns the current status of the video evidence.

    Args:
        violation_id: Violation UUID
        violation_service: Injected ViolationService
        evidence_service: Injected EvidenceService

    Returns:
        Video evidence information

    Raises:
        HTTPException: 404 if violation not found, 502 on VAS failure
    """
    # Get violation
    try:
        violation = await violation_service.get_violation_by_id(violation_id)
    except ViolationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "violation_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Try to get existing bookmark evidence
    existing_evidence = await evidence_service.get_evidence_for_violation(
        violation_id,
        evidence_type=EvidenceType.BOOKMARK,
    )

    evidence = None
    if existing_evidence:
        evidence = existing_evidence[0]  # Get most recent
    else:
        # Create bookmark (idempotent)
        try:
            evidence = await evidence_service.create_bookmark(
                violation,
                before_seconds=5,
                after_seconds=10,
                allow_existing=True,
            )
        except NoActiveStreamError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "no_active_stream",
                    "message": "No active stream available for video capture",
                    "details": e.details,
                },
            ) from e
        except EvidenceVASError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "vas_error",
                    "message": str(e),
                    "details": e.details,
                },
            ) from e

    logger.info(
        "Retrieved/created video evidence",
        violation_id=str(violation_id),
        evidence_id=str(evidence.id),
        status=evidence.status.value,
    )

    # Get video URL from VAS if ready
    video_url = None
    if evidence.status.value == "ready" and evidence.vas_bookmark_id:
        try:
            from app.deps import get_vas_client
            vas_client = get_vas_client()
            bookmark = await vas_client.get_bookmark(evidence.vas_bookmark_id)
            video_url = bookmark.video_url
        except Exception as e:
            logger.warning(
                "Failed to get bookmark video URL",
                evidence_id=str(evidence.id),
                error=str(e),
            )

    return VideoEvidenceResponse(
        evidence_id=evidence.id,
        violation_id=evidence.violation_id,
        status=evidence.status.value,
        vas_bookmark_id=evidence.vas_bookmark_id,
        duration_seconds=evidence.bookmark_duration_seconds,
        video_url=video_url,
        requested_at=evidence.requested_at,
        ready_at=evidence.ready_at,
    )

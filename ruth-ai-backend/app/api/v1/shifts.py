"""Shift schedule and shift-scoped violation count endpoints.

- GET  /settings/shift-schedule          read the site-global schedule
- PUT  /settings/shift-schedule          replace it (422 on overlap/gap)
- GET  /shifts/current                   the window containing now
- GET  /violations/counts/current-shift  per-camera unreviewed counts

The counts endpoint returns the window alongside the counts so a client
never has to compute shift boundaries itself, and so a rollover landing
between two polls cannot leave the displayed window and the displayed
numbers describing different shifts.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.logging import get_logger
from app.deps import DBSession
from app.models.app_setting import SHIFT_SCHEDULE_KEY, AppSetting
from app.schemas import ErrorResponse
from app.schemas.shift import (
    CurrentShiftResponse,
    ShiftScheduleResponse,
    ShiftScheduleUpdateRequest,
    ShiftViolationCountsResponse,
)
from app.services.shift_schedule import ShiftSchedule, ShiftScheduleError, ShiftWindow
from app.services.shift_service import ShiftService
from sqlalchemy import select

router = APIRouter(tags=["Shifts"])
logger = get_logger(__name__)


def _to_current_shift_response(window: ShiftWindow, now: datetime) -> CurrentShiftResponse:
    return CurrentShiftResponse(
        name=window.name,
        start=window.start,
        end=window.end,
        mode=window.mode,
        timezone=window.timezone,
        server_time=now,
    )


@router.get(
    "/settings/shift-schedule",
    response_model=ShiftScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the site shift schedule",
    description=(
        "Returns the site-global shift schedule. When none has been saved, "
        "returns the continuous 24h default with is_configured=false."
    ),
)
async def get_shift_schedule(db: DBSession) -> ShiftScheduleResponse:
    """Read the site-global shift schedule."""
    service = ShiftService(db)
    schedule = await service.get_schedule()

    exists = await db.execute(
        select(AppSetting.id).where(AppSetting.key == SHIFT_SCHEDULE_KEY)
    )
    is_configured = exists.scalars().first() is not None

    return ShiftScheduleResponse(
        **schedule.model_dump(mode="json"),
        is_configured=is_configured,
    )


@router.put(
    "/settings/shift-schedule",
    response_model=ShiftScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace the site shift schedule",
    description=(
        "Replaces the site-global shift schedule. Shifts must tile the full "
        "24 hours: overlaps and gaps are both rejected with 422."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Shifts overlap or leave a gap"},
    },
)
async def put_shift_schedule(
    request: ShiftScheduleUpdateRequest,
    db: DBSession,
) -> ShiftScheduleResponse:
    """Validate and persist the site-global shift schedule."""
    service = ShiftService(db)

    schedule = ShiftSchedule(
        mode=request.mode,
        timezone=request.timezone,
        shifts=request.shifts,
    )

    try:
        saved = await service.set_schedule(schedule, updated_by=request.updated_by)
    except ShiftScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_shift_schedule",
                "message": exc.message,
                "details": {"conflicts": exc.conflicts},
            },
        ) from exc

    return ShiftScheduleResponse(**saved.model_dump(mode="json"), is_configured=True)


@router.get(
    "/shifts/current",
    response_model=CurrentShiftResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the current shift window",
    description=(
        "Returns the shift containing the server's current instant, with "
        "absolute UTC bounds. Handles shifts that cross midnight."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Stored schedule leaves now uncovered"},
    },
)
async def get_current_shift(db: DBSession) -> CurrentShiftResponse:
    """Resolve the shift window containing this instant."""
    service = ShiftService(db)
    now = datetime.now(timezone.utc)

    try:
        window = await service.get_current_window(now)
    except ShiftScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "no_current_shift",
                "message": exc.message,
                "details": {"conflicts": exc.conflicts},
            },
        ) from exc

    return _to_current_shift_response(window, now)


@router.get(
    "/violations/counts/current-shift",
    response_model=ShiftViolationCountsResponse,
    status_code=status.HTTP_200_OK,
    summary="Per-camera unreviewed violation counts for the current shift",
    description=(
        "Counts violations that were detected within the current shift window "
        "and are still unreviewed (status=open), grouped by camera, across all "
        "model types on the feed. One request serves an entire monitoring grid."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Stored schedule leaves now uncovered"},
    },
)
async def get_current_shift_violation_counts(
    db: DBSession,
    camera_ids: str | None = Query(
        None,
        description="Comma-separated camera UUIDs. Omit to count every camera.",
    ),
) -> ShiftViolationCountsResponse:
    """Count this shift's still-unreviewed violations per camera."""
    service = ShiftService(db)
    now = datetime.now(timezone.utc)

    try:
        window = await service.get_current_window(now)
    except ShiftScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "no_current_shift",
                "message": exc.message,
                "details": {"conflicts": exc.conflicts},
            },
        ) from exc

    requested: list[UUID] = []
    if camera_ids:
        for raw in camera_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                requested.append(UUID(raw))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "invalid_camera_id",
                        "message": f"Not a valid camera UUID: {raw!r}",
                    },
                ) from exc

    counts = await service.count_unreviewed_by_camera(window, requested or None)

    # A camera with nothing outstanding is absent from the GROUP BY. The
    # card must show "0 violations" rather than "--", so fill in the
    # cameras that were asked about.
    for camera_id in requested:
        counts.setdefault(camera_id, 0)

    logger.info(
        "Current-shift violation counts",
        shift=window.name,
        cameras=len(counts),
        total=sum(counts.values()),
    )

    return ShiftViolationCountsResponse(
        shift=_to_current_shift_response(window, now),
        counts=counts,
    )

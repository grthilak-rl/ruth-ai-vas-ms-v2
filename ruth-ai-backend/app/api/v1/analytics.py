"""Analytics API endpoints.

From API Contract - Analytics APIs:
- GET    /analytics/summary (Enhanced with time range, granularity, breakdowns)
- GET    /analytics/violations/trends (Time series trends)
- GET    /analytics/devices/status (Per-device analytics)
- POST   /analytics/export (CSV/XLSX/PDF exports)

Aligned with analytics-design.md Section 8.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Query, status
from sqlalchemy import and_, case, func, select

from fastapi.responses import Response

from app.core.logging import get_logger
from app.deps import DBSession
from app.models import Device, StreamSession, StreamState, Violation, ViolationStatus
from app.schemas import (
    AnalyticsComparison,
    AnalyticsNotImplementedResponse,
    AnalyticsSummaryResponse,
    AnalyticsTotals,
    CameraBreakdown,
    DeviceAnalytics,
    DeviceStatusResponse,
    DeviceStatusSummary,
    ErrorResponse,
    ExportRequest,
    StatusBreakdown,
    TimeRange,
    TimeSeriesBucket,
    TypeBreakdown,
    ViolationTrendBucket,
    ViolationTrendsResponse,
)
from app.services.export_service import ExportService

router = APIRouter(tags=["Analytics"])
logger = get_logger(__name__)


@router.get(
    "/analytics/summary",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get analytics summary",
    description="Returns aggregated analytics summary with breakdowns and time series. Per analytics-design.md §8.1.",
    responses={
        200: {"model": AnalyticsSummaryResponse, "description": "Analytics summary"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_analytics_summary(
    db: DBSession,
    from_time: datetime | None = Query(
        None, alias="from", description="Start of time range (ISO 8601)"
    ),
    to_time: datetime | None = Query(
        None, alias="to", description="End of time range (ISO 8601)"
    ),
    granularity: Literal["hour", "day"] = Query(
        "hour", description="Time series granularity"
    ),
) -> AnalyticsSummaryResponse:
    """Get analytics summary with enhanced breakdowns.

    Returns aggregated counts, per-camera/type/status breakdowns, and time series.
    Aligned with analytics-design.md §8.1.

    Args:
        db: Database session
        from_time: Start of time range (default: 24h ago)
        to_time: End of time range (default: now)
        granularity: Time series granularity (hour or day)

    Returns:
        Enhanced analytics summary
    """
    now = datetime.now(timezone.utc)
    to_time = to_time or now
    from_time = from_time or (to_time - timedelta(hours=24))

    logger.info(
        "Analytics summary requested",
        from_time=from_time.isoformat(),
        to_time=to_time.isoformat(),
        granularity=granularity,
    )

    # Base filter for time range
    time_filter = and_(
        Violation.timestamp >= from_time,
        Violation.timestamp < to_time,
    )

    # Count total violations in range
    total_stmt = select(func.count()).select_from(Violation).where(time_filter)
    result = await db.execute(total_stmt)
    violations_total = result.scalar() or 0

    # Count violations by status
    status_counts = {}
    for status_val in ViolationStatus:
        stmt = (
            select(func.count())
            .select_from(Violation)
            .where(and_(time_filter, Violation.status == status_val))
        )
        result = await db.execute(stmt)
        status_counts[status_val.value] = result.scalar() or 0

    # Count active cameras (with LIVE streams)
    active_cameras_stmt = (
        select(func.count(func.distinct(StreamSession.device_id)))
        .select_from(StreamSession)
        .where(StreamSession.state == StreamState.LIVE)
    )
    result = await db.execute(active_cameras_stmt)
    cameras_active = result.scalar() or 0

    # Count total cameras
    total_cameras_stmt = select(func.count()).select_from(Device).where(Device.is_active == True)
    result = await db.execute(total_cameras_stmt)
    cameras_total = result.scalar() or 0

    # Build totals
    totals = AnalyticsTotals(
        violations_total=violations_total,
        violations_open=status_counts.get("open", 0),
        violations_reviewed=status_counts.get("reviewed", 0),
        violations_dismissed=status_counts.get("dismissed", 0),
        violations_resolved=status_counts.get("resolved", 0),
        cameras_active=cameras_active,
        cameras_total=cameras_total,
    )

    # Comparison to previous period
    comparison = await _compute_comparison(db, from_time, to_time, violations_total)

    # Per-camera breakdown
    by_camera = await _get_camera_breakdown(db, time_filter)

    # Per-type breakdown
    by_type = await _get_type_breakdown(db, time_filter, violations_total)

    # Per-status breakdown
    by_status = await _get_status_breakdown(db, time_filter, violations_total)

    # Time series
    time_series = await _get_time_series(db, from_time, to_time, granularity)

    return AnalyticsSummaryResponse(
        time_range=TimeRange(from_=from_time, to=to_time),
        totals=totals,
        comparison=comparison,
        by_camera=by_camera,
        by_type=by_type,
        by_status=by_status,
        time_series=time_series,
        generated_at=now,
    )


async def _compute_comparison(
    db: DBSession,
    from_time: datetime,
    to_time: datetime,
    current_total: int,
) -> AnalyticsComparison | None:
    """Compute comparison to previous period."""
    period_duration = to_time - from_time
    prev_from = from_time - period_duration
    prev_to = from_time

    prev_stmt = (
        select(func.count())
        .select_from(Violation)
        .where(
            and_(
                Violation.timestamp >= prev_from,
                Violation.timestamp < prev_to,
            )
        )
    )
    result = await db.execute(prev_stmt)
    prev_total = result.scalar() or 0

    if prev_total == 0:
        return None

    change = current_total - prev_total
    change_percent = (change / prev_total) * 100 if prev_total > 0 else 0.0

    return AnalyticsComparison(
        violations_total_change=change,
        violations_total_change_percent=round(change_percent, 1),
    )


async def _get_camera_breakdown(
    db: DBSession,
    time_filter,
) -> list[CameraBreakdown]:
    """Get per-camera violation breakdown."""
    stmt = (
        select(
            Device.id,
            Device.name,
            func.count(Violation.id).label("total"),
            func.sum(
                case((Violation.status == ViolationStatus.OPEN, 1), else_=0)
            ).label("open"),
            func.sum(
                case((Violation.status == ViolationStatus.REVIEWED, 1), else_=0)
            ).label("reviewed"),
            func.sum(
                case((Violation.status == ViolationStatus.DISMISSED, 1), else_=0)
            ).label("dismissed"),
            func.sum(
                case((Violation.status == ViolationStatus.RESOLVED, 1), else_=0)
            ).label("resolved"),
        )
        .select_from(Violation)
        .join(Device, Violation.device_id == Device.id)
        .where(time_filter)
        .group_by(Device.id, Device.name)
        .order_by(func.count(Violation.id).desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        CameraBreakdown(
            camera_id=str(row.id),
            camera_name=row.name,
            violations_total=row.total or 0,
            violations_open=row.open or 0,
            violations_reviewed=row.reviewed or 0,
            violations_dismissed=row.dismissed or 0,
            violations_resolved=row.resolved or 0,
        )
        for row in rows
    ]


async def _get_type_breakdown(
    db: DBSession,
    time_filter,
    total: int,
) -> list[TypeBreakdown]:
    """Get violation type breakdown."""
    stmt = (
        select(
            Violation.type,
            func.count(Violation.id).label("count"),
        )
        .select_from(Violation)
        .where(time_filter)
        .group_by(Violation.type)
        .order_by(func.count(Violation.id).desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        TypeBreakdown(
            type=row.type.value,
            type_display=row.type.value.replace("_", " ").title(),
            count=row.count,
            percentage=round((row.count / total * 100) if total > 0 else 0, 1),
        )
        for row in rows
    ]


async def _get_status_breakdown(
    db: DBSession,
    time_filter,
    total: int,
) -> list[StatusBreakdown]:
    """Get violation status breakdown."""
    stmt = (
        select(
            Violation.status,
            func.count(Violation.id).label("count"),
        )
        .select_from(Violation)
        .where(time_filter)
        .group_by(Violation.status)
        .order_by(func.count(Violation.id).desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        StatusBreakdown(
            status=row.status.value,
            count=row.count,
            percentage=round((row.count / total * 100) if total > 0 else 0, 1),
        )
        for row in rows
    ]


async def _get_time_series(
    db: DBSession,
    from_time: datetime,
    to_time: datetime,
    granularity: Literal["hour", "day"],
) -> list[TimeSeriesBucket]:
    """Get time series data with specified granularity."""
    # Use PostgreSQL date_trunc for time bucketing
    trunc_format = granularity  # 'hour' or 'day'

    stmt = (
        select(
            func.date_trunc(trunc_format, Violation.timestamp).label("bucket"),
            func.count(Violation.id).label("total"),
            Violation.type,
        )
        .select_from(Violation)
        .where(
            and_(
                Violation.timestamp >= from_time,
                Violation.timestamp < to_time,
            )
        )
        .group_by("bucket", Violation.type)
        .order_by("bucket")
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Group by bucket
    buckets: dict[datetime, dict[str, int]] = {}
    for row in rows:
        bucket_time = row.bucket
        if bucket_time not in buckets:
            buckets[bucket_time] = {}
        buckets[bucket_time][row.type.value] = row.total

    # Convert to response format
    return [
        TimeSeriesBucket(
            bucket=bucket_time,
            total=sum(by_type.values()),
            by_type=by_type,
        )
        for bucket_time, by_type in sorted(buckets.items())
    ]


@router.get(
    "/analytics/violations/trends",
    response_model=ViolationTrendsResponse,
    status_code=status.HTTP_200_OK,
    summary="Violation trends analytics",
    description="Returns violation trends over time with granularity control. Per analytics-design.md §8.2.",
    responses={
        200: {"model": ViolationTrendsResponse, "description": "Violation trends"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_violations_trends(
    db: DBSession,
    from_time: datetime | None = Query(
        None, alias="from", description="Start of time range (ISO 8601)"
    ),
    to_time: datetime | None = Query(
        None, alias="to", description="End of time range (ISO 8601)"
    ),
    granularity: Literal["minute", "hour", "day"] = Query(
        "hour", description="Time bucket granularity"
    ),
    camera_id: str | None = Query(None, description="Filter by camera ID"),
    violation_type: str | None = Query(None, description="Filter by violation type"),
) -> ViolationTrendsResponse:
    """Get violation trends over time.

    Returns time-bucketed violation counts with breakdowns by type and status.

    Args:
        db: Database session
        from_time: Start of time range (default: 24h ago)
        to_time: End of time range (default: now)
        granularity: Time bucket size (minute, hour, or day)
        camera_id: Optional camera filter
        violation_type: Optional violation type filter

    Returns:
        Violation trends data
    """
    now = datetime.now(timezone.utc)
    to_time = to_time or now
    from_time = from_time or (to_time - timedelta(hours=24))

    logger.info(
        "Violation trends requested",
        from_time=from_time.isoformat(),
        to_time=to_time.isoformat(),
        granularity=granularity,
        camera_id=camera_id,
        violation_type=violation_type,
    )

    # Build filters
    filters = [
        Violation.timestamp >= from_time,
        Violation.timestamp < to_time,
    ]

    if camera_id:
        filters.append(Violation.device_id == camera_id)

    if violation_type:
        filters.append(Violation.type == violation_type)

    # Query for time series with type and status breakdowns
    stmt = (
        select(
            func.date_trunc(granularity, Violation.timestamp).label("bucket"),
            Violation.type,
            Violation.status,
            func.count(Violation.id).label("count"),
        )
        .select_from(Violation)
        .where(and_(*filters))
        .group_by("bucket", Violation.type, Violation.status)
        .order_by("bucket")
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Aggregate by bucket
    buckets: dict[datetime, dict] = {}
    for row in rows:
        bucket_time = row.bucket
        if bucket_time not in buckets:
            buckets[bucket_time] = {
                "by_type": {},
                "by_status": {},
                "total": 0,
            }

        type_key = row.type.value
        status_key = row.status.value

        buckets[bucket_time]["by_type"][type_key] = (
            buckets[bucket_time]["by_type"].get(type_key, 0) + row.count
        )
        buckets[bucket_time]["by_status"][status_key] = (
            buckets[bucket_time]["by_status"].get(status_key, 0) + row.count
        )
        buckets[bucket_time]["total"] += row.count

    # Convert to response format
    data = [
        ViolationTrendBucket(
            bucket=bucket_time,
            total=bucket_data["total"],
            by_type=bucket_data["by_type"],
            by_status=bucket_data["by_status"],
        )
        for bucket_time, bucket_data in sorted(buckets.items())
    ]

    return ViolationTrendsResponse(
        time_range=TimeRange(from_=from_time, to=to_time),
        granularity=granularity,
        data=data,
        generated_at=now,
    )


@router.get(
    "/analytics/devices/status",
    response_model=DeviceStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Device status analytics",
    description="Returns per-device analytics summary. Per analytics-design.md §8.2.",
    responses={
        200: {"model": DeviceStatusResponse, "description": "Device status analytics"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_devices_status(
    db: DBSession,
    from_time: datetime | None = Query(
        None, alias="from", description="Start of time range (ISO 8601)"
    ),
    to_time: datetime | None = Query(
        None, alias="to", description="End of time range (ISO 8601)"
    ),
) -> DeviceStatusResponse:
    """Get device status analytics.

    Returns per-device violation breakdown and summary.

    Args:
        db: Database session
        from_time: Start of time range (default: 24h ago)
        to_time: End of time range (default: now)

    Returns:
        Device status analytics
    """
    now = datetime.now(timezone.utc)
    to_time = to_time or now
    from_time = from_time or (to_time - timedelta(hours=24))

    logger.info(
        "Device status analytics requested",
        from_time=from_time.isoformat(),
        to_time=to_time.isoformat(),
    )

    # Query per-device statistics
    # For each device, get: violation counts by status, by type, avg confidence, last violation time
    devices_data = []

    # Get all devices
    devices_stmt = select(Device).where(Device.is_active == True)
    devices_result = await db.execute(devices_stmt)
    all_devices = devices_result.scalars().all()

    total_violations = 0

    for device in all_devices:
        # Count violations for this device in time range
        violations_stmt = (
            select(Violation)
            .where(
                and_(
                    Violation.device_id == device.id,
                    Violation.timestamp >= from_time,
                    Violation.timestamp < to_time,
                )
            )
        )
        violations_result = await db.execute(violations_stmt)
        violations = violations_result.scalars().all()

        if not violations:
            # Skip devices with no violations in range
            continue

        violations_total = len(violations)
        total_violations += violations_total

        # Build status breakdown
        violations_by_status = {}
        for v in violations:
            status_key = v.status.value
            violations_by_status[status_key] = violations_by_status.get(status_key, 0) + 1

        # Build type breakdown
        violations_by_type = {}
        for v in violations:
            type_key = v.type.value
            violations_by_type[type_key] = violations_by_type.get(type_key, 0) + 1

        # Calculate average confidence
        avg_confidence = sum(v.confidence for v in violations) / len(violations)

        # Get last violation timestamp
        last_violation_at = max(v.timestamp for v in violations)

        devices_data.append(
            DeviceAnalytics(
                camera_id=str(device.id),
                camera_name=device.name,
                violations_total=violations_total,
                violations_by_status=violations_by_status,
                violations_by_type=violations_by_type,
                avg_confidence=round(avg_confidence, 2),
                last_violation_at=last_violation_at,
            )
        )

    # Sort by violation count (descending)
    devices_data.sort(key=lambda d: d.violations_total, reverse=True)

    # Count active cameras
    active_cameras_stmt = (
        select(func.count(func.distinct(StreamSession.device_id)))
        .select_from(StreamSession)
        .where(StreamSession.state == StreamState.LIVE)
    )
    active_result = await db.execute(active_cameras_stmt)
    active_cameras = active_result.scalar() or 0

    summary = DeviceStatusSummary(
        total_violations=total_violations,
        total_cameras=len(all_devices),
        active_cameras=active_cameras,
    )

    return DeviceStatusResponse(
        time_range=TimeRange(from_=from_time, to=to_time),
        devices=devices_data,
        summary=summary,
        generated_at=now,
    )


@router.post(
    "/analytics/export",
    status_code=status.HTTP_200_OK,
    summary="Export analytics data",
    description="Generate and download analytics export in CSV, XLSX, or PDF format. Per analytics-design.md §8.2.",
    responses={
        200: {"description": "Export file download"},
        400: {"model": ErrorResponse, "description": "Invalid export configuration"},
        503: {"model": ErrorResponse, "description": "Export generation failed"},
    },
)
async def export_analytics(
    db: DBSession,
    request: ExportRequest,
) -> Response:
    """Export analytics data.

    Generates a downloadable file in the requested format (CSV, XLSX, or PDF)
    containing violations data matching the specified filters.

    Args:
        db: Database session
        request: Export configuration

    Returns:
        Binary file download with appropriate Content-Type and Content-Disposition
    """
    from_time = request.time_range.from_
    to_time = request.time_range.to

    # Validate time range
    max_range_days = 90
    if (to_time - from_time).days > max_range_days:
        logger.warning(
            "Export time range exceeds maximum",
            from_time=from_time.isoformat(),
            to_time=to_time.isoformat(),
            max_days=max_range_days,
        )
        return Response(
            content='{"error":"INVALID_EXPORT_CONFIG","error_description":"Time range exceeds maximum allowed (90 days)","status_code":400}',
            status_code=400,
            media_type="application/json",
        )

    logger.info(
        "Export requested",
        format=request.format,
        from_time=from_time.isoformat(),
        to_time=to_time.isoformat(),
        scope_all=request.scope.all,
    )

    try:
        # Initialize export service
        export_service = ExportService(db)

        # Prepare filters
        camera_ids = None if request.scope.all else request.scope.camera_ids or None
        violation_types = None if request.scope.all else request.scope.violation_types or None
        statuses = None if request.scope.all else request.scope.statuses or None

        # Generate export
        file_bytes, content_type, filename = await export_service.export_violations(
            format=request.format,
            from_time=from_time,
            to_time=to_time,
            camera_ids=camera_ids,
            violation_types=violation_types,
            statuses=statuses,
            include_headers=request.options.include_headers,
            include_timestamps=request.options.include_timestamps,
            include_raw_confidence=request.options.include_raw_confidence,
            include_evidence_urls=request.options.include_evidence_urls,
            include_bounding_boxes=request.options.include_bounding_boxes,
        )

        logger.info(
            "Export generated",
            format=request.format,
            filename=filename,
            size_bytes=len(file_bytes),
        )

        # Return file as download
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except Exception as e:
        logger.error(
            "Export generation failed",
            error=str(e),
            format=request.format,
        )
        return Response(
            content='{"error":"EXPORT_GENERATION_FAILED","error_description":"Could not generate export. Please try again.","status_code":503}',
            status_code=503,
            media_type="application/json",
        )

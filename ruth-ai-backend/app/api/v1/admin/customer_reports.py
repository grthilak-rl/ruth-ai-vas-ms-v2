"""Customer report API (admin protected_router).

- GET  /admin/customer-reports/defaults        periods the Export page offers
- POST /admin/customer-reports                 start building one
- GET  /admin/customer-reports                 recent reports, newest first
- GET  /admin/customer-reports/{id}            progress
- GET  /admin/customer-reports/{id}/download   the PDF

Admin-only, like the evidence export: the PDF carries cropped frames of
identifiable workers in one shareable file, and the recent list names who
generated each report, which only the admin login can attest. The raw-data
exports on the same page are unchanged.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.core.admin_auth import AdminUser
from app.core.config import get_settings
from app.core.logging import get_logger
from app.deps import DBSession
from app.models.customer_report import CustomerReport
from app.models.project import Project
from app.models.violation_export import EXPORT_READY
from app.schemas.customer_report import (
    GALLERY_SIZES,
    CustomerReportDefaults,
    CustomerReportJob,
    CustomerReportList,
    CustomerReportRequest,
)
from app.services.report.data import day_offset_minutes, report_day_of
from app.services.report.job import PeriodError, report_period, run_report_job
from app.services.shift_service import ShiftService

logger = get_logger(__name__)

router = APIRouter(prefix="/customer-reports", tags=["Admin"])

#: Strong references to in-flight builds, so a build is not garbage
#: collected half-written.
_background: set = set()


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": "no such report"},
    )


@router.get("/defaults", response_model=CustomerReportDefaults, summary="Report period defaults")
async def report_defaults(db: DBSession, _admin: AdminUser) -> CustomerReportDefaults:
    schedule = await ShiftService(db).get_schedule()
    offset = day_offset_minutes(schedule)
    now_local = datetime.now(schedule.tzinfo)
    active = (
        await db.execute(select(Project).where(Project.state == "active"))
    ).scalars().first()
    settings = get_settings()
    return CustomerReportDefaults(
        timezone=schedule.timezone,
        day_start=f"{offset // 60:02d}:{offset % 60:02d}",
        # The report day in progress is not over; the one before it is.
        last_complete_day=report_day_of(now_local, offset) - timedelta(days=1),
        project_started_on=(
            report_day_of(active.started_at.astimezone(schedule.tzinfo), offset) if active else None
        ),
        max_custom_days=settings.customer_report_max_days,
        retention_days=settings.customer_report_retention_days,
        gallery_sizes=list(GALLERY_SIZES),
        default_gallery_size=12,
    )


@router.post(
    "",
    response_model=CustomerReportJob,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start building a customer report",
)
async def create_report(
    request: CustomerReportRequest, db: DBSession, admin: AdminUser
) -> CustomerReportJob:
    schedule = await ShiftService(db).get_schedule()
    try:
        start, end, label = report_period(
            request.preset, schedule, day=request.day, start=request.start, end=request.end
        )
    except PeriodError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_period", "message": str(e)},
        ) from e

    now = datetime.now(timezone.utc)
    row = CustomerReport(
        format=request.format,
        preset=request.preset,
        mode=request.mode,
        period_start=start,
        period_end=end,
        period_label=label,
        options=request.model_dump(mode="json"),
        stage="Queued",
        total=4,
        created_by=admin.username,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Build after the response: the job owns its own session, because this
    # request's session closes as soon as we return.
    from app.core.database import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:  # pragma: no cover - startup ordering
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "not_ready", "message": "database not initialised"},
        )
    task = asyncio.create_task(run_report_job(row.id, session_factory))
    _background.add(task)
    task.add_done_callback(_background.discard)

    logger.info(
        "Customer report requested",
        report_id=str(row.id),
        preset=request.preset,
        period=label,
        mode=request.mode,
        gallery=request.gallery,
        by=admin.username,
    )
    return CustomerReportJob.model_validate(row)


@router.get("", response_model=CustomerReportList, summary="Recent customer reports")
async def list_reports(
    db: DBSession,
    _admin: AdminUser,
    limit: int = Query(20, ge=1, le=100),
) -> CustomerReportList:
    total = (await db.execute(select(func.count()).select_from(CustomerReport))).scalar_one()
    rows = (
        await db.execute(
            select(CustomerReport).order_by(CustomerReport.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return CustomerReportList(items=[CustomerReportJob.model_validate(r) for r in rows], total=total)


@router.get("/{report_id}", response_model=CustomerReportJob, summary="Report progress")
async def get_report(report_id: uuid.UUID, db: DBSession, _admin: AdminUser) -> CustomerReportJob:
    row = await db.get(CustomerReport, report_id)
    if row is None:
        raise _not_found()
    return CustomerReportJob.model_validate(row)


@router.get("/{report_id}/download", summary="Download the report")
async def download_report(report_id: uuid.UUID, db: DBSession, _admin: AdminUser) -> FileResponse:
    row = await db.get(CustomerReport, report_id)
    if row is None:
        raise _not_found()
    if row.status != EXPORT_READY or not row.file_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "not_ready", "message": f"report is {row.status}", "status": row.status},
        )
    root = Path(get_settings().customer_report_dir).resolve()
    resolved = Path(row.file_path).resolve()
    # Our own row's path, but still a filesystem path reaching a download.
    if not resolved.is_relative_to(root) or not resolved.is_file():
        logger.warning("Report file missing at download", report_id=str(report_id))
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error": "file_gone", "message": "the report is no longer on disk"},
        )
    return FileResponse(
        resolved,
        media_type="application/pdf",
        filename=row.filename or f"safety-report-{report_id}.pdf",
    )

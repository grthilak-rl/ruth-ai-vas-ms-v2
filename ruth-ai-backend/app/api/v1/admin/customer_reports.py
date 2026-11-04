"""Customer report API (admin protected_router).

- GET  /admin/customer-reports/defaults        periods the Export page offers
- POST /admin/customer-reports/gallery-preview  the evidence the report would show
- POST /admin/customer-reports                 start building one
- GET  /admin/customer-reports                 recent reports, newest first
- GET  /admin/customer-reports/{id}            progress
- GET  /admin/customer-reports/{id}/download   the PDF
- POST /admin/customer-reports/{id}/regenerate the same report again, built now
- GET/PUT /admin/customer-reports/auto-settings  automatic per-shift reports

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
from app.models.customer_report import TRIGGER_MANUAL, TRIGGER_REGENERATE, CustomerReport
from app.models.enums import ViolationStatus
from app.models.violation import Violation
from app.models.project import CURRENT_PROJECT_STATES, Project
from app.models.violation_export import EXPORT_READY
from app.schemas.customer_report import (
    GALLERY_SIZES,
    AutoReportSettingsIn,
    AutoReportSettingsOut,
    CustomerReportDefaults,
    ShiftOption,
    GalleryCandidate,
    GalleryPreview,
    CustomerReportJob,
    CustomerReportList,
    CustomerReportRequest,
)
from app.services.report.data import (
    shift_occurrence,
    day_offset_minutes,
    load_report,
    report_day_of,
    select_gallery,
)
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
        await db.execute(select(Project).where(Project.state.in_(CURRENT_PROJECT_STATES)))
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
        shifts=[
            ShiftOption(name=s.name, start=s.start, end=s.end)
            for s in (schedule.shifts if schedule.mode == "shifts" else [])
        ],
        **_last_complete_shift(schedule),
    )


def _last_complete_shift(schedule) -> dict:
    """The newest shift occurrence that has ended, as (shift day, name)."""
    if schedule.mode != "shifts" or not schedule.shifts:
        return {}
    now = datetime.now(timezone.utc)
    offset = day_offset_minutes(schedule)
    today = report_day_of(now.astimezone(schedule.tzinfo), offset)
    ended = [
        (shift_occurrence(day, schedule, s.name)[1], day, s.name)
        for day in (today - timedelta(days=1), today)
        for s in schedule.shifts
        if shift_occurrence(day, schedule, s.name)[1] <= now
    ]
    if not ended:
        return {}
    _end, day, name = max(ended)
    return {"last_complete_shift_day": day, "last_complete_shift": name}


async def _period_or_422(request: CustomerReportRequest, db):
    schedule = await ShiftService(db).get_schedule()
    try:
        return report_period(
            request.preset, schedule, day=request.day, start=request.start, end=request.end,
            shift=request.shift,
        )
    except PeriodError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_period", "message": str(e)},
        ) from e


@router.post(
    "/gallery-preview",
    response_model=GalleryPreview,
    summary="Evidence gallery candidates for a report",
)
async def gallery_preview(
    request: CustomerReportRequest, db: DBSession, _admin: AdminUser
) -> GalleryPreview:
    """What the gallery would show, minus ``gallery_exclude``.

    The same selection the build uses, so an approved set is the printed set.
    The admin removes a candidate by adding its key to ``gallery_exclude``
    and asking again; the next candidate fills in.
    """
    start, end, _ = await _period_or_422(request, db)
    report = await load_report(
        db, start=start, end=end, preset=request.preset, mode=request.mode, shift=request.shift
    )
    picks = await select_gallery(db, report, request.gallery_size, request.gallery_exclude)
    return GalleryPreview(
        items=[
            GalleryCandidate(
                key=p.incident.key,
                violation_id=p.violation_id,
                area=p.incident.area,
                camera=p.incident.camera,
                type_label=p.incident.type_label,
                severity=p.incident.severity,
                started=f"{p.incident.started_at:%a %-d %b, %H:%M}",
                minutes=max(1, round(p.incident.duration_minutes)),
                detections=p.incident.detections,
            )
            for p in picks
        ],
        incidents=report.current.incidents,
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
    start, end, label = await _period_or_422(request, db)

    now = datetime.now(timezone.utc)
    row = CustomerReport(
        format=request.format,
        preset=request.preset,
        mode=request.mode,
        period_start=start,
        period_end=end,
        period_label=label,
        options=request.model_dump(mode="json"),
        shift_name=request.shift if request.preset == "shift" else None,
        trigger=TRIGGER_MANUAL,
        attempts=1,
        stage="Queued",
        total=4,
        created_by=admin.username,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    _start_build(row.id)

    logger.info(
        "Customer report requested",
        report_id=str(row.id),
        preset=request.preset,
        period=label,
        mode=request.mode,
        gallery=request.gallery,
        gallery_removed=len(request.gallery_exclude),
        by=admin.username,
    )
    return CustomerReportJob.model_validate(row)


def _start_build(report_id: uuid.UUID) -> None:
    """Build after the response: the job owns its own session, because the
    request's session closes as soon as we return."""
    from app.core.database import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:  # pragma: no cover - startup ordering
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "not_ready", "message": "database not initialised"},
        )
    task = asyncio.create_task(run_report_job(report_id, session_factory))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _view(db, rows) -> list[CustomerReportJob]:
    """Rows as API items, with "N dismissed since built" for ready ones.

    Dismissing does not stamp reviewed_at, so "since" is the violation's
    last change: dismissed now, and changed after the report was built.
    """
    out = []
    for row in rows:
        item = CustomerReportJob.model_validate(row)
        if row.status == EXPORT_READY:
            item.dismissed_since = (
                await db.execute(
                    select(func.count()).select_from(Violation).where(
                        Violation.timestamp >= row.period_start,
                        Violation.timestamp < row.period_end,
                        Violation.status == ViolationStatus.DISMISSED,
                        Violation.updated_at > row.created_at,
                    )
                )
            ).scalar_one()
        out.append(item)
    return out


@router.get("/auto-settings", response_model=AutoReportSettingsOut, summary="Automatic shift reports")
async def read_auto_settings(db: DBSession, _admin: AdminUser) -> AutoReportSettingsOut:
    from app.services.report.auto import auto_report_scheduler, get_auto_settings

    settings, row = await get_auto_settings(db)
    return AutoReportSettingsOut(
        **settings.model_dump(),
        updated_by=row.updated_by if row else None,
        idle_reason=auto_report_scheduler.idle_reason,
        last_tick_at=auto_report_scheduler.last_tick_at,
    )


@router.put("/auto-settings", response_model=AutoReportSettingsOut, summary="Change automatic shift reports")
async def update_auto_settings(
    body: AutoReportSettingsIn, db: DBSession, admin: AdminUser
) -> AutoReportSettingsOut:
    from app.services.report.auto import save_auto_settings

    await save_auto_settings(
        db, enabled=body.enabled, settle_minutes=body.settle_minutes, by=admin.username
    )
    logger.info(
        "Auto shift reports changed",
        enabled=body.enabled, settle_minutes=body.settle_minutes, by=admin.username,
    )
    return await read_auto_settings(db, admin)


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
    return CustomerReportList(items=await _view(db, rows), total=total)


@router.get("/{report_id}", response_model=CustomerReportJob, summary="Report progress")
async def get_report(report_id: uuid.UUID, db: DBSession, _admin: AdminUser) -> CustomerReportJob:
    row = await db.get(CustomerReport, report_id)
    if row is None:
        raise _not_found()
    return (await _view(db, [row]))[0]


@router.post(
    "/{report_id}/regenerate",
    response_model=CustomerReportJob,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Build the same report again",
)
async def regenerate_report(report_id: uuid.UUID, db: DBSession, admin: AdminUser) -> CustomerReportJob:
    """Same period, preset, counting and options, built from today's data
    (e.g. after false alarms were dismissed). A new row pointing at the
    original, which is kept as it was."""
    original = await db.get(CustomerReport, report_id)
    if original is None:
        raise _not_found()
    now = datetime.now(timezone.utc)
    row = CustomerReport(
        format=original.format,
        preset=original.preset,
        mode=original.mode,
        period_start=original.period_start,
        period_end=original.period_end,
        period_label=original.period_label,
        options=dict(original.options or {}),
        shift_name=original.shift_name,
        trigger=TRIGGER_REGENERATE,
        regenerated_from=original.id,
        attempts=1,
        stage="Queued",
        total=4,
        created_by=admin.username,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    _start_build(row.id)
    logger.info("Customer report regenerated", report_id=str(row.id), original=str(original.id), by=admin.username)
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

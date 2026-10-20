"""Bulk violation-evidence export API (admin protected_router).

- POST /admin/violation-exports/preview   what an export would contain
- POST /admin/violation-exports           start building one
- GET  /admin/violation-exports           recent jobs, newest first
- GET  /admin/violation-exports/{id}      progress
- GET  /admin/violation-exports/{id}/download   the ZIP

Admin-gated on both creation *and* download, deliberately. The archive is
hundreds of megabytes of identifiable worker imagery in one file; the
download URL would otherwise be a shareable link to all of it. The
Violations page itself stays open, as it is today.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.core.admin_auth import AdminUser
from app.core.config import get_settings
from app.core.logging import get_logger
from app.deps import DBSession
from app.models import EXPORT_READY, ViolationExport
from app.models.violation import Violation
from app.schemas.violation_export import (
    ExportJob,
    ExportJobList,
    ExportPreview,
    ExportRequest,
)
from app.services.violation_export import ExportOptions
from app.services.violation_export_job import resolve_plan, run_job

logger = get_logger(__name__)

router = APIRouter(prefix="/violation-exports", tags=["Admin"])

#: Strong references to in-flight build tasks, so a build is not garbage
#: collected half-written.
_background: set = set()


def _statement(request: ExportRequest):
    """The filtered violation query, built by the Violations page's own helper.

    Imported here rather than reimplemented so an export cannot disagree
    with the list the operator was looking at.
    """
    from app.api.v1.violations import apply_violation_filters

    stmt = select(Violation)
    f = request.filters
    return apply_violation_filters(
        stmt,
        statuses=f.statuses,
        camera_id=f.camera_id,
        since=f.since,
        until=f.until,
        violation_type=f.violation_type,
        type_detail=f.type_detail,
        severities=f.severities,
        area=f.area,
    )


def _options(request: ExportRequest) -> ExportOptions:
    return ExportOptions(
        scope=request.scope,
        annotated=request.annotated,
        include_snapshots=request.include_snapshots,
        incident_ids=request.incident_ids,
        filters=request.filters.model_dump(mode="json", exclude_none=True),
    )


@router.post("/preview", response_model=ExportPreview, summary="Preview an export")
async def preview_export(
    request: ExportRequest, db: DBSession, _admin: AdminUser
) -> ExportPreview:
    """Counts and a size estimate, so the operator sees the shape first.

    This is also where "N of M have no inferred frame" comes from: the
    frame feature started partway through the site's history, so a wide date
    range can be mostly violations that only ever had a scene snapshot.
    """
    options = _options(request)
    try:
        plan = await resolve_plan(db, _statement(request), options)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stale_selection", "message": str(e)},
        ) from e

    cap = get_settings().violation_export_max_violations
    return ExportPreview(
        violations_matching_filters=plan.matched,
        violations_in_export=plan.total,
        without_inferred_frame=plan.no_frame,
        estimated_bytes=plan.estimate_bytes(
            annotated=options.annotated,
            include_snapshots=options.include_snapshots,
        ),
        max_violations=cap,
        within_cap=plan.total <= cap,
    )


@router.post(
    "",
    response_model=ExportJob,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start building an export",
)
async def create_export(
    request: ExportRequest, db: DBSession, admin: AdminUser
) -> ExportJob:
    options = _options(request)
    try:
        plan = await resolve_plan(db, _statement(request), options)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stale_selection", "message": str(e)},
        ) from e

    if plan.total == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "empty_export",
                "message": "no violations match those filters",
            },
        )

    cap = get_settings().violation_export_max_violations
    if plan.total > cap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "export_too_large",
                "message": (
                    f"{plan.total} violations exceeds the limit of {cap}; "
                    f"narrow the date range, camera or type"
                ),
                "violations": plan.total,
                "max_violations": cap,
            },
        )

    now = datetime.now(timezone.utc)
    row = ViolationExport(
        request=options.as_dict(),
        total=plan.total,
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

    task = asyncio.create_task(
        run_job(row.id, _statement(request), options, session_factory)
    )
    _background.add(task)
    task.add_done_callback(_background.discard)

    logger.info(
        "Violation export requested",
        export_id=str(row.id),
        violations=plan.total,
        no_frame=plan.no_frame,
        scope=options.scope,
        annotated=options.annotated,
        include_snapshots=options.include_snapshots,
        by=admin.username,
    )
    return ExportJob.model_validate(row)


@router.get("", response_model=ExportJobList, summary="Recent exports")
async def list_exports(
    db: DBSession,
    _admin: AdminUser,
    limit: int = Query(20, ge=1, le=100),
) -> ExportJobList:
    total = (
        await db.execute(select(func.count()).select_from(ViolationExport))
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(ViolationExport)
                .order_by(ViolationExport.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return ExportJobList(
        items=[ExportJob.model_validate(r) for r in rows], total=total
    )


@router.get("/{export_id}", response_model=ExportJob, summary="Export progress")
async def get_export(
    export_id: uuid.UUID, db: DBSession, _admin: AdminUser
) -> ExportJob:
    row = await db.get(ViolationExport, export_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "no such export"},
        )
    return ExportJob.model_validate(row)


@router.get("/{export_id}/download", summary="Download the archive")
async def download_export(
    export_id: uuid.UUID, db: DBSession, _admin: AdminUser
) -> FileResponse:
    row = await db.get(ViolationExport, export_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "no such export"},
        )
    if row.status != EXPORT_READY or not row.file_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "not_ready",
                "message": f"export is {row.status}",
                "status": row.status,
            },
        )

    path = Path(row.file_path)
    root = Path(get_settings().violation_export_dir).resolve()
    resolved = path.resolve()
    # The path comes from our own row, but it is still a filesystem path
    # reaching a download endpoint; keep it inside the export directory.
    if not resolved.is_relative_to(root) or not resolved.is_file():
        logger.warning(
            "Export file missing at download", export_id=str(export_id), path=str(path)
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "file_gone",
                "message": "the archive is no longer on disk",
            },
        )

    stamp = row.created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return FileResponse(
        resolved,
        media_type="application/zip",
        filename=f"violations_{stamp}_{export_id}.zip",
    )

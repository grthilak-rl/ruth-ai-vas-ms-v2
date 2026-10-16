"""Project lifecycle admin API (mounted on the admin protected_router).

- GET  /admin/projects                      list projects, newest first
- GET  /admin/projects/preflight            what starting a new one would do
- POST /admin/projects/start                archive the current, open the new
- GET  /admin/projects/{id}/violations      read-only archived-project viewer

Everything here requires a valid admin bearer token, the same as Model
Management. The destructive-looking one is POST /start — and it deletes
nothing: every row it removes from a live table is written to the matching
`*_archive` table in the same transaction, and a verified pg_dump is taken
before the transaction opens.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.admin_auth import AdminUser
from app.core.cache import DEVICES_LIST_CACHE_KEYS, cache_delete
from app.core.logging import get_logger
from app.deps import DBSession, StreamServiceDep, VASClientDep
from app.models import (
    PROJECT_STATE_ACTIVE,
    EvidenceArchive,
    Project,
    ViolationArchive,
)
from app.schemas import ErrorResponse
from app.schemas.project import (
    ArchivedViolation,
    ArchivedViolationListResponse,
    PreflightResponse,
    ProjectListResponse,
    ProjectSummary,
    StartProjectRequest,
    StartProjectResponse,
)
from app.services.project_service import (
    BackupFailedError,
    BackupUnavailableError,
    ConfirmationMismatchError,
    InferenceActiveError,
    ProjectError,
    ProjectNameInUseError,
    ProjectService,
    StopInferenceTimeoutError,
    TooMuchDataError,
    slugify,
)

router = APIRouter(prefix="/projects", tags=["Admin", "Projects"])
logger = get_logger(__name__)


def _conflict(error: str, message: str, details: dict | None = None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": error, "message": message, "details": details or {}},
    )


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
    description="Every project this site has run, newest first.",
)
async def list_projects(db: DBSession, _admin: AdminUser) -> ProjectListResponse:
    service = ProjectService(db)
    projects = await service.list_projects()
    items = [ProjectSummary.model_validate(p) for p in projects]
    active = next((i for i in items if i.state == PROJECT_STATE_ACTIVE), None)
    return ProjectListResponse(items=items, active=active)


@router.get(
    "/preflight",
    response_model=PreflightResponse,
    summary="What would starting a new project do",
    description=(
        "Measures the rows that would be archived and reports anything that "
        "blocks the action. Read-only; mutates nothing. Call this to render "
        "the confirmation screen."
    ),
)
async def preflight(
    db: DBSession,
    _admin: AdminUser,
    stop_inference: bool = Query(
        False,
        description=(
            "Preview the result assuming live inference will be stopped "
            "first; live cameras then stop counting as a blocker."
        ),
    ),
) -> PreflightResponse:
    service = ProjectService(db)
    result = await service.preflight(allow_stop_inference=stop_inference)
    return PreflightResponse(
        can_proceed=result.can_proceed,
        blockers=result.blockers,
        current_project=(
            ProjectSummary.model_validate(result.current_project)
            if result.current_project
            else None
        ),
        row_counts=result.row_counts,
        total_rows=result.total_rows,
        live_cameras=[c.as_dict() for c in result.live_cameras],
        backup_dir=result.backup_dir,
        evidence_with_vas_media=result.evidence_with_vas_media,
    )


@router.post(
    "/start",
    response_model=StartProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new project",
    description=(
        "Archives the active project's violations, events, evidence, stream "
        "sessions and bookmark analyses into the *_archive tables, then opens "
        "a new project. Nothing is deleted and no file on disk is touched. "
        "A verified pg_dump is taken first. Refuses while inference is live "
        "unless stop_inference=true."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Refused by preflight"},
        422: {"model": ErrorResponse, "description": "Confirmation mismatch"},
        503: {"model": ErrorResponse, "description": "Backup unavailable or failed"},
    },
)
async def start_project(
    request: StartProjectRequest,
    db: DBSession,
    admin: AdminUser,
    stream_service: StreamServiceDep,
    vas_client: VASClientDep,
) -> StartProjectResponse:
    """Archive the current project and open `request.name`.

    Ordering matters and is not an accident:

    1. Validate the typed confirmation before doing any work at all.
    2. Preflight (measure, check blockers).
    3. Stop inference if asked, and *wait*. This commits.
    4. pg_dump, outside the transaction, verified.
    5. One transaction: copy, verify, delete, close, open. Commit.
    6. Invalidate the devices cache so the UI does not serve a stale list.

    A failure anywhere in 1-4 has changed nothing except, possibly, having
    stopped inference (which the operator asked for) and written an orphan
    dump file (harmless, logged). A failure in 5 rolls back wholesale.
    """
    if request.confirm_name != request.name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "confirmation_mismatch",
                "message": "The confirmation text does not match the project name.",
            },
        )

    service = ProjectService(db, vas_client=vas_client)

    pre = await service.preflight(allow_stop_inference=request.stop_inference)

    if "backup_unavailable" in pre.blockers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "backup_unavailable",
                "message": (
                    "Cannot take the pre-archive backup, so the archive will "
                    "not start. Check that pg_dump is installed and "
                    f"{pre.backup_dir} exists and is writable."
                ),
            },
        )
    if "inference_active" in pre.blockers:
        raise _conflict(
            "inference_active",
            (
                f"Inference is live on {len(pre.live_cameras)} camera(s). "
                "Stop it first, or re-submit with stop_inference=true."
            ),
            {"cameras": [c.as_dict() for c in pre.live_cameras]},
        )
    if "too_much_data" in pre.blockers and not request.confirm_large:
        raise _conflict(
            "too_much_data",
            (
                f"{pre.total_rows:,} rows would be archived in one "
                "transaction. Re-submit with confirm_large=true, or run the "
                "CLI where it can be supervised."
            ),
            {"total_rows": pre.total_rows, "row_counts": pre.row_counts},
        )

    # The service re-checks this under its lock, which is what actually
    # enforces it. Checking here too means a name clash is reported before
    # inference is stopped and a dump is written, rather than after.
    slug = slugify(request.name)
    clash = await db.execute(select(Project.id).where(Project.slug == slug))
    if clash.scalars().first() is not None:
        raise _conflict(
            "project_name_in_use",
            f"A project with the slug {slug!r} already exists. Choose a name "
            "that is distinguishable after slugification.",
            {"slug": slug},
        )

    stopped: list[str] = []
    if request.stop_inference and pre.live_cameras:
        try:
            stopped = await service.stop_all_inference(stream_service)
        except StopInferenceTimeoutError as exc:
            raise _conflict("stop_inference_timeout", exc.message, exc.details) from exc

    try:
        backup_path = await service.run_backup(slug)
    except BackupUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "backup_unavailable", "message": exc.message},
        ) from exc
    except BackupFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "backup_failed", "message": exc.message},
        ) from exc

    try:
        result = await service.start_new_project(
            name=request.name,
            confirm_name=request.confirm_name,
            started_by=admin.username,
            backup_path=backup_path,
        )
        await db.commit()
    except ConfirmationMismatchError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "confirmation_mismatch", "message": exc.message},
        ) from exc
    except ProjectNameInUseError as exc:
        await db.rollback()
        raise _conflict("project_name_in_use", exc.message, exc.details) from exc
    except InferenceActiveError as exc:
        await db.rollback()
        raise _conflict("inference_active", exc.message, exc.details) from exc
    except TooMuchDataError as exc:
        await db.rollback()
        raise _conflict("too_much_data", exc.message, exc.details) from exc
    except ProjectError as exc:
        await db.rollback()
        logger.error(
            "Archive failed; database rolled back, nothing was moved",
            error=exc.message,
            details=exc.details,
            backup_path=str(backup_path),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "archive_failed",
                "message": (
                    f"{exc.message} The database was rolled back — nothing was "
                    f"archived or deleted. The backup at {backup_path} is "
                    "still valid."
                ),
                "details": exc.details,
            },
        ) from exc

    # The devices list is Redis-cached; the camera list itself is unchanged
    # but anything derived from session state is not, so drop it.
    await cache_delete(*DEVICES_LIST_CACHE_KEYS)

    archived_total = sum(result.counts.values())
    return StartProjectResponse(
        new_project=ProjectSummary.model_validate(result.new_project),
        archived_project=(
            ProjectSummary.model_validate(result.archived_project)
            if result.archived_project
            else None
        ),
        archive_batch_id=result.archive_batch_id,
        archived_counts=result.counts,
        backup_path=result.backup_path,
        stopped_cameras=stopped,
        vas_paths_resolved=result.vas_paths_resolved,
        vas_paths_missing=result.vas_paths_missing,
        message=(
            f"Archived {archived_total:,} rows from "
            f"{result.archived_project.name!r} and started {result.new_project.name!r}. "
            "Nothing was deleted; no file on disk was moved."
        ),
    )


@router.get(
    "/{project_id}/violations",
    response_model=ArchivedViolationListResponse,
    summary="Violations of an archived project",
    description=(
        "Read-only view of a closed project's violations, from "
        "violations_archive. snapshot_path/video_path are VAS's paths as they "
        "were when the project was archived — null means VAS had already "
        "removed the media by then."
    ),
    responses={404: {"model": ErrorResponse, "description": "No such project"}},
)
async def archived_violations(
    project_id: uuid.UUID,
    db: DBSession,
    _admin: AdminUser,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ArchivedViolationListResponse:
    service = ProjectService(db)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "project_not_found", "message": "No such project"},
        )

    total = (
        await db.execute(
            select(func.count())
            .select_from(ViolationArchive)
            .where(ViolationArchive.project_id == project_id)
        )
    ).scalar() or 0

    # One row per violation: evidence is 1:N in principle but at most one
    # snapshot and one bookmark in practice, so the two paths are folded in
    # with max() rather than returning duplicate violations.
    rows = (
        await db.execute(
            select(
                ViolationArchive,
                func.max(EvidenceArchive.vas_file_path).label("snapshot_path"),
                func.max(EvidenceArchive.vas_video_file_path).label("video_path"),
            )
            .outerjoin(
                EvidenceArchive, EvidenceArchive.violation_id == ViolationArchive.id
            )
            .where(ViolationArchive.project_id == project_id)
            .group_by(ViolationArchive.id)
            .order_by(ViolationArchive.timestamp.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return ArchivedViolationListResponse(
        project=ProjectSummary.model_validate(project),
        items=[
            ArchivedViolation(
                id=v.id,
                device_id=v.device_id,
                camera_name=v.camera_name,
                type=v.type,
                type_detail=v.type_detail,
                status=v.status,
                confidence=v.confidence,
                timestamp=v.timestamp,
                model_id=v.model_id,
                model_version=v.model_version,
                reviewed_by=v.reviewed_by,
                reviewed_at=v.reviewed_at,
                resolution_notes=v.resolution_notes,
                snapshot_path=snapshot_path,
                video_path=video_path,
            )
            for v, snapshot_path, video_path in rows
        ],
        total=int(total),
    )

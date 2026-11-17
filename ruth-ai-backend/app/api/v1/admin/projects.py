"""Project lifecycle admin API (mounted on the admin protected_router).

- GET  /admin/projects                      every project, newest first, with row counts
- GET  /admin/projects/start/preflight      what starting the next project would do
- POST /admin/projects/start                queue: open the next project with the chosen cameras
- GET  /admin/projects/lifecycle/preflight  Stop / Resume / End, per camera
- POST /admin/projects/lifecycle/{stop,resume,end}   queue that action
- GET  /admin/projects/cameras/preflight   adding/removing cameras of the current project
- POST /admin/projects/cameras              queue: add/remove cameras of the active project
- GET  /admin/projects/jobs/state           the running action and the latest one
- GET  /admin/projects/jobs/{id}            one action, with its stages
- POST /admin/projects/jobs/{id}/retry      run a failed/interrupted action again

Every action runs as a background job (app/services/project_jobs.py): the
POST validates cheaply and answers 202 with the job, the UI polls it. One
action at a time: a second POST answers 409 with the running job's id.

Projects are tags: nothing here archives, moves or deletes data. Ending a
project makes it past (viewable from Settings -> Project); starting the
next one requires the current one to be ended first. A verified pg_dump is
taken before a Start. Footage deletion is never un-paused here.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.core.admin_auth import AdminUser
from app.core.cache import DEVICES_LIST_CACHE_KEYS, cache_delete
from app.core.logging import get_logger
from app.deps import DBSession, StreamServiceDep, VASClientDep
from app.models import CURRENT_PROJECT_STATES
from app.schemas import ErrorResponse
from app.schemas.project import (
    ChangeCamerasPreflight,
    ChangeCamerasRequest,
    EndProjectRequest,
    LifecycleCamera,
    LifecyclePreflightResponse,
    ProjectJobResponse,
    ProjectJobsState,
    ProjectListResponse,
    ProjectSummary,
    StartPreflightResponse,
    StartProjectRequest,
)
from app.services.project_service import ProjectService, slugify

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
    description="Every project this site has run, newest first, with tagged row counts.",
)
async def list_projects(db: DBSession, _admin: AdminUser) -> ProjectListResponse:
    service = ProjectService(db)
    projects = await service.list_projects()
    counts = await service.project_counts()
    items = []
    for p in projects:
        item = ProjectSummary.model_validate(p)
        item.counts = counts.get(p.id, {})
        items.append(item)
    active = next((i for i in items if i.state in CURRENT_PROJECT_STATES), None)
    return ProjectListResponse(items=items, active=active)


_START_EFFECTS = [
    "A new project opens; from now on new detections, reports and exports are tagged with it.",
    "Ticked cameras are enabled in VAS; inference returns where the camera's intent has models.",
    "Unticked cameras are disabled in VAS (models per camera are kept).",
    "Footage deletion is left as it is (paused since End); only Settings -> System changes it.",
    "Nothing is archived or deleted: every past project stays viewable from Settings -> Project.",
]


@router.get(
    "/start/preflight",
    response_model=StartPreflightResponse,
    summary="What starting the next project would do",
)
async def start_preflight(
    db: DBSession,
    _admin: AdminUser,
    stream_service: StreamServiceDep,
    vas_client: VASClientDep,
    camera_ids: list[str] | None = Query(
        None, description="Plan for these VAS ids (nothing is picked by default)"
    ),
) -> StartPreflightResponse:
    from app.services.project_lifecycle import plan_as_dict

    lifecycle = _lifecycle_service(db, vas_client, stream_service)
    current, last, plans = await lifecycle.start_preflight(
        set(camera_ids) if camera_ids is not None else None
    )
    blockers, reason = [], None
    if current is not None:
        blockers.append("project_current")
        reason = f"{current.name!r} is {current.state}. End it first; its data stays viewable."
    service = ProjectService(db)
    backup_problem = service.backup_problem()
    if backup_problem:
        blockers.append("backup_unavailable")
        reason = reason or f"Cannot take the pre-start backup: {backup_problem}"
    return StartPreflightResponse(
        can_proceed=not blockers,
        blocked_reason=reason,
        blockers=blockers,
        current_project=ProjectSummary.model_validate(current) if current else None,
        last_project=ProjectSummary.model_validate(last) if last else None,
        cameras=[LifecycleCamera(**plan_as_dict(p)) for p in plans],
        backup_dir=service._settings.project_backup_dir,
        effects=_START_EFFECTS,
    )


_EFFECTS = {
    "stop": [
        "Footage deletion is paused in VAS (nothing is deleted while stopped).",
        "Automatic inference restarts (reconciler) do nothing while stopped.",
        "Starting inference is refused (409) until the project is resumed.",
        "Configuration is kept: cameras, models per camera and intents are untouched.",
        "Nothing is deleted: footage, evidence frames, violations and reports stay readable.",
    ],
    "end": [
        "Same as Stop, and the project cannot be resumed.",
        "Footage deletion stays paused.",
        "The project becomes past: open it any time from Settings -> Project to see its data.",
        "Then start the next project with the cameras it should run.",
        "Nothing is deleted or archived: footage, evidence frames, violations and reports stay readable.",
    ],
    "resume": [
        "Footage deletion stays as it is (paused): only Settings -> System lifts the pause.",
        "Only the cameras that were enabled when the project was stopped are re-enabled.",
        "Inference returns on its own (reconciler, about 90 s) where the intent is active.",
    ],
}


def _lifecycle_service(db, vas_client, stream_service):
    from app.services.project_lifecycle import ProjectLifecycleService

    return ProjectLifecycleService(db, vas_client, stream_service)


@router.get(
    "/lifecycle/preflight",
    response_model=LifecyclePreflightResponse,
    summary="What Stop / Resume / End would change, per camera",
)
async def lifecycle_preflight(
    db: DBSession,
    _admin: AdminUser,
    stream_service: StreamServiceDep,
    vas_client: VASClientDep,
    action: str = Query(..., pattern="^(stop|resume|end)$"),
) -> LifecyclePreflightResponse:
    from app.services.project_lifecycle import LifecycleError, check_allowed, plan_as_dict

    service = _lifecycle_service(db, vas_client, stream_service)
    project, plans = await service.preflight(action)
    blocked = None
    try:
        # The name check belongs to the submit, not the preview.
        check_allowed(action, project.state if project else None,
                      project_name=project.name if project else None,
                      confirm_name=project.name if project else None)
    except LifecycleError as e:
        blocked = e.message
    return LifecyclePreflightResponse(
        action=action,
        project=ProjectSummary.model_validate(project) if project else None,
        allowed=blocked is None,
        blocked_reason=blocked,
        cameras=[LifecycleCamera(**plan_as_dict(p)) for p in plans],
        effects=_EFFECTS[action],
    )


# ---------------------------------------------------------------------------
# Queueing actions (background jobs)
# ---------------------------------------------------------------------------

_JOB_RESPONSES = {
    409: {"model": ErrorResponse, "description": "Another project action is running, or not allowed now"},
    422: {"model": ErrorResponse, "description": "Confirmation mismatch, no cameras picked"},
    503: {"model": ErrorResponse, "description": "Backup unavailable"},
}


def _lifecycle_http_error(e) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if e.code in ("confirmation_mismatch", "bad_name", "no_cameras", "no_change", "bad_request")
            else status.HTTP_409_CONFLICT
        ),
        detail={"error": e.code, "message": e.message},
    )


async def job_view(db, job) -> ProjectJobResponse:
    from app.models import Project
    from app.models.project_job import JOB_RETRYABLE_STATES
    from app.services.project_jobs import latest_job, stage_list

    result = job.result or {}
    name = None
    if job.project_id is not None:
        project = await db.get(Project, job.project_id)
        name = project.name if project else None
    elif job.action == "start":
        name = (job.params or {}).get("name")
    else:
        from app.services.project_lifecycle import site_project

        current = await site_project(db)
        name = current.name if current else None
    latest = await latest_job(db)
    return ProjectJobResponse(
        id=job.id,
        action=job.action,
        state=job.state,
        stage=job.stage,
        stage_detail=job.stage_detail,
        stages=stage_list(job),
        error_code=job.error_code,
        error_message=job.error_message,
        errors=result.get("errors", []),
        cameras=[LifecycleCamera(**c) for c in result.get("cameras", [])],
        retention_paused=result.get("retention_paused"),
        project_id=job.project_id,
        project_name=name,
        backup_path=job.backup_path,
        attempts=job.attempts,
        can_retry=job.state in JOB_RETRYABLE_STATES and latest is not None and latest.id == job.id,
        created_by=job.created_by,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


async def _queue(db, action: str, params: dict, by: str) -> ProjectJobResponse:
    """Insert the job (one at a time) and start it after the response."""
    from app.core.database import get_session_factory
    from app.services.project_jobs import JobBusyError, create_job, launch

    factory = get_session_factory()
    if factory is None:  # pragma: no cover - startup ordering
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "not_ready", "message": "database not initialised"},
        )
    try:
        job = await create_job(db, action, params, by)
    except JobBusyError as exc:
        raise _busy(exc.active) from exc
    launch(job.id, factory)
    logger.warning("Project action queued", job_id=str(job.id), action=action, by=by)
    return await job_view(db, job)


def _busy(active) -> HTTPException:
    from app.services.project_lifecycle import LIFECYCLE_BUSY, LIFECYCLE_BUSY_MESSAGE

    return _conflict(
        LIFECYCLE_BUSY,
        LIFECYCLE_BUSY_MESSAGE,
        {"job_id": str(active.id), "action": active.action} if active else {},
    )


async def _refuse_if_busy(db, lifecycle) -> None:
    from app.services.project_jobs import active_job

    active = await active_job(db)
    if active is not None or await lifecycle.busy():
        raise _busy(active)


@router.post(
    "/start",
    response_model=ProjectJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start the next project (background job)",
    description=(
        "Validates, then queues the Start and returns the job at once. The job "
        "takes a verified pg_dump, creates the project and switches the chosen "
        "cameras in VAS. Requires the current project to be ended and at least "
        "one camera (or allow_no_cameras). Footage deletion is left as it is."
    ),
    responses=_JOB_RESPONSES,
)
async def start_project(
    request: StartProjectRequest,
    db: DBSession,
    admin: AdminUser,
    stream_service: StreamServiceDep,
    vas_client: VASClientDep,
) -> ProjectJobResponse:
    from sqlalchemy import select

    from app.models import Project
    from app.services.project_lifecycle import (
        LifecycleError,
        check_start,
        check_start_cameras,
        current_project,
    )

    name = request.name.strip()
    lifecycle = _lifecycle_service(db, vas_client, stream_service)
    await _refuse_if_busy(db, lifecycle)
    try:
        check_start(await current_project(db), name=name, confirm_name=request.confirm_name.strip())
        check_start_cameras(
            await lifecycle.cameras(), set(request.camera_ids),
            allow_no_cameras=request.allow_no_cameras,
        )
    except LifecycleError as e:
        raise _lifecycle_http_error(e) from e

    slug = slugify(name)
    if (await db.execute(select(Project.id).where(Project.slug == slug))).scalars().first():
        raise _conflict(
            "project_name_in_use",
            f"A project with the slug {slug!r} already exists. Choose another name.",
            {"slug": slug},
        )
    problem = ProjectService(db).backup_problem()
    if problem:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "backup_unavailable",
                    "message": f"Cannot take the pre-start backup: {problem}"},
        )
    return await _queue(db, "start", {
        "name": name,
        "confirm_name": request.confirm_name.strip(),
        "camera_ids": sorted(set(request.camera_ids)),
        "allow_no_cameras": request.allow_no_cameras,
    }, admin.username)


async def _queue_lifecycle(db, lifecycle, action: str, by: str, confirm_name: str | None = None):
    from app.services.project_lifecycle import (
        ACTION_END,
        ACTION_RESUME,
        ACTION_STOP,
        LifecycleError,
        check_allowed,
        site_project,
    )

    await _refuse_if_busy(db, lifecycle)
    project = await site_project(db)
    try:
        check_allowed(
            {"stop": ACTION_STOP, "end": ACTION_END, "resume": ACTION_RESUME}[action],
            project.state if project else None,
            project_name=project.name if project else None,
            confirm_name=confirm_name,
        )
    except LifecycleError as e:
        raise _lifecycle_http_error(e) from e
    params = {"confirm_name": confirm_name} if confirm_name is not None else {}
    return await _queue(db, action, params, by)


@router.post("/lifecycle/stop", response_model=ProjectJobResponse, status_code=status.HTTP_202_ACCEPTED,
             summary="Stop the project (background job)", responses=_JOB_RESPONSES)
async def stop_project(
    db: DBSession, admin: AdminUser, stream_service: StreamServiceDep, vas_client: VASClientDep
) -> ProjectJobResponse:
    lifecycle = _lifecycle_service(db, vas_client, stream_service)
    return await _queue_lifecycle(db, lifecycle, "stop", admin.username)


@router.post("/lifecycle/resume", response_model=ProjectJobResponse, status_code=status.HTTP_202_ACCEPTED,
             summary="Resume the project (background job)", responses=_JOB_RESPONSES)
async def resume_project(
    db: DBSession, admin: AdminUser, stream_service: StreamServiceDep, vas_client: VASClientDep
) -> ProjectJobResponse:
    lifecycle = _lifecycle_service(db, vas_client, stream_service)
    return await _queue_lifecycle(db, lifecycle, "resume", admin.username)


@router.post("/lifecycle/end", response_model=ProjectJobResponse, status_code=status.HTTP_202_ACCEPTED,
             summary="End the project (background job)", responses=_JOB_RESPONSES)
async def end_project(
    request: EndProjectRequest,
    db: DBSession,
    admin: AdminUser,
    stream_service: StreamServiceDep,
    vas_client: VASClientDep,
) -> ProjectJobResponse:
    lifecycle = _lifecycle_service(db, vas_client, stream_service)
    return await _queue_lifecycle(db, lifecycle, "end", admin.username, request.confirm_name)


@router.get("/jobs/state", response_model=ProjectJobsState, summary="Running and latest project action")
async def jobs_state(db: DBSession, _admin: AdminUser) -> ProjectJobsState:
    from app.services.project_jobs import active_job, latest_job

    active = await active_job(db)
    latest = await latest_job(db)
    return ProjectJobsState(
        active=await job_view(db, active) if active else None,
        latest=await job_view(db, latest) if latest else None,
    )


@router.get("/jobs/{job_id}", response_model=ProjectJobResponse, summary="One project action")
async def get_job(job_id: uuid.UUID, db: DBSession, _admin: AdminUser) -> ProjectJobResponse:
    from app.models.project_job import ProjectJob

    job = await db.get(ProjectJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "job_not_found", "message": "No such project action."})
    return await job_view(db, job)


@router.post("/jobs/{job_id}/retry", response_model=ProjectJobResponse,
             status_code=status.HTTP_202_ACCEPTED, summary="Retry a failed or interrupted action",
             responses=_JOB_RESPONSES)
async def retry_job(job_id: uuid.UUID, db: DBSession, admin: AdminUser) -> ProjectJobResponse:
    from app.core.database import get_session_factory
    from app.services.project_jobs import JobBusyError, JobNotRetryableError, launch
    from app.services.project_jobs import retry_job as _retry

    try:
        job = await _retry(db, job_id, admin.username)
    except JobBusyError as exc:
        raise _busy(exc.active) from exc
    except JobNotRetryableError as exc:
        raise _conflict("not_retryable", exc.message) from exc
    launch(job.id, get_session_factory())
    return await job_view(db, job)


# ---------------------------------------------------------------------------
# Cameras in this project (add / remove mid-project)
# ---------------------------------------------------------------------------

_CAMERAS_EFFECTS = [
    "Added cameras are enabled in VAS and join the project from now; inference starts where the camera has models.",
    "Removed cameras are disabled in VAS and leave the project from now. Their violations and "
    "history stay in the project, and analytics count them for the time they were in.",
    "Inference intents are kept: a removed camera's inference resumes if it is added back.",
    "VAS placements (location history) are never changed by this.",
]


async def _members_view(db, members: dict) -> list:
    from sqlalchemy import select

    from app.models import Device
    from app.schemas.project import ProjectMember

    if not members:
        return []
    devices = {
        str(d.id): d
        for d in (await db.execute(select(Device).where(Device.id.in_(
            [uuid.UUID(k) for k in members])))).scalars().all()
    }
    out = []
    for key, row in members.items():
        d = devices.get(key)
        out.append(ProjectMember(
            device_id=row.device_id,
            vas_device_id=d.vas_device_id if d else None,
            name=(d.display_name or d.name) if d else key,
            joined_at=row.joined_at,
            inferred=row.inferred,
            source=row.source,
        ))
    return sorted(out, key=lambda m: m.name)


@router.get(
    "/cameras/preflight",
    response_model=ChangeCamerasPreflight,
    summary="What adding/removing cameras of the current project would do",
)
async def cameras_preflight(
    db: DBSession,
    _admin: AdminUser,
    stream_service: StreamServiceDep,
    vas_client: VASClientDep,
    add: list[str] = Query(default_factory=list),
    remove: list[str] = Query(default_factory=list),
) -> ChangeCamerasPreflight:
    from app.services.project_lifecycle import LifecycleError, check_change_cameras, plan_as_dict

    lifecycle = _lifecycle_service(db, vas_client, stream_service)
    project, members, plans = await lifecycle.change_cameras_preflight(set(add), set(remove))
    blocked = None
    try:
        if add or remove:
            check_change_cameras(project, await lifecycle.cameras(), set(members), set(add), set(remove))
        elif project is None or project.state != "active":
            check_change_cameras(project, [], set(), {"-"}, set())
    except LifecycleError as e:
        blocked = e.message
    return ChangeCamerasPreflight(
        project=ProjectSummary.model_validate(project) if project else None,
        allowed=blocked is None,
        blocked_reason=blocked,
        members=await _members_view(db, members),
        cameras=[LifecycleCamera(**plan_as_dict(p)) for p in plans],
        effects=_CAMERAS_EFFECTS,
    )


@router.post(
    "/cameras",
    response_model=ProjectJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add/remove cameras of the active project (background job)",
    responses=_JOB_RESPONSES,
)
async def change_cameras(
    request: ChangeCamerasRequest,
    db: DBSession,
    admin: AdminUser,
    stream_service: StreamServiceDep,
    vas_client: VASClientDep,
) -> ProjectJobResponse:
    from app.services.project_lifecycle import (
        LifecycleError,
        check_change_cameras,
        current_project,
        open_members,
    )

    lifecycle = _lifecycle_service(db, vas_client, stream_service)
    await _refuse_if_busy(db, lifecycle)
    project = await current_project(db)
    members = await open_members(db, project.id) if project else {}
    add, remove = set(request.add), set(request.remove)
    try:
        check_change_cameras(project, await lifecycle.cameras(), set(members), add, remove)
    except LifecycleError as e:
        raise _lifecycle_http_error(e) from e
    return await _queue(db, "cameras", {"add": sorted(add), "remove": sorted(remove)}, admin.username)

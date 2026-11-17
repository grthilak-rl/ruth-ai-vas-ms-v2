"""Project lifecycle actions (Start, Stop, End, Resume) as background jobs.

The request validates cheaply, writes a ``project_jobs`` row and returns its
id (202). This module runs the job in the backend:

- **One at a time.** A partial unique index allows one queued/running job;
  a second request gets 409 with the running job's id. The runner also holds
  the lifecycle lock (its own connection) for the whole job.
- **Stages.** Each stage is written to the row as it starts, with a short
  detail ("DEMO-CAMERA2 (2/3)"), on a session of its own so the UI sees it
  at once. The lifecycle work runs on another session.
- **Restart-safe.** On startup a job still queued/running was cut short:
  it becomes ``interrupted`` (never resumed by itself). Retry continues from
  what is recorded: Start reuses a verified backup (``backup_path``), never
  creates the project twice (``project_id`` is written in the same commit
  that creates it), and re-plans camera switching against VAS as it is now.
  Stop, End and Resume are idempotent from their in-between states
  (stopping/resuming), so Retry simply runs them again.
- **Failure.** A camera VAS would not switch fails the job with that camera
  named; the project keeps ``lifecycle_error`` as before. Retry finishes it.
- **Refresh.** Every action ends by re-syncing Ruth's device rows from VAS
  (Ruth lists only cameras its copy says are enabled). If only that fails,
  the job fails with ``refresh_failed`` and Retry redoes it.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.project import Project
from app.models.project_job import (
    JOB_ACTIVE_STATES,
    JOB_FAILED,
    JOB_INTERRUPTED,
    JOB_QUEUED,
    JOB_RETRYABLE_STATES,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    ProjectJob,
)

logger = get_logger(__name__)

#: (key, label) per action, in order.
REFRESH = ("refresh", "Refresh Ruth's camera list")

STAGES: dict[str, list[tuple[str, str]]] = {
    "start": [
        ("backup", "Back up the database"),
        ("project", "Create the project"),
        ("cameras", "Switch cameras in VAS"),
        REFRESH,
    ],
    "stop": [
        ("idle", "Stop new work"),
        ("sessions", "End inference sessions"),
        ("cameras", "Disable cameras in VAS"),
        ("retention", "Pause footage deletion"),
        ("finish", "Mark the project stopped"),
        REFRESH,
    ],
    "end": [
        ("idle", "Stop new work"),
        ("sessions", "End inference sessions"),
        ("cameras", "Disable cameras in VAS"),
        ("retention", "Pause footage deletion"),
        ("finish", "Mark the project ended"),
        REFRESH,
    ],
    "resume": [
        ("resuming", "Mark the project resuming"),
        ("cameras", "Re-enable cameras in VAS"),
        ("finish", "Mark the project active"),
        REFRESH,
    ],
    "cameras": [
        ("cameras", "Add and remove cameras"),
        REFRESH,
    ],
}

def stage_label(action: str, stage: str | None) -> str:
    return dict(STAGES.get(action, [])).get(stage or "", stage or "start")


def stage_list(job: ProjectJob) -> list[dict[str, str]]:
    """Every stage of the job's action with pending/running/done/failed/interrupted."""
    keys = [k for k, _ in STAGES[job.action]]
    at = keys.index(job.stage) if job.stage in keys else -1
    out = []
    for i, (key, label) in enumerate(STAGES[job.action]):
        if job.state == JOB_SUCCEEDED:
            status = "done"
        elif job.state == JOB_QUEUED or at < 0 or i > at:
            status = "pending"
        elif i < at:
            status = "done"
        else:
            status = {JOB_RUNNING: "running", JOB_FAILED: "failed", JOB_INTERRUPTED: "interrupted"}[job.state]
        out.append({"key": key, "label": label, "status": status})
    return out


class JobBusyError(Exception):
    """Another lifecycle job is queued or running."""

    def __init__(self, active: ProjectJob | None) -> None:
        super().__init__("Another project action is running.")
        self.active = active


class JobNotRetryableError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


async def active_job(db: AsyncSession) -> ProjectJob | None:
    return (
        await db.execute(
            select(ProjectJob).where(ProjectJob.state.in_(JOB_ACTIVE_STATES)).limit(1)
        )
    ).scalars().first()


async def latest_job(db: AsyncSession) -> ProjectJob | None:
    return (
        await db.execute(select(ProjectJob).order_by(ProjectJob.created_at.desc()).limit(1))
    ).scalars().first()


async def create_job(db: AsyncSession, action: str, params: dict[str, Any], by: str) -> ProjectJob:
    """Queue a job, or raise JobBusyError if one is queued or running."""
    job = ProjectJob(id=uuid.uuid4(), action=action, state=JOB_QUEUED, params=params, created_by=by)
    db.add(job)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_project_jobs_one_active" not in str(exc.orig):
            raise
        raise JobBusyError(await active_job(db)) from exc
    await db.refresh(job)
    return job


async def retry_job(db: AsyncSession, job_id: uuid.UUID, by: str) -> ProjectJob:
    """Queue a failed/interrupted job again. Only the latest job can be retried."""
    job = await db.get(ProjectJob, job_id)
    if job is None:
        raise JobNotRetryableError("No such project action.")
    latest = await latest_job(db)
    if latest is None or latest.id != job.id:
        raise JobNotRetryableError("Only the most recent project action can be retried.")
    if job.state not in JOB_RETRYABLE_STATES:
        raise JobNotRetryableError(f"This action is {job.state}; only a failed or interrupted one can be retried.")
    job.state = JOB_QUEUED
    job.attempts += 1
    job.error_code = job.error_message = None
    job.finished_at = None
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise JobBusyError(await active_job(db)) from exc
    await db.refresh(job)
    logger.warning("Project action retried", job_id=str(job.id), action=job.action,
                   attempt=job.attempts, from_stage=job.stage, by=by)
    return job


async def _set(session_factory, job_id: uuid.UUID, **values) -> None:
    """Write to the job row on a session of its own (visible at once)."""
    async with session_factory() as s:
        await s.execute(update(ProjectJob).where(ProjectJob.id == job_id).values(**values))
        await s.commit()


async def recover_interrupted(session_factory) -> int:
    """At startup: a job still queued/running was cut short by the restart."""
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        rows = (
            await s.execute(select(ProjectJob).where(ProjectJob.state.in_(JOB_ACTIVE_STATES)))
        ).scalars().all()
        for job in rows:
            job.state = JOB_INTERRUPTED
            job.error_code = "interrupted"
            job.error_message = (
                f"The backend restarted during \"{stage_label(job.action, job.stage)}\". "
                "Retry continues from there."
            )
            job.finished_at = now
            logger.warning("Project action interrupted by a restart", job_id=str(job.id),
                           action=job.action, stage=job.stage)
        await s.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

_background: set[asyncio.Task] = set()


def launch(job_id: uuid.UUID, session_factory, **deps) -> asyncio.Task:
    task = asyncio.create_task(run_job(job_id, session_factory, **deps), name=f"project-job-{job_id}")
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


def _result_dict(result) -> dict[str, Any]:
    from app.services.project_lifecycle import plan_as_dict

    return {
        "cameras": [plan_as_dict(p) for p in result.cameras],
        "errors": list(result.errors),
        "retention_paused": result.retention_paused,
    }


async def run_job(job_id: uuid.UUID, session_factory, *, vas_client=None, stream_service_factory=None) -> None:
    """Run one queued job to succeeded/failed. Never raises (except cancellation)."""
    from app.services.exceptions import ServiceError
    from app.services.project_lifecycle import LifecycleError, ProjectLifecycleService
    from app.services.project_service import (
        BackupFailedError,
        BackupUnavailableError,
        ProjectNameInUseError,
    )

    async with session_factory() as s:
        job = await s.get(ProjectJob, job_id)
        if job is None or job.state != JOB_QUEUED:
            return
        action, params, by = job.action, dict(job.params or {}), job.created_by
        backup_path, project_id = job.backup_path, job.project_id
        job.state = JOB_RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.stage, job.stage_detail = STAGES[action][0][0], None
        await s.commit()

    async def progress(stage: str, detail: str | None = None) -> None:
        await _set(session_factory, job_id, stage=stage, stage_detail=detail)

    if vas_client is None:
        from app.deps.services import get_vas_client

        vas_client = get_vas_client()

    logger.warning("Project action started", job_id=str(job_id), action=action, by=by)
    try:
        async with session_factory() as db:
            if stream_service_factory is None:
                from app.services.stream_service import StreamService

                streams = StreamService(vas_client, db)
            else:
                streams = stream_service_factory(db)
            svc = ProjectLifecycleService(db, vas_client, streams)
            svc.progress = progress
            async with svc.lock.held():
                if action == "start":
                    result = await _run_start(svc, db, session_factory, job_id, params, by,
                                              backup_path=backup_path, project_id=project_id,
                                              progress=progress)
                elif action in ("stop", "end"):
                    result = await svc._stop(by, end=action == "end", confirm_name=params.get("confirm_name"))
                elif action == "cameras":
                    result = await svc._change_cameras(
                        by, add=list(params.get("add") or []), remove=list(params.get("remove") or [])
                    )
                else:
                    result = await svc._resume(by)
                pid = result.project.id
                error_stage = svc.error_stage
                # Ruth keeps its own copy of each camera (enabled flag included)
                # and lists only enabled ones: refresh it now, or cameras just
                # switched stay hidden/visible in Ruth until the next restart.
                await progress("refresh", None)
                refresh_error = await _refresh_devices(db, vas_client)
    except asyncio.CancelledError:
        # Shutdown mid-job: say so now; startup recovery would say it too.
        await asyncio.shield(_set(
            session_factory, job_id, state=JOB_INTERRUPTED, error_code="interrupted",
            error_message="The backend stopped during this action. Retry continues from there.",
            finished_at=datetime.now(timezone.utc),
        ))
        raise
    except (LifecycleError, ServiceError, ProjectNameInUseError,
            BackupUnavailableError, BackupFailedError) as exc:
        code = getattr(exc, "code", None) or {
            ProjectNameInUseError: "project_name_in_use",
            BackupUnavailableError: "backup_unavailable",
            BackupFailedError: "backup_failed",
        }.get(type(exc), "refused")
        await _fail(session_factory, job_id, code, getattr(exc, "message", str(exc)))
        return
    except Exception as exc:  # noqa: BLE001 - the job row is the only place this can surface
        logger.exception("Project action crashed", job_id=str(job_id), action=action)
        await _fail(session_factory, job_id, "unexpected", f"{type(exc).__name__}: {exc}")
        return

    values: dict[str, Any] = {"result": _result_dict(result), "project_id": pid,
                              "finished_at": datetime.now(timezone.utc)}
    if refresh_error and not result.errors:
        values.update(state=JOB_FAILED, error_code="refresh_failed", stage="refresh",
                      error_message=f"Cameras were switched, but Ruth's camera list was not refreshed "
                                    f"({refresh_error}). Retry refreshes it.")
        logger.warning("Project action: device refresh failed", job_id=str(job_id), error=refresh_error)
    elif result.errors:
        # Point at the stage that failed, not at the refresh that ran after it.
        values.update(state=JOB_FAILED, error_code="incomplete", stage=error_stage or "cameras",
                      stage_detail=None, error_message="; ".join(result.errors)[:4000])
        logger.warning("Project action incomplete", job_id=str(job_id), action=action, errors=result.errors)
    else:
        values.update(state=JOB_SUCCEEDED, stage_detail=None, error_code=None, error_message=None)
        logger.warning("Project action finished", job_id=str(job_id), action=action)
    await _set(session_factory, job_id, **values)
    try:
        from app.core.cache import DEVICES_LIST_CACHE_KEYS, cache_delete

        await cache_delete(*DEVICES_LIST_CACHE_KEYS)  # camera enabled flags changed
    except Exception:  # noqa: BLE001 - a stale cache entry expires on its own
        logger.debug("Device list cache not cleared after project action")


async def _refresh_devices(db, vas_client) -> str | None:
    """Re-sync Ruth's device rows from VAS. Returns an error text, or None."""
    from app.services.device_service import DeviceService

    try:
        await DeviceService(vas_client, db).sync_devices_from_vas()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - reported on the job
        await db.rollback()
        return f"{type(exc).__name__}: {exc}"
    return None


async def _fail(session_factory, job_id: uuid.UUID, code: str, message: str) -> None:
    logger.warning("Project action failed", job_id=str(job_id), error=code, message=message)
    await _set(session_factory, job_id, state=JOB_FAILED, error_code=code, error_message=message[:4000],
               finished_at=datetime.now(timezone.utc))


async def _run_start(svc, db, session_factory, job_id, params, by, *, backup_path, project_id, progress):
    from app.services.project_service import ProjectService, slugify

    service = ProjectService(db)
    if backup_path and await service.verify_existing(backup_path):
        await progress("backup", f"reusing {backup_path.rsplit('/', 1)[-1]}")
    else:
        await progress("backup", "pg_dump of the whole database")
        backup_path = str(await service.run_backup(slugify(params["name"].strip())))
        await _set(session_factory, job_id, backup_path=backup_path)

    chosen = set(params.get("camera_ids") or [])
    if project_id is not None:
        project = await db.get(Project, project_id)
        await progress("project", f"{project.name} already created")
    else:
        await progress("project", params["name"].strip())
        project, chosen = await svc._start_create(
            by, name=params["name"], confirm_name=params["confirm_name"],
            camera_ids=list(chosen), backup_path=backup_path,
            allow_no_cameras=bool(params.get("allow_no_cameras")), job_id=job_id,
        )
    await progress("cameras", None)
    return await svc._start_cameras(project, chosen, by=by)

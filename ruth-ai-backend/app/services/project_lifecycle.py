"""Stop, Resume and End the current project.

Stop turns the site off without losing anything:

1. The project moves to ``stopping`` first, so everything that could start a
   camera again goes idle before anything is touched: the reconciler skips
   whole cycles and ``StreamService.start_stream`` refuses (409).
2. A snapshot records, per camera, VAS's ``enabled`` flag as it is now.
   Resume restores exactly this: a camera that was off before Stop stays off.
3. Ruth's inference sessions end. Intents are NOT touched (no set_off): the
   models per camera and the operator's on/off choice survive.
4. Every enabled camera is disabled in VAS (PATCH enabled=false). That stops
   live view, recording and AI frames in one step, and VAS refuses every
   start path while disabled, including its own restarts after a reboot.
5. VAS footage deletion is paused (``retention_paused``).
6. The project becomes ``stopped`` (or ``ended``).

Footage deletion is never *unpaused* by a lifecycle action — not by Resume,
not by Start. Stop and End may pause it; lifting the pause is an operator
decision, made in Settings -> System (PUT /admin/footage-retention).

Every step is idempotent, so a Stop that failed half-way (a camera VAS would
not disable) leaves the project in ``stopping`` with the error recorded, and
running Stop again finishes it. Resume is the mirror: ``resuming``, re-enable
the snapshot's cameras, ``active``; the reconciler then restores inference
from the untouched intents.

End is Stop that cannot be resumed, and makes the project past: it stays
viewable from Settings -> Project with all of its data. Start then opens the
next project with the cameras the operator picked (``plan_start``): picked
cameras are enabled in VAS, the rest disabled, and the reconciler restores
or suspends inference from the intents exactly as for Resume and Stop.
Nothing is deleted or archived by any of these.

The per-camera plan (what will change) is computed by pure functions shared
by the preflight screen and the executor, so what the admin confirms is what
runs.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Device, StreamSession, StreamState
from app.models.inference_intent import DeviceInferenceIntent
from app.models.project import (
    CURRENT_PROJECT_STATES,
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_ENDED,
    PROJECT_STATE_RESUMING,
    PROJECT_STATE_STOPPED,
    PROJECT_STATE_STOPPING,
    Project,
)
from app.services.exceptions import ServiceError

logger = get_logger(__name__)

#: Advisory lock for Stop/Resume/End/Start; two at once must not interleave.
LIFECYCLE_LOCK_KEY = 0x52555448_4C494645  # "RUTH" "LIFE"

LIFECYCLE_BUSY = "lifecycle_busy"
LIFECYCLE_BUSY_MESSAGE = (
    "Another project action is running. Wait for it to finish, then try again."
)

ACTION_STOP = "stop"
ACTION_END = "end"
ACTION_RESUME = "resume"
ACTION_START = "start"
ACTION_CAMERAS = "cameras"


class ProjectNotRunningError(ServiceError):
    """Something tried to start a camera while the project is not active."""

    def __init__(self, state: str) -> None:
        super().__init__(
            f"The project is {state}: cameras and inference stay off until it is resumed.",
            details={"project_state": state},
        )
        self.state = state


class LifecycleError(ServiceError):
    """Stop/Resume/End refused; ``code`` says why (API maps it to 409/422)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, details={"error": code})
        self.code = code


# ---------------------------------------------------------------------------
# Site state, for the guards
# ---------------------------------------------------------------------------


async def current_project(db: AsyncSession) -> Project | None:
    """The project in a current state (active/stopping/stopped/resuming), if any.

    None between End and the next Start. Use site_project when "the last
    project" is the right answer then.
    """
    return (
        await db.execute(
            select(Project)
            .where(Project.state.in_(CURRENT_PROJECT_STATES))
            .order_by(Project.started_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def site_project(db: AsyncSession) -> Project | None:
    """The current project, or the last one when none is current."""
    from app.core.project_scope import site_project as _site_project

    return await _site_project(db)


async def site_state(db: AsyncSession) -> str | None:
    """The site's project state, or None when there is no project yet.

    Between End and the next Start this is ``ended``: the site stays idle
    until a project is started.
    """
    project = await site_project(db)
    return project.state if project else None


def is_running(state: str | None) -> bool:
    """Cameras may run only while the project is active (or none exists)."""
    return state in (None, PROJECT_STATE_ACTIVE)


async def ensure_running(db: AsyncSession) -> None:
    state = await site_state(db)
    if not is_running(state):
        raise ProjectNotRunningError(state)


# ---------------------------------------------------------------------------
# Plan (pure)
# ---------------------------------------------------------------------------


@dataclass
class CameraState:
    """One camera as Ruth and VAS see it now."""

    vas_device_id: str
    name: str
    vas_enabled: bool
    video_state: str | None = None
    device_id: str | None = None  # Ruth's, when Ruth knows the camera
    intent: str | None = None  # active / suspended / off
    intent_models: int = 0
    live_session: bool = False


@dataclass
class CameraPlan:
    name: str
    vas_device_id: str
    device_id: str | None
    vas_enabled_now: bool
    intent: str | None
    intent_models: int
    live_session: bool
    actions: list[str] = field(default_factory=list)
    #: Will this action change the camera in VAS?
    vas_change: bool = False


def _intent_text(cam: CameraState) -> str:
    if cam.intent is None:
        return "No inference configured"
    models = f"{cam.intent_models} model{'s' * (cam.intent_models != 1)}"
    return f"Inference intent kept as is ({cam.intent}, {models})"


def plan_stop(cameras: list[CameraState]) -> list[CameraPlan]:
    plans = []
    for cam in cameras:
        actions = []
        if cam.live_session:
            actions.append("End the inference session")
        if cam.vas_enabled:
            actions.append("Disable in VAS: live view, recording and AI frames stop")
        else:
            actions.append("Already disabled in VAS; stays disabled on Resume")
        actions.append(_intent_text(cam))
        plans.append(CameraPlan(
            name=cam.name, vas_device_id=cam.vas_device_id, device_id=cam.device_id,
            vas_enabled_now=cam.vas_enabled, intent=cam.intent, intent_models=cam.intent_models,
            live_session=cam.live_session, actions=actions, vas_change=cam.vas_enabled,
        ))
    return plans


def plan_resume(cameras: list[CameraState], snapshot: dict[str, Any] | None) -> list[CameraPlan]:
    """Re-enable exactly the cameras the Stop snapshot says were enabled."""
    was_enabled = {
        c["vas_device_id"]: bool(c.get("vas_enabled"))
        for c in (snapshot or {}).get("cameras", [])
    }
    plans = []
    for cam in cameras:
        enable = was_enabled.get(cam.vas_device_id, False)
        actions = []
        if enable:
            actions.append("Re-enable in VAS: live view and recording start")
            if cam.intent in ("active", "suspended") and cam.intent_models:
                actions.append("Inference resumes within about 90 s (intent kept)")
            else:
                actions.append("No inference (intent is off or not configured)")
        elif cam.vas_device_id in was_enabled:
            actions.append("Stays disabled: it was disabled before Stop")
        else:
            actions.append("Stays disabled: added after Stop")
        plans.append(CameraPlan(
            name=cam.name, vas_device_id=cam.vas_device_id, device_id=cam.device_id,
            vas_enabled_now=cam.vas_enabled, intent=cam.intent, intent_models=cam.intent_models,
            live_session=cam.live_session, actions=actions, vas_change=enable and not cam.vas_enabled,
        ))
    return plans


def snapshot_of(cameras: list[CameraState], now: datetime, by: str) -> dict[str, Any]:
    return {
        "captured_at": now.isoformat(),
        "captured_by": by,
        "cameras": [
            {"vas_device_id": c.vas_device_id, "name": c.name, "vas_enabled": c.vas_enabled,
             "video_state": c.video_state, "device_id": c.device_id}
            for c in cameras
        ],
    }


def plan_start(cameras: list[CameraState], chosen: set[str]) -> list[CameraPlan]:
    """What starting a project with the cameras `chosen` (VAS ids) changes."""
    plans = []
    for cam in cameras:
        pick = cam.vas_device_id in chosen
        actions = []
        if pick and not cam.vas_enabled:
            actions.append("Enable in VAS: live view and recording start")
        elif pick:
            actions.append("Already enabled in VAS")
        elif cam.vas_enabled:
            actions.append("Disable in VAS: not part of the new project")
        else:
            actions.append("Stays disabled")
        if pick:
            if cam.intent in ("active", "suspended") and cam.intent_models:
                actions.append("Inference starts within about 90 s (intent kept)")
            else:
                actions.append("No inference until models are chosen on the camera")
        plans.append(CameraPlan(
            name=cam.name, vas_device_id=cam.vas_device_id, device_id=cam.device_id,
            vas_enabled_now=cam.vas_enabled, intent=cam.intent, intent_models=cam.intent_models,
            live_session=cam.live_session, actions=actions, vas_change=pick != cam.vas_enabled,
        ))
    return plans


def check_start(current: Project | None, *, name: str, confirm_name: str) -> None:
    """Start is allowed only when no project is current (the last one ended)."""
    if current is not None:
        raise LifecycleError(
            "project_current",
            f"{current.name!r} is still {current.state}. End it first; "
            "its data stays viewable from Settings -> Project.",
        )
    if not name.strip():
        raise LifecycleError("bad_name", "Give the new project a name.")
    if confirm_name != name:
        raise LifecycleError("confirmation_mismatch", "Type the project name exactly to start it.")


def check_start_cameras(
    cameras: list[CameraState], chosen: set[str], *, allow_no_cameras: bool = False
) -> None:
    """The picked cameras exist in VAS and in Ruth; none picked only on purpose.

    After End every camera is disabled, so "start with whatever is enabled"
    always meant "start with nothing": the 17 Nov Start of Post HPCL Dev ran
    with no cameras because nothing was ticked. Zero cameras now has to be
    asked for explicitly.
    """
    if not chosen and not allow_no_cameras:
        raise LifecycleError(
            "no_cameras",
            "Pick the cameras the new project runs, or confirm starting with no cameras.",
        )
    known = {c.vas_device_id: c for c in cameras}
    unknown = sorted(chosen - set(known))
    if unknown:
        raise LifecycleError("unknown_camera", f"VAS does not know camera(s) {', '.join(unknown)}.")
    not_in_ruth = sorted(known[c].name for c in chosen if not known[c].device_id)
    if not_in_ruth:
        raise LifecycleError(
            "camera_not_synced",
            f"Ruth has not synced {', '.join(not_in_ruth)} yet; open Cameras once and retry.",
        )


def plan_change(
    cameras: list[CameraState], members: set[str], add: set[str], remove: set[str]
) -> list[CameraPlan]:
    """What "Change cameras" does to each camera. `members`: Ruth device ids."""
    plans = []
    for cam in cameras:
        member = cam.device_id is not None and cam.device_id in members
        actions: list[str] = []
        change = False
        if cam.vas_device_id in add and not member:
            actions.append("Joins the project from now")
            if cam.vas_enabled:
                actions.append("Already enabled in VAS")
            else:
                actions.append("Enable in VAS: live view and recording start")
                change = True
            if cam.intent in ("active", "suspended") and cam.intent_models:
                actions.append("Inference starts within about 90 s (intent kept)")
            else:
                actions.append("No inference until models are chosen on the camera")
        elif cam.vas_device_id in remove and member:
            actions.append("Leaves the project from now; its data and history stay in the project")
            if cam.vas_enabled:
                actions.append("Disable in VAS: live view, recording and AI frames stop")
                change = True
            else:
                actions.append("Already disabled in VAS")
            if cam.intent:
                actions.append("Inference intent kept: it resumes if the camera is added back")
            actions.append("Its VAS placement (location history) is not touched")
        elif member:
            actions.append("Stays in the project")
        else:
            actions.append("Not in the project")
            if cam.vas_enabled:
                actions.append("Enabled in VAS but not a member of this project")
        plans.append(CameraPlan(
            name=cam.name, vas_device_id=cam.vas_device_id, device_id=cam.device_id,
            vas_enabled_now=cam.vas_enabled, intent=cam.intent, intent_models=cam.intent_models,
            live_session=cam.live_session, actions=actions, vas_change=change,
        ))
    return plans


def check_change_cameras(
    project: Project | None, cameras: list[CameraState], members: set[str],
    add: set[str], remove: set[str],
) -> None:
    """Up-front checks for "Change cameras" (the job itself is idempotent)."""
    if project is None:
        raise LifecycleError("no_project", "There is no current project.")
    if project.state != PROJECT_STATE_ACTIVE:
        raise LifecycleError(
            "bad_state",
            f"{project.name} is {project.state}: cameras can be changed only while the "
            "project is active. Resume it first.",
        )
    if not add and not remove:
        raise LifecycleError("no_change", "Pick cameras to add or remove.")
    if add & remove:
        raise LifecycleError("bad_request", "A camera cannot be added and removed at once.")
    known = {c.vas_device_id: c for c in cameras}
    unknown = sorted((add | remove) - set(known))
    if unknown:
        raise LifecycleError("unknown_camera", f"VAS does not know camera(s) {', '.join(unknown)}.")
    not_in_ruth = sorted(known[c].name for c in add if not known[c].device_id)
    if not_in_ruth:
        raise LifecycleError(
            "camera_not_synced",
            f"Ruth has not synced {', '.join(not_in_ruth)} yet; open Cameras once and retry.",
        )
    already = sorted(known[c].name for c in add if known[c].device_id in members)
    if already:
        raise LifecycleError("already_member", f"Already in the project: {', '.join(already)}.")
    outside = sorted(known[c].name for c in remove if known[c].device_id not in members)
    if outside:
        raise LifecycleError("not_member", f"Not in the project: {', '.join(outside)}.")


async def open_members(db: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Open membership rows of a project, by Ruth device id (str)."""
    from app.models.project import ProjectCamera

    rows = (
        await db.execute(
            select(ProjectCamera).where(
                ProjectCamera.project_id == project_id, ProjectCamera.left_at.is_(None)
            )
        )
    ).scalars().all()
    return {str(r.device_id): r for r in rows}


async def close_memberships(db: AsyncSession, project_id: uuid.UUID, at: datetime) -> None:
    """End: every open membership of the project closes when it ends."""
    from app.models.project import ProjectCamera

    await db.execute(
        update(ProjectCamera)
        .where(ProjectCamera.project_id == project_id, ProjectCamera.left_at.is_(None))
        .values(left_at=at)
    )


def check_allowed(action: str, state: str | None, *, project_name: str | None = None,
                  confirm_name: str | None = None) -> None:
    """Which transitions are allowed from which state. Raises LifecycleError."""
    if state is None:
        raise LifecycleError("no_project", "There is no current project.")
    if action == ACTION_STOP and state not in (PROJECT_STATE_ACTIVE, PROJECT_STATE_STOPPING):
        raise LifecycleError("bad_state", f"Cannot stop a project that is {state}.")
    if action == ACTION_RESUME and state not in (PROJECT_STATE_STOPPED, PROJECT_STATE_RESUMING):
        raise LifecycleError(
            "bad_state",
            "An ended project cannot be resumed." if state == PROJECT_STATE_ENDED
            else f"Cannot resume a project that is {state}.",
        )
    if action == ACTION_END:
        if state not in (PROJECT_STATE_ACTIVE, PROJECT_STATE_STOPPING, PROJECT_STATE_STOPPED):
            raise LifecycleError("bad_state", f"Cannot end a project that is {state}.")
        if not confirm_name or confirm_name != project_name:
            raise LifecycleError(
                "confirmation_mismatch", "Type the project name exactly to end it."
            )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


@dataclass
class LifecycleResult:
    project: Project
    cameras: list[CameraPlan]
    errors: list[str]
    retention_paused: bool | None

    @property
    def complete(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# The one-at-a-time lock
# ---------------------------------------------------------------------------


class LifecycleLock:
    """Postgres session lock held on a connection of its own.

    A session-level advisory lock belongs to the connection that took it.
    The lifecycle actions commit part-way through, and every commit hands
    the request session's connection back to the pool, so a lock taken on
    that session was later "released" on a different connection (a no-op)
    and stayed held by a pooled connection until the backend restarted:
    the next action then waited forever. Holding it on a dedicated
    connection, which nothing else commits on or returns to the pool, keeps
    take and release on the same connection.

    It never waits: a second action is refused at once (409
    ``lifecycle_busy``) instead of hanging behind the first.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    async def is_held(self) -> bool:
        """Is any lifecycle action running right now (on any worker)?"""
        async with self._engine.connect() as conn:
            held = (
                await conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory'"
                        " AND granted AND objsubid = 1"
                        " AND ((classid::bigint << 32) | objid::bigint) = :k)"
                    ),
                    {"k": LIFECYCLE_LOCK_KEY},
                )
            ).scalar()
        return bool(held)

    @asynccontextmanager
    async def held(self) -> AsyncIterator[None]:
        async with self._engine.connect() as conn:
            got = (
                await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LIFECYCLE_LOCK_KEY})
            ).scalar()
            await conn.commit()  # hold the lock without sitting idle in a transaction
            if not got:
                raise LifecycleError(LIFECYCLE_BUSY, LIFECYCLE_BUSY_MESSAGE)
            try:
                yield
            finally:
                try:
                    await conn.execute(
                        text("SELECT pg_advisory_unlock(:k)"), {"k": LIFECYCLE_LOCK_KEY}
                    )
                    await conn.commit()
                except Exception:
                    # Never put a connection that may still hold the lock back
                    # in the pool: closing it releases the lock server-side.
                    logger.exception("Lifecycle unlock failed; discarding the connection")
                    await conn.invalidate()


#: (stage, detail) -> None. The job runner records it; requests ignore it.
Progress = Callable[[str, "str | None"], Awaitable[None]]


async def _no_progress(stage: str, detail: str | None = None) -> None:
    return None


class ProjectLifecycleService:
    def __init__(
        self, db: AsyncSession, vas_client, stream_service, *, lock: LifecycleLock | None = None
    ) -> None:
        self._db = db
        self._vas = vas_client
        self._streams = stream_service
        self._lock = lock if lock is not None else LifecycleLock(db.bind)
        #: Stage reporting; the job runner replaces it (see project_jobs.py).
        self.progress: Progress = _no_progress
        #: The stage running now, and the one where the first error happened
        #: (so a failed job points Retry at the right stage).
        self.stage_now: str | None = None
        self.error_stage: str | None = None

    async def _stage(self, stage: str, detail: str | None = None) -> None:
        self.stage_now = stage
        await self.progress(stage, detail)

    def _note_error(self, errors: list[str], message: str) -> None:
        if self.error_stage is None:
            self.error_stage = self.stage_now
        errors.append(message)

    @property
    def lock(self) -> LifecycleLock:
        return self._lock

    async def busy(self) -> bool:
        """Is another project action running right now?"""
        return await self._lock.is_held()

    async def cameras(self) -> list[CameraState]:
        """Every VAS camera, joined to Ruth's intent and live session."""
        vas_devices = await self._vas.get_devices(limit=1000)
        ruth = {
            d.vas_device_id: d
            for d in (await self._db.execute(select(Device))).scalars().all()
        }
        intents = {
            i.device_id: i
            for i in (await self._db.execute(select(DeviceInferenceIntent))).scalars().all()
        }
        live = set(
            (
                await self._db.execute(
                    select(StreamSession.device_id).where(StreamSession.state == StreamState.LIVE)
                )
            ).scalars().all()
        )
        out = []
        for v in sorted(vas_devices, key=lambda d: d.name):
            device = ruth.get(v.id)
            intent = intents.get(device.id) if device else None
            out.append(CameraState(
                vas_device_id=v.id,
                name=(device.display_name if device and device.display_name else v.name),
                vas_enabled=bool(v.enabled),
                video_state=getattr(v, "video_state", None),
                device_id=str(device.id) if device else None,
                intent=intent.desired_state if intent else None,
                intent_models=len(intent.models or []) if intent else 0,
                live_session=bool(device and device.id in live),
            ))
        return out

    async def preflight(self, action: str) -> tuple[Project | None, list[CameraPlan]]:
        project = await site_project(self._db)
        cameras = await self.cameras()
        if action == ACTION_RESUME:
            return project, plan_resume(cameras, project.lifecycle_snapshot if project else None)
        return project, plan_stop(cameras)

    async def stop(self, by: str, *, end: bool = False, confirm_name: str | None = None) -> LifecycleResult:
        async with self._lock.held():
            return await self._stop(by, end=end, confirm_name=confirm_name)

    async def _stop(self, by: str, *, end: bool, confirm_name: str | None) -> LifecycleResult:
        project = await site_project(self._db)
        check_allowed(
            ACTION_END if end else ACTION_STOP,
            project.state if project else None,
            project_name=project.name if project else None,
            confirm_name=confirm_name,
        )
        now = datetime.now(timezone.utc)
        await self._stage("idle", None)
        cameras = await self.cameras()

        if project.state == PROJECT_STATE_ACTIVE:
            # Idle first, snapshot before any change; committed together so a
            # crash after this point resumes from the true pre-Stop state.
            project.state = PROJECT_STATE_STOPPING
            project.stopped_at, project.stopped_by = now, by
            project.lifecycle_snapshot = snapshot_of(cameras, now, by)
            await self._db.commit()

        plans = plan_stop(cameras)
        errors: list[str] = []

        await self._stage("sessions", None)
        for cam in cameras:
            if cam.live_session and cam.device_id:
                try:
                    await self._streams.stop_inference(uuid.UUID(cam.device_id))
                except Exception as e:  # noqa: BLE001 - record and carry on
                    self._note_error(errors, f"{cam.name}: could not end inference session ({e})")

        to_disable = [cam for cam in cameras if cam.vas_enabled]
        await self._stage("cameras", f"{len(to_disable)} to disable" if to_disable else "none enabled")
        for i, cam in enumerate(to_disable, 1):
            await self._stage("cameras", f"{cam.name} ({i}/{len(to_disable)})")
            try:
                await self._vas.set_device_enabled(cam.vas_device_id, False)
            except Exception as e:  # noqa: BLE001
                self._note_error(errors, f"{cam.name}: VAS did not disable it ({e})")

        await self._stage("retention", None)
        paused = await self._set_retention_paused(True, errors)

        await self._stage("finish", None)
        if errors:
            project.lifecycle_error = "; ".join(errors)[:4000]
            await self._db.commit()
            logger.warning("Project stop incomplete", project=project.name, errors=errors, by=by)
        else:
            if end:
                project.state = PROJECT_STATE_ENDED
                project.ended_at, project.ended_by = now, by
                await close_memberships(self._db, project.id, now)
            elif project.state == PROJECT_STATE_STOPPING:
                project.state = PROJECT_STATE_STOPPED
            project.lifecycle_error = None
            await self._db.commit()
            logger.warning(
                "Project ended" if end else "Project stopped",
                project=project.name,
                cameras_disabled=sum(1 for c in cameras if c.vas_enabled),
                by=by,
            )
        return LifecycleResult(project, plans, errors, paused)

    async def resume(self, by: str) -> LifecycleResult:
        async with self._lock.held():
            return await self._resume(by)

    async def _resume(self, by: str) -> LifecycleResult:
        project = await site_project(self._db)
        check_allowed(ACTION_RESUME, project.state if project else None)
        now = datetime.now(timezone.utc)
        await self._stage("resuming", None)
        project.state = PROJECT_STATE_RESUMING
        await self._db.commit()

        cameras = await self.cameras()
        plans = plan_resume(cameras, project.lifecycle_snapshot)
        errors: list[str] = []
        to_enable = [p for p in plans if p.vas_change]
        await self._stage("cameras", f"{len(to_enable)} to re-enable" if to_enable else "none to re-enable")
        for i, plan in enumerate(to_enable, 1):
            await self._stage("cameras", f"{plan.name} ({i}/{len(to_enable)})")
            try:
                await self._vas.set_device_enabled(plan.vas_device_id, True)
            except Exception as e:  # noqa: BLE001
                self._note_error(errors, f"{plan.name}: VAS did not re-enable it ({e})")

        # Deliberately NOT un-pausing footage deletion: that is an operator
        # decision in Settings -> System, never a side effect of Resume.
        paused = await self._read_retention_paused()

        await self._stage("finish", None)
        if errors:
            project.lifecycle_error = "; ".join(errors)[:4000]
            await self._db.commit()
            logger.warning("Project resume incomplete", project=project.name, errors=errors, by=by)
        else:
            project.state = PROJECT_STATE_ACTIVE
            project.resumed_at, project.resumed_by = now, by
            project.lifecycle_error = None
            await self._db.commit()
            logger.warning(
                "Project resumed",
                project=project.name,
                cameras_enabled=sum(1 for p in plans if p.vas_change),
                by=by,
            )
        return LifecycleResult(project, plans, errors, paused)

    async def start_preflight(self, chosen: set[str] | None = None) -> tuple[Project | None, Project | None, list[CameraPlan]]:
        """(blocking current project, last project, plan).

        Nothing is picked by default: after End every camera is disabled, so
        "the cameras enabled now" would always be none.
        """
        current = await current_project(self._db)
        last = await site_project(self._db)
        cameras = await self.cameras()
        return current, last, plan_start(cameras, chosen or set())

    async def start(
        self,
        by: str,
        *,
        name: str,
        confirm_name: str,
        camera_ids: list[str],
        backup_path: str | None = None,
        allow_no_cameras: bool = False,
    ) -> LifecycleResult:
        """Open the next project with the cameras `camera_ids` (VAS ids)."""
        async with self._lock.held():
            project, chosen = await self._start_create(
                by, name=name, confirm_name=confirm_name, camera_ids=camera_ids,
                backup_path=backup_path, allow_no_cameras=allow_no_cameras,
            )
            return await self._start_cameras(project, chosen, by=by)

    async def _start_create(
        self, by: str, *, name: str, confirm_name: str, camera_ids: list[str],
        backup_path: str | None, allow_no_cameras: bool = False, job_id: uuid.UUID | None = None,
    ) -> tuple[Project, set[str]]:
        """Create the project and its camera list, in one commit.

        With `job_id`, the job row gets the project id in the same commit, so
        a Retry after a crash knows whether the project already exists.
        """
        from app.models.project import ProjectCamera
        from app.models.project_job import ProjectJob
        from app.services.project_service import ProjectNameInUseError, slugify

        name = name.strip()
        confirm_name = confirm_name.strip()
        current = await current_project(self._db)
        check_start(current, name=name, confirm_name=confirm_name)
        slug = slugify(name)
        if (await self._db.execute(select(Project.id).where(Project.slug == slug))).scalars().first():
            raise ProjectNameInUseError(slug)

        cameras = await self.cameras()
        known = {c.vas_device_id: c for c in cameras}
        chosen = set(camera_ids)
        check_start_cameras(cameras, chosen, allow_no_cameras=allow_no_cameras)

        previous = await site_project(self._db)
        if previous is not None and backup_path:
            previous.backup_path = backup_path

        project = Project(
            name=name, slug=slug, state=PROJECT_STATE_ACTIVE,
            started_at=datetime.now(timezone.utc), started_by=by,
        )
        self._db.add(project)
        await self._db.flush()
        for vas_id in sorted(chosen):
            self._db.add(ProjectCamera(
                project_id=project.id, device_id=uuid.UUID(known[vas_id].device_id), source="dialog",
                joined_at=project.started_at,
            ))
        if job_id is not None:
            await self._db.execute(
                update(ProjectJob).where(ProjectJob.id == job_id).values(project_id=project.id)
            )
        # Committed before VAS is touched: from here on every new row is
        # tagged with the new project by the database default.
        await self._db.commit()
        logger.warning(
            "Project created",
            project=name,
            previous=previous.name if previous else None,
            cameras=sorted(known[c].name for c in chosen),
            by=by,
        )
        return project, chosen

    async def _start_cameras(self, project: Project, chosen: set[str], *, by: str) -> LifecycleResult:
        """Enable the picked cameras in VAS and disable the rest.

        Safe to run again: the plan compares with VAS as it is now, so a
        Retry only switches the cameras still in the wrong state.
        """
        cameras = await self.cameras()
        plans = plan_start(cameras, chosen)
        errors: list[str] = []
        changes = [p for p in plans if p.vas_change]
        await self._stage("cameras", f"{len(changes)} to switch" if changes else "nothing to switch")
        for i, plan in enumerate(changes, 1):
            enable = plan.vas_device_id in chosen
            await self._stage("cameras", f"{plan.name} ({i}/{len(changes)})")
            try:
                await self._vas.set_device_enabled(plan.vas_device_id, enable)
            except Exception as e:  # noqa: BLE001 - record and carry on
                self._note_error(errors, f"{plan.name}: VAS did not {'enable' if enable else 'disable'} it ({e})")

        # Footage deletion is left exactly as it is (normally paused since End).
        paused = await self._read_retention_paused()
        project.lifecycle_error = "; ".join(errors)[:4000] if errors else None
        await self._db.commit()
        logger.warning(
            "Project started" if not errors else "Project started; camera switching incomplete",
            project=project.name,
            cameras=sorted(p.name for p in plans if p.vas_device_id in chosen),
            errors=errors,
            by=by,
        )
        return LifecycleResult(project, plans, errors, paused)

    async def change_cameras_preflight(
        self, add: set[str], remove: set[str]
    ) -> tuple[Project | None, dict[str, Any], list[CameraPlan]]:
        project = await current_project(self._db)
        members = await open_members(self._db, project.id) if project else {}
        cameras = await self.cameras()
        return project, members, plan_change(cameras, set(members), add, remove)

    async def change_cameras(self, by: str, *, add: list[str], remove: list[str]) -> LifecycleResult:
        async with self._lock.held():
            return await self._change_cameras(by, add=add, remove=remove)

    async def _change_cameras(self, by: str, *, add: list[str], remove: list[str]) -> LifecycleResult:
        """Add and remove cameras of the active project, one camera at a time.

        Per camera, VAS first, then the membership row once VAS confirmed, each
        committed on its own: a crash leaves every finished camera finished,
        and Retry (same lists) skips what is already right. Never touches a
        camera's VAS placement; inference intents are kept (the reconciler
        suspends a disabled camera's intent and restores it when re-enabled).
        """
        from app.models.project import ProjectCamera

        project = await current_project(self._db)
        if project is None or project.state != PROJECT_STATE_ACTIVE:
            raise LifecycleError(
                "bad_state",
                "Cameras can be changed only while the project is active. Resume it first.",
            )
        cameras = await self.cameras()
        known = {c.vas_device_id: c for c in cameras}
        members = await open_members(self._db, project.id)
        plans = plan_change(cameras, set(members), set(add), set(remove))
        work = [(v, "add") for v in sorted(set(add))] + [(v, "remove") for v in sorted(set(remove))]
        errors: list[str] = []
        await self._stage("cameras", f"{len(work)} to change")
        for i, (vas_id, op) in enumerate(work, 1):
            cam = known.get(vas_id)
            if cam is None:
                self._note_error(errors, f"{vas_id}: VAS no longer knows this camera")
                continue
            await self._stage("cameras", f"{cam.name} ({i}/{len(work)})")
            if cam.device_id is None:
                self._note_error(errors, f"{cam.name}: Ruth has not synced it yet")
                continue
            device_id = uuid.UUID(cam.device_id)
            try:
                if op == "add":
                    if not cam.vas_enabled:
                        await self._vas.set_device_enabled(vas_id, True)
                    if cam.device_id not in members:
                        self._db.add(ProjectCamera(
                            project_id=project.id, device_id=device_id, source="dialog",
                            joined_at=datetime.now(timezone.utc),
                        ))
                else:
                    if cam.live_session and self._streams is not None:
                        await self._streams.stop_inference(device_id)
                    if cam.vas_enabled:
                        await self._vas.set_device_enabled(vas_id, False)
                    row = members.get(cam.device_id)
                    if row is not None:
                        row.left_at = datetime.now(timezone.utc)
                await self._db.commit()
            except Exception as e:  # noqa: BLE001 - record and carry on
                await self._db.rollback()
                verb = "add" if op == "add" else "remove"
                self._note_error(errors, f"{cam.name}: could not {verb} it ({e})")

        paused = await self._read_retention_paused()
        project = await self._db.get(Project, project.id)
        project.lifecycle_error = "; ".join(errors)[:4000] if errors else None
        await self._db.commit()
        logger.warning(
            "Project cameras changed" if not errors else "Project cameras changed; incomplete",
            project=project.name,
            added=sorted(known[v].name for v in add if v in known),
            removed=sorted(known[v].name for v in remove if v in known),
            errors=errors,
            by=by,
        )
        return LifecycleResult(project, plans, errors, paused)

    async def _read_retention_paused(self) -> bool | None:
        try:
            return bool((await self._vas.get_storage_config()).get("retention_paused"))
        except Exception:  # noqa: BLE001 - display only
            return None

    async def _set_retention_paused(self, paused: bool, errors: list[str]) -> bool | None:
        try:
            config = await self._vas.update_storage_config({"retention_paused": paused})
            return bool(config.get("retention_paused"))
        except Exception as e:  # noqa: BLE001
            self._note_error(errors, f"VAS footage-deletion pause not {'set' if paused else 'cleared'} ({e})")
            return None


def plan_as_dict(plan: CameraPlan) -> dict[str, Any]:
    return asdict(plan)

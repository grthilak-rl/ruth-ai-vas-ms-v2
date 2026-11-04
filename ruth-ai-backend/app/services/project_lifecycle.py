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

Every step is idempotent, so a Stop that failed half-way (a camera VAS would
not disable) leaves the project in ``stopping`` with the error recorded, and
running Stop again finishes it. Resume is the mirror: ``resuming``, re-enable
the snapshot's cameras, un-pause deletion, ``active``; the reconciler then
restores inference from the untouched intents.

End is Stop that cannot be resumed. Nothing is deleted or archived by any of
these: footage, frames, violations and reports stay readable.

The per-camera plan (what will change) is computed by pure functions shared
by the preflight screen and the executor, so what the admin confirms is what
runs.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
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

#: Advisory lock for Stop/Resume/End; two at once must not interleave.
LIFECYCLE_LOCK_KEY = 0x52555448_4C494645  # "RUTH" "LIFE"

ACTION_STOP = "stop"
ACTION_END = "end"
ACTION_RESUME = "resume"


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
    return (
        await db.execute(
            select(Project)
            .where(Project.state.in_(CURRENT_PROJECT_STATES))
            .order_by(Project.started_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def site_state(db: AsyncSession) -> str | None:
    """The current project's state, or None when there is no project yet."""
    project = await current_project(db)
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


class ProjectLifecycleService:
    def __init__(self, db: AsyncSession, vas_client, stream_service) -> None:
        self._db = db
        self._vas = vas_client
        self._streams = stream_service

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
        project = await current_project(self._db)
        cameras = await self.cameras()
        if action == ACTION_RESUME:
            return project, plan_resume(cameras, project.lifecycle_snapshot if project else None)
        return project, plan_stop(cameras)

    async def _lock(self) -> None:
        await self._db.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LIFECYCLE_LOCK_KEY})

    async def _unlock(self) -> None:
        await self._db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LIFECYCLE_LOCK_KEY})

    async def stop(self, by: str, *, end: bool = False, confirm_name: str | None = None) -> LifecycleResult:
        await self._lock()
        try:
            return await self._stop(by, end=end, confirm_name=confirm_name)
        finally:
            await self._unlock()

    async def _stop(self, by: str, *, end: bool, confirm_name: str | None) -> LifecycleResult:
        project = await current_project(self._db)
        check_allowed(
            ACTION_END if end else ACTION_STOP,
            project.state if project else None,
            project_name=project.name if project else None,
            confirm_name=confirm_name,
        )
        now = datetime.now(timezone.utc)
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

        for cam in cameras:
            if cam.live_session and cam.device_id:
                try:
                    await self._streams.stop_inference(uuid.UUID(cam.device_id))
                except Exception as e:  # noqa: BLE001 - record and carry on
                    errors.append(f"{cam.name}: could not end inference session ({e})")

        for cam in cameras:
            if cam.vas_enabled:
                try:
                    await self._vas.set_device_enabled(cam.vas_device_id, False)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{cam.name}: VAS did not disable it ({e})")

        paused = await self._set_retention_paused(True, errors)

        if errors:
            project.lifecycle_error = "; ".join(errors)[:4000]
            await self._db.commit()
            logger.warning("Project stop incomplete", project=project.name, errors=errors, by=by)
        else:
            if end:
                project.state = PROJECT_STATE_ENDED
                project.ended_at, project.ended_by = now, by
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
        await self._lock()
        try:
            return await self._resume(by)
        finally:
            await self._unlock()

    async def _resume(self, by: str) -> LifecycleResult:
        project = await current_project(self._db)
        check_allowed(ACTION_RESUME, project.state if project else None)
        now = datetime.now(timezone.utc)
        project.state = PROJECT_STATE_RESUMING
        await self._db.commit()

        cameras = await self.cameras()
        plans = plan_resume(cameras, project.lifecycle_snapshot)
        errors: list[str] = []
        for plan in plans:
            if plan.vas_change:
                try:
                    await self._vas.set_device_enabled(plan.vas_device_id, True)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{plan.name}: VAS did not re-enable it ({e})")

        paused = await self._set_retention_paused(False, errors)

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

    async def _set_retention_paused(self, paused: bool, errors: list[str]) -> bool | None:
        try:
            config = await self._vas.update_storage_config({"retention_paused": paused})
            return bool(config.get("retention_paused"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"VAS footage-deletion pause not {'set' if paused else 'cleared'} ({e})")
            return None


def plan_as_dict(plan: CameraPlan) -> dict[str, Any]:
    return asdict(plan)

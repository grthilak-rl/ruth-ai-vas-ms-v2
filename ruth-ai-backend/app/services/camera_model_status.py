"""Is each model on each camera actually working?

A model can fail on every frame while its session reads as live: on
2026-11-19 the retired geo_fencing ran 22 minutes on a camera, failing every
frame, with System Health, the camera tile and the badge all quiet. This is
what makes that visible.

Per camera model, one of:

- ``running``: no failure, or it has succeeded within the last 60 s
- ``failing``: it has failed for ``FAILING_AFTER_SECONDS`` with no success
- ``unavailable``: it is not installed (retired or never installed). That is
  known at once, so there is no 60 s wait. This includes models a resume
  left out because they are not installed (``in_session`` false).

The inference loop reports every model outcome to ``tracker``; it is in
memory, so a backend restart starts every model from "running" again (and a
model still failing is "failing" 60 s later).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import INTENT_ACTIVE, Device, DeviceInferenceIntent, StreamSession
from app.services.model_availability import unavailable_models
from app.services.session_models import ACTIVE_STATES, session_entries

FAILING_AFTER_SECONDS = 60.0

STATUS_RUNNING = "running"
STATUS_FAILING = "failing"
STATUS_UNAVAILABLE = "unavailable"


@dataclass
class _Health:
    failing_since: Optional[float] = None  # monotonic: first failure since the last success
    failing_since_at: Optional[datetime] = None
    last_error: Optional[str] = None
    errors: int = 0  # failures since the last success


@dataclass
class ModelHealth:
    status: str
    failing_since: Optional[datetime] = None
    last_error: Optional[str] = None
    errors: int = 0


class CameraModelTracker:
    """Outcomes of each (camera, model), as the inference loop reports them."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._clock = clock
        self._wall = wall
        self._health: dict[tuple[UUID, str], _Health] = {}

    def record_success(self, device_id: UUID, model_id: str) -> None:
        self._health.pop((device_id, model_id), None)

    def record_failure(self, device_id: UUID, model_id: str, error: str) -> None:
        h = self._health.setdefault((device_id, model_id), _Health())
        if h.failing_since is None:
            h.failing_since = self._clock()
            h.failing_since_at = self._wall()
        h.errors += 1
        h.last_error = (error or "no usable result")[:500]

    def health(self, device_id: UUID, model_id: str) -> ModelHealth:
        h = self._health.get((device_id, model_id))
        if h is None or h.failing_since is None:
            return ModelHealth(STATUS_RUNNING)
        if self._clock() - h.failing_since < FAILING_AFTER_SECONDS:
            return ModelHealth(STATUS_RUNNING, last_error=h.last_error, errors=h.errors)
        return ModelHealth(STATUS_FAILING, h.failing_since_at, h.last_error, h.errors)

    def reset(self) -> None:
        self._health.clear()


#: The process-wide tracker the inference loop reports to.
tracker = CameraModelTracker()


@dataclass
class CameraModelStatus:
    device_id: UUID
    camera: str
    model_id: str
    status: str
    in_session: bool
    reason: Optional[str] = None  # model_retired / model_not_installed / inference_failing
    message: Optional[str] = None
    replacement: Optional[str] = None
    failing_since: Optional[datetime] = None
    errors: int = 0

    def as_dict(self) -> dict[str, Any]:
        out = {
            "device_id": str(self.device_id),
            "camera": self.camera,
            "model_id": self.model_id,
            "status": self.status,
            "in_session": self.in_session,
            "reason": self.reason,
            "message": self.message,
        }
        if self.replacement:
            out["replacement"] = self.replacement
        if self.failing_since:
            out["failing_since"] = self.failing_since.isoformat()
            out["errors"] = self.errors
        return out


@dataclass
class _Camera:
    device_id: UUID
    name: str
    session_models: list[str] = field(default_factory=list)
    intent_models: list[str] = field(default_factory=list)


async def _cameras(db: AsyncSession, device_id: Optional[UUID] = None) -> list[_Camera]:
    """Cameras with a live session or an active intent, and their models."""
    cams: dict[UUID, _Camera] = {}
    q = select(StreamSession, Device).join(Device, Device.id == StreamSession.device_id).where(
        StreamSession.state.in_(ACTIVE_STATES)
    )
    if device_id is not None:
        q = q.where(StreamSession.device_id == device_id)
    for session, device in (await db.execute(q)).all():
        cam = cams.setdefault(device.id, _Camera(device.id, device.display_name or device.name))
        cam.session_models = [e["model_id"] for e in session_entries(session)]
    q = select(DeviceInferenceIntent, Device).join(Device, Device.id == DeviceInferenceIntent.device_id).where(
        DeviceInferenceIntent.desired_state == INTENT_ACTIVE
    )
    if device_id is not None:
        q = q.where(DeviceInferenceIntent.device_id == device_id)
    for intent, device in (await db.execute(q)).all():
        cam = cams.setdefault(device.id, _Camera(device.id, device.display_name or device.name))
        cam.intent_models = [e.get("model_id") for e in (intent.models or []) if e.get("model_id")]
    return list(cams.values())


async def camera_model_statuses(
    db: AsyncSession,
    device_id: Optional[UUID] = None,
    model_tracker: Optional[CameraModelTracker] = None,
) -> list[CameraModelStatus]:
    """Status of every model on every camera that runs or should run.

    Models in a session are reported running / failing / unavailable. Models
    only in the saved list (a resume left them out) are reported only when
    they are not installed: that is the one reason they are missing.
    """
    model_tracker = model_tracker or tracker
    cams = await _cameras(db, device_id)
    missing = await unavailable_models(
        {m for c in cams for m in c.session_models + c.intent_models}
    )
    out: list[CameraModelStatus] = []
    for cam in cams:
        for model_id in cam.session_models:
            out.append(_status(cam, model_id, True, missing, model_tracker))
        for model_id in cam.intent_models:
            if model_id not in cam.session_models and model_id in missing:
                out.append(_status(cam, model_id, False, missing, model_tracker))
    return out


def _status(cam: _Camera, model_id: str, in_session: bool, missing: dict, model_tracker) -> CameraModelStatus:
    base = dict(device_id=cam.device_id, camera=cam.name, model_id=model_id, in_session=in_session)
    err = missing.get(model_id)
    if err is not None:
        return CameraModelStatus(
            **base, status=STATUS_UNAVAILABLE, reason=err.code, message=err.message, replacement=err.replacement
        )
    h = model_tracker.health(cam.device_id, model_id)
    if h.status == STATUS_FAILING:
        return CameraModelStatus(
            **base,
            status=STATUS_FAILING,
            reason="inference_failing",
            message=f"No result for {_ago(h.failing_since)}: {h.last_error}",
            failing_since=h.failing_since,
            errors=h.errors,
        )
    return CameraModelStatus(**base, status=STATUS_RUNNING)


def _ago(since: Optional[datetime]) -> str:
    if since is None:
        return "over a minute"
    seconds = max(0, int((datetime.now(timezone.utc) - since) / timedelta(seconds=1)))
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"

"""Put inference back when it stops on its own.

BL-11 A. A session can die for reasons nobody chose — a backend restart
mid-handover, VAS dropping a stream, a crash. Before this, nothing
noticed: camera 74004 ran 21.3 hours with live video and no inference
while every service indicator read healthy.

The rules that matter are the ones about *not* acting:

* An operator who stopped inference has `desired_state = off`, and that
  is never overridden. Auto-recovery that fights the operator is worse
  than no auto-recovery.
* A camera whose video is offline is not a failure to resume — there is
  nothing to resume. Counting it would park every camera on a site-wide
  network blip, which is precisely when recovery is most wanted.
* A shared dependency being down (VAS, a runtime) is one system problem,
  not twelve camera problems. Those cycles are skipped whole and raise a
  single alert instead of twelve.

What remains — a camera whose video is live, whose dependencies are up,
and which still will not start — is a real per-camera fault, and after
two of those it is parked and retried on a capped backoff.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import (
    INTENT_ACTIVE,
    INTENT_SUSPENDED,
    Device,
    DeviceInferenceIntent,
    StreamSession,
    StreamState,
)
from app.services.inference_intent import (
    InferenceIntentService,
    is_parked,
    may_attempt,
)

logger = get_logger(__name__)


class VasState:
    """What VAS currently says about one camera."""

    __slots__ = ("video_live", "enabled", "is_active")

    def __init__(self, video_live: bool, enabled: Optional[bool], is_active: Optional[bool]):
        self.video_live = video_live
        self.enabled = enabled
        self.is_active = is_active

#: Sessions in these states count as "inference is happening or about to".
#: STARTING is included deliberately: a camera mid-start is not a camera
#: that needs starting, and racing it would create two sessions.
RUNNING_STATES = (StreamState.LIVE, StreamState.STARTING)

#: How long after an operator changes intent before the reconciler will
#: act on that camera. The picker writes intent and then starts a session
#: a moment later; without a grace window the reconciler can see the gap
#: between those two and "resume" a camera that is already starting.
INTENT_GRACE_SECONDS = 30


class ReconcileOutcome:
    """What one cycle did, for logging and for the health endpoint."""

    def __init__(self) -> None:
        self.checked = 0
        self.resumed: list[str] = []
        self.failed: list[str] = []
        self.skipped_no_video: list[str] = []
        self.skipped_grace: list[str] = []
        self.parked: list[str] = []
        self.suspended: list[str] = []
        self.unsuspended: list[str] = []
        self.dependency_error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "resumed": self.resumed,
            "failed": self.failed,
            "skipped_no_video": self.skipped_no_video,
            "skipped_grace": self.skipped_grace,
            "parked": self.parked,
            "suspended": self.suspended,
            "unsuspended": self.unsuspended,
            "dependency_error": self.dependency_error,
        }


class InferenceReconciler:
    """Periodically bring reality back to the operator's intent."""

    def __init__(
        self,
        db_session_factory: Callable[[], AsyncSession],
        stream_service_factory: Callable[[AsyncSession], Any],
        vas_client: Any,
        interval_seconds: float = 60.0,
    ):
        self._db_session_factory = db_session_factory
        self._stream_service_for = stream_service_factory
        self._vas = vas_client
        self._interval = interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        #: Last cycle's result, surfaced by System Health.
        self.last_outcome: Optional[ReconcileOutcome] = None
        self.last_run_at: Optional[datetime] = None
        #: device_id -> when it was auto-resumed, for the 24 h summary.
        self._resume_log: list[tuple[datetime, str]] = []

    def _db(self):
        """A DB session whose rollback path actually runs on failure.

        The factory is an async *generator*, not a context manager.
        Wrapping it in asynccontextmanager is what makes `__aexit__` call
        `athrow()`, so a failure reaches the generator's `except` branch
        and rolls back — see InferenceLoopService._db for the full
        account of what driving it by hand breaks.
        """
        return asynccontextmanager(self._db_session_factory)()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Inference reconciler started", interval_seconds=self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Inference reconciler stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                self.last_outcome = await self.reconcile_once()
                self.last_run_at = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # never let one bad cycle kill the loop
                logger.error(f"Reconcile cycle failed: {e}", exc_info=True)
            await asyncio.sleep(self._interval)

    # -- the cycle ---------------------------------------------------------

    async def reconcile_once(self) -> ReconcileOutcome:
        out = ReconcileOutcome()
        now = datetime.now(timezone.utc)

        async with self._db() as db:
            intents = (
                await db.execute(
                    select(DeviceInferenceIntent, Device)
                    .join(Device, Device.id == DeviceInferenceIntent.device_id)
                    .where(
                        DeviceInferenceIntent.desired_state.in_(
                            (INTENT_ACTIVE, INTENT_SUSPENDED)
                        )
                    )
                )
            ).all()

            if not intents:
                return out

            intents_service = InferenceIntentService(db)

            # One VAS read for the whole cycle. If it fails this is a
            # shared-dependency problem: skip everything, count nothing,
            # raise one alert.
            try:
                vas_state = await self._vas_state_map(
                    [device for _intent, device in intents]
                )
            except Exception as e:
                out.dependency_error = f"VAS unreachable: {e}"
                logger.warning(
                    "Reconcile skipped: shared dependency unavailable",
                    error=str(e),
                    cameras=len(intents),
                )
                return out

            running = await self._running_device_ids(db)

            for intent, device in intents:
                name = device.name
                state = vas_state.get(device.id)

                # Refresh `enabled` from the device list this cycle already
                # fetched. Previously it only changed on a full device sync
                # — startup or a manual call — so a camera disabled in VAS
                # stayed "enabled" in Ruth indefinitely and the reconciler
                # kept trying to resume it.
                if state is not None and state.enabled is not None:
                    if device.enabled != state.enabled:
                        device.enabled = state.enabled
                        logger.info(
                            "Device enabled flag refreshed from VAS",
                            device=name, enabled=state.enabled,
                        )
                    if state.is_active is not None:
                        device.is_active = state.is_active

                disabled = not getattr(device, "is_active", True) or not getattr(
                    device, "enabled", True
                )

                if disabled:
                    # Disabling a camera in VAS has to stop its inference —
                    # nothing else does, so it would otherwise keep running
                    # on a camera nobody can see. Suspended, not off: the
                    # models are kept so re-enabling restores them.
                    if intent.desired_state == INTENT_ACTIVE:
                        await intents_service.suspend(intent)
                        out.suspended.append(name)
                        logger.info(
                            "Camera disabled in VAS; inference suspended",
                            device=name,
                            models=[e.get("model_id") for e in (intent.models or [])],
                        )
                    if device.id in running:
                        await self._stop(db, device)
                    continue

                if intent.desired_state == INTENT_SUSPENDED:
                    # It is back. Want the same models again; the resume
                    # itself happens below, by the ordinary path.
                    await intents_service.unsuspend(intent)
                    out.unsuspended.append(name)
                    logger.info(
                        "Camera re-enabled in VAS; restoring inference",
                        device=name,
                        models=[e.get("model_id") for e in (intent.models or [])],
                    )

                out.checked += 1

                if intent.device_id in running:
                    # Healthy. Clear any failure history so a camera that
                    # recovered does not stay parked.
                    if intent.consecutive_failures:
                        intent.consecutive_failures = 0
                        intent.last_error = None
                    continue

                # Just-changed intent: the picker writes intent then starts
                # the session; do not race it.
                #
                # Only for operator changes. The reconciler's own writes —
                # un-suspending a camera that came back, say — have nothing
                # to race, and applying the grace to them would make a
                # re-enabled camera wait an extra full cycle for no reason.
                operator_change = not str(intent.updated_by or "").startswith("reconciler")
                if (
                    operator_change
                    and intent.updated_at
                    and (now - intent.updated_at) < timedelta(seconds=INTENT_GRACE_SECONDS)
                ):
                    out.skipped_grace.append(name)
                    continue

                # No video means nothing to resume. Not a failure — this is
                # the camera-offline case, and parking on it would guarantee
                # the fleet is parked exactly when a site link flaps.
                if not (state.video_live if state else False):
                    out.skipped_no_video.append(name)
                    continue

                if is_parked(intent) and not may_attempt(intent, now):
                    out.parked.append(name)
                    continue

                error = await self._resume(db, intent, device)
                await intents_service.record_attempt(intent, error=error)
                if error is None:
                    out.resumed.append(name)
                    self._resume_log.append((now, name))
                    logger.info(
                        "Resumed inference automatically",
                        device=name,
                        device_id=str(intent.device_id),
                        models=[e.get("model_id") for e in (intent.models or [])],
                    )
                else:
                    out.failed.append(name)
                    if is_parked(intent):
                        out.parked.append(name)
                    logger.warning(
                        "Auto-resume failed",
                        device=name,
                        device_id=str(intent.device_id),
                        consecutive_failures=intent.consecutive_failures,
                        error=error,
                    )

            await db.commit()

        self._trim_resume_log(now)
        return out

    # -- helpers -----------------------------------------------------------

    async def _running_device_ids(self, db: AsyncSession) -> set[UUID]:
        rows = await db.execute(
            select(StreamSession.device_id).where(
                StreamSession.state.in_(RUNNING_STATES)
            )
        )
        return {r for r in rows.scalars().all() if r is not None}

    async def _vas_state_map(self, devices: list[Device]) -> dict[UUID, "VasState"]:
        """VAS's current view of each camera: video, and whether it exists.

        One call per cycle, already needed for the video check, so
        refreshing `enabled` from it costs nothing extra. `video_live`
        uses VAS's measured `video_state` rather than its stream state:
        the stream state records intent and stayed "live" for a camera
        that had been unreachable for an hour.

        A camera missing from the VAS list entirely leaves `enabled` as
        None — unknown, not False. Deleting a camera from VAS and VAS
        failing to list it look the same from here, and the second must
        not silently stop inference.
        """
        vas_devices = await self._vas.get_devices()
        by_vas_id = {str(getattr(d, "id", "")): d for d in vas_devices}
        out: dict[UUID, VasState] = {}
        for device in devices:
            vas_device = by_vas_id.get(str(getattr(device, "vas_device_id", "")))
            if vas_device is None:
                out[device.id] = VasState(video_live=False, enabled=None, is_active=None)
                continue
            video_state = getattr(vas_device, "video_state", None)
            out[device.id] = VasState(
                video_live=(video_state == "live"),
                enabled=getattr(vas_device, "enabled", None),
                is_active=getattr(vas_device, "is_active", None),
            )
        return out

    async def _stop(self, db: AsyncSession, device: Device) -> None:
        """Stop a disabled camera's session. Best effort."""
        try:
            await self._stream_service_for(db).stop_inference(device.id)
            logger.info("Stopped inference on a disabled camera", device=device.name)
        except Exception as e:
            logger.warning(
                "Could not stop inference on a disabled camera",
                device=device.name, error=str(e),
            )

    async def _resume(
        self, db: AsyncSession, intent: DeviceInferenceIntent, device: Device
    ) -> Optional[str]:
        """Start the desired models. Returns an error string, or None."""
        entries = list(intent.models or [])
        if not entries:
            return "desired active but no models recorded"
        try:
            stream_service = self._stream_service_for(db)
            first = entries[0]
            session = await stream_service.start_stream(
                device.id,
                model_id=first["model_id"],
                model_version=first.get("model_version"),
                inference_fps=intent.inference_fps or 10,
                confidence_threshold=intent.confidence_threshold or 0.7,
                model_config=first.get("config"),
            )
            # Restore the full list, not just the first model. start_stream
            # only knows about one; the session is multi-model.
            session.models = entries
            session.models_revision = (session.models_revision or 0) + 1
            await db.flush()
            return None
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    def _trim_resume_log(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=24)
        self._resume_log = [(t, n) for t, n in self._resume_log if t >= cutoff]

    def resumes_last_24h(self) -> list[dict[str, str]]:
        now = datetime.now(timezone.utc)
        self._trim_resume_log(now)
        return [
            {"camera": name, "at": t.isoformat()}
            for t, name in sorted(self._resume_log, reverse=True)
        ]


_reconciler: Optional[InferenceReconciler] = None


def get_reconciler() -> Optional[InferenceReconciler]:
    return _reconciler


def set_reconciler(value: Optional[InferenceReconciler]) -> None:
    global _reconciler
    _reconciler = value

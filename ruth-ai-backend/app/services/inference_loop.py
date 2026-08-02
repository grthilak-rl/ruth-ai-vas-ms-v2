"""
Inference Loop Service

Runs continuous AI inference on active stream sessions.
This is the missing component that connects:
- VAS (frame source)
- AI Runtime (inference engine)
- Violations (result storage)

Architecture:
- Main loop runs in a background asyncio task
- For each active session, fetch a frame and run inference
- If violation detected, create a violation record
- Respects inference_fps setting per session

Usage:
    loop = InferenceLoopService(
        runtime_router=router,
        violation_service=violation_service,
        db_session_factory=get_db,
    )

    # Start the loop (background task)
    await loop.start()

    # Stop gracefully
    await loop.stop()
"""

import asyncio
import base64
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, Optional
from uuid import UUID

from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Device, StreamSession, StreamState, Violation, ViolationStatus
from app.models.enums import is_known_violation_type, resolve_violation_type
from app.integrations.unified_runtime.router import RuntimeRouter
from app.integrations.vas import VASClient

logger = get_logger(__name__)


def _normalize_bbox(bbox: Any) -> Optional[Dict[str, int]]:
    """Normalize a model bbox into the documented {x, y, width, height} shape.

    Models report corner coordinates as ``[x1, y1, x2, y2]`` in the pixel
    space of the inferenced frame. The API contract (and the review overlay)
    expect top-left plus extent, so convert once here at persistence time
    rather than teaching every consumer both shapes.

    Args:
        bbox: Raw bbox from the model. Accepts ``[x1, y1, x2, y2]`` or an
            already-normalized dict.

    Returns:
        Dict with int x/y/width/height, or None if the input is unusable.
    """
    if isinstance(bbox, dict):
        if {"x", "y", "width", "height"} <= bbox.keys():
            return {
                "x": int(bbox["x"]),
                "y": int(bbox["y"]),
                "width": int(bbox["width"]),
                "height": int(bbox["height"]),
            }
        return None

    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None

    try:
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None

    # Corners may arrive in either order; normalize so extents stay positive.
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))

    return {
        "x": int(round(left)),
        "y": int(round(top)),
        "width": int(round(right - left)),
        "height": int(round(bottom - top)),
    }


# ---------------------------------------------------------------------------
# GPU budget
# ---------------------------------------------------------------------------
# Inference is GPU-bound and the GPU is shared by every active camera, so a
# fixed per-camera fps is not something we can promise: measured fall_detection
# runs ~94ms and ppe_detection ~295ms, meaning one 3090 sustains roughly 10
# fall inferences/sec in total. Ask 7 cameras for 2fps each and demand (14/sec)
# exceeds supply; the loop would fall further behind on every camera and the
# frames it did inference would be increasingly stale.
#
# So per-camera fps is derived, not configured: cameras get the target rate
# when the GPU has room, and an equal share of capacity when it doesn't. Adding
# a camera slows every camera a little instead of overcommitting the GPU.
TARGET_FPS = float(os.getenv("RUTH_INFERENCE_TARGET_FPS", "2.0"))
MIN_FPS = float(os.getenv("RUTH_INFERENCE_MIN_FPS", "0.2"))
# Kept at 2 deliberately: raising it to 3 was measured and rejected, moving
# aggregate throughput only 5.43 -> 5.60 inferences/sec (+3%) because the GPU
# is already the binding constraint here.
#
# An earlier version of this comment also blamed the bump for a "session
# handling race" in the violation-write path. That was wrong. The
# "This Session's transaction has been rolled back" errors were not a race and
# had nothing to do with concurrency — each call already gets its own session.
# They were an invalid enum value failing the insert, with the real cause
# masked by the hand-driven session generator. Both are fixed (see _db() and
# VIOLATION_TYPE_MAP); the value stays at 2 purely on the throughput evidence.
INFERENCE_CONCURRENCY = int(os.getenv("RUTH_INFERENCE_CONCURRENCY", "2"))

# Occupancy ceiling the scheduler aims for.
#
# This is deliberately > 1.0, which needs explaining. record_latency() times
# the whole submit_inference round trip — frame fetch, base64, HTTP to the
# runtime, and only then the GPU — so the "latency" the budget divides by is
# roughly 2.4x actual GPU time (measured: ~200ms round trip vs ~83ms
# fall_detection inference). Treating that as GPU occupancy made the loop pace
# to a real GPU utilisation of 0.42 when it believed it was at 0.85, costing
# about half the achievable throughput.
#
# Raising the ceiling compensates. Measured on this deployment: at 1.7 the
# 4-camera set reached 1.5fps (fall) with real GPU occupancy of only 0.66, so
# the round trip is ~283ms against ~83ms of GPU — a ratio of ~3.4x rather than
# the 2.4x first estimated. 2.3 buys the full 2fps target and lands real GPU
# occupancy near 0.88. It is safe for the value to exceed 1.0 precisely
# because the divisor is not GPU time — sessions waiting on HTTP overlap with
# sessions on the GPU.
#
# Overshooting is self-correcting rather than dangerous: saturating the GPU
# raises measured latency, which feeds the EWMA and pulls the allocated fps
# back down on the next iteration.
#
# This is the quick knob, not the correct fix. The correct fix is to time only
# the runtime call so this number means what its name says; then this drops
# back to ~0.85. Tracked as a follow-up.
MAX_GPU_UTILIZATION = float(os.getenv("RUTH_INFERENCE_MAX_GPU_UTIL", "2.3"))

# Until a model has been measured, assume the slower of the two known models
# so early iterations under-schedule rather than overcommit.
DEFAULT_LATENCY_S = 0.3
LATENCY_EWMA_ALPHA = 0.3


class InferenceBudget:
    """Shares finite GPU capacity across the active inference sessions.

    Tracks how long each model actually takes and hands out a per-iteration
    sleep interval that keeps aggregate GPU demand under MAX_GPU_UTILIZATION.
    Degradation is graceful and automatic: with few cameras everyone gets
    TARGET_FPS, and as cameras are added each one's rate falls until it reaches
    MIN_FPS — a floor, so a saturated system still makes progress on every
    camera rather than starving some completely.
    """

    def __init__(self) -> None:
        self._active: set = set()
        self._latency_s: Dict[str, float] = {}

    def register(self, session_id: UUID) -> None:
        self._active.add(session_id)

    def unregister(self, session_id: UUID) -> None:
        self._active.discard(session_id)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def record_latency(self, model_id: str, seconds: float) -> None:
        """Fold one observed inference duration into the model's EWMA."""
        previous = self._latency_s.get(model_id)
        if previous is None:
            self._latency_s[model_id] = seconds
        else:
            self._latency_s[model_id] = (
                LATENCY_EWMA_ALPHA * seconds
                + (1 - LATENCY_EWMA_ALPHA) * previous
            )

    def latency_for(self, model_id: str) -> float:
        return self._latency_s.get(model_id, DEFAULT_LATENCY_S)

    def fps_for(self, model_id: str) -> float:
        """Per-camera fps this model can sustain given current contention."""
        n = max(1, self.active_count)
        latency = self.latency_for(model_id)
        if latency <= 0:
            return TARGET_FPS
        # Each inference occupies the GPU for `latency`, and n cameras share
        # it, so the fair share per camera is util / (n * latency).
        fair_share_fps = MAX_GPU_UTILIZATION / (n * latency)
        return max(MIN_FPS, min(TARGET_FPS, fair_share_fps))

    def interval_for(self, model_id: str) -> float:
        """Seconds to wait between inferences for one camera."""
        return 1.0 / self.fps_for(model_id)


class InferenceLoopService:
    """
    Background service that runs inference on active streams.

    This service:
    1. Monitors all active stream sessions
    2. For each session, periodically fetches frames and runs inference
    3. Creates violations when detections occur
    4. Handles errors gracefully without stopping the loop
    """

    def __init__(
        self,
        runtime_router: RuntimeRouter,
        vas_client: VASClient,
        db_session_factory: Callable[[], AsyncSession],
        loop_interval: float = 0.5,  # Check for new sessions every 500ms
    ):
        """
        Initialize inference loop service.

        Args:
            runtime_router: Router for AI inference
            vas_client: VAS client for frame fetching
            db_session_factory: Factory to create DB sessions
            loop_interval: How often to check for active sessions
        """
        self._runtime_router = runtime_router
        self._vas_client = vas_client
        self._db_session_factory = db_session_factory
        self._loop_interval = loop_interval

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._session_tasks: Dict[UUID, asyncio.Task] = {}  # session_id -> task

        # Violation debouncing state per session
        # Tracks: last violation state, last violation time, active zones with violations
        self._violation_state: Dict[UUID, Dict[str, Any]] = {}  # session_id -> state
        self._violation_cooldown_seconds = 30  # Minimum seconds between violations for same zone

        # GPU budget shared by every session task. The semaphore bounds how many
        # inferences are in flight so a burst of sessions can't queue work
        # faster than the GPU drains it; the budget derives each session's pace.
        self._budget = InferenceBudget()
        self._gpu_slots = asyncio.Semaphore(INFERENCE_CONCURRENCY)

        # session_id -> device_id, so a cancelled session can drop its
        # device's detections (the cancel path has no device_id otherwise).
        self._session_devices: Dict[UUID, UUID] = {}

        # Newest detection result per device, for browser overlays to read.
        # Bounded by definition: one entry per device, overwritten in place,
        # and dropped when the device's session stops.
        self._latest_detections: Dict[UUID, Dict[str, Any]] = {}

        # VAS stream-state cache populated by VASEventConsumer.
        # Maps stream_id/room_id (string) -> "active" | "paused".
        self._vas_stream_state: Dict[str, str] = {}

    async def activate(self, stream_id: str) -> None:
        """Mark a VAS stream as active (called by VASEventConsumer).

        Today this is a notification-only entry point: it records that VAS
        has started producing frames for `stream_id`. The inference loop
        still picks up work from StreamSession DB rows; this method does
        NOT auto-create sessions.
        """
        self._vas_stream_state[stream_id] = "active"
        logger.info("VAS stream marked active", stream_id=stream_id)

    async def pause(self, stream_id: str) -> None:
        """Mark a VAS stream as paused/stopped (called by VASEventConsumer)."""
        self._vas_stream_state[stream_id] = "paused"
        logger.info("VAS stream marked paused", stream_id=stream_id)

    def vas_stream_is_paused(self, stream_id: str) -> bool:
        """True only when VAS has explicitly reported this stream as paused.

        Returns False when the cache has no entry for the stream (unknown
        state). This is deliberate: VAS does not publish events on the
        start-stream reconnect path, so an absent cache entry should not
        gate inference. If VAS isn't actually producing, the snapshot
        fetch will fail loudly — more useful than a silent skip.
        """
        return self._vas_stream_state.get(stream_id) == "paused"

    async def start(self) -> None:
        """Start the inference loop as a background task."""
        if self._running:
            logger.warning("Inference loop already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._main_loop())
        logger.info("Inference loop started")

    async def stop(self) -> None:
        """Stop the inference loop gracefully."""
        self._running = False

        # Cancel all session tasks
        for session_id, task in self._session_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.debug(f"Cancelled inference task for session {session_id}")

        self._session_tasks.clear()

        # Cancel main loop task
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Inference loop stopped")

    async def _main_loop(self) -> None:
        """Main loop that monitors active sessions."""
        while self._running:
            try:
                async with self._db() as db:
                    # Get all LIVE sessions
                    stmt = select(StreamSession).where(
                        StreamSession.state == StreamState.LIVE
                    )
                    result = await db.execute(stmt)
                    active_sessions = list(result.scalars().all())

                    # Start tasks for new sessions
                    active_session_ids = {s.id for s in active_sessions}
                    for session in active_sessions:
                        if session.id not in self._session_tasks:
                            self._start_session_task(session)

                    # Stop tasks for sessions that are no longer active
                    for session_id in list(self._session_tasks.keys()):
                        if session_id not in active_session_ids:
                            self._stop_session_task(session_id)

            except Exception as e:
                logger.error(f"Error in inference main loop: {e}", exc_info=True)

            await asyncio.sleep(self._loop_interval)

    def _start_session_task(self, session: StreamSession) -> None:
        """Start inference task for a session."""
        task = asyncio.create_task(
            self._inference_task(
                session_id=session.id,
                device_id=session.device_id,
                vas_stream_id=session.vas_stream_id,
                model_id=session.model_id,
                model_version=session.model_version,
                model_config=session.model_config,
                inference_fps=session.inference_fps or 5,
                confidence_threshold=session.confidence_threshold or 0.7,
            )
        )
        self._session_tasks[session.id] = task
        self._session_devices[session.id] = session.device_id
        logger.info(
            "Started inference task",
            session_id=str(session.id),
            model_id=session.model_id,
            fps=session.inference_fps,
        )

    def _stop_session_task(self, session_id: UUID) -> None:
        """Stop inference task for a session."""
        if session_id in self._session_tasks:
            task = self._session_tasks.pop(session_id)
            task.cancel()
            # Free this session's share of the GPU budget so the remaining
            # cameras immediately re-pace to the larger slice available.
            self._budget.unregister(session_id)
            # Drop the device's last detection. Without this, turning a model
            # off would leave its final result readable forever and browsers
            # would keep drawing ghost boxes over a camera with no active
            # model. Cancellation skips the task's own exit path, so this is
            # the only place the toggle-off case gets cleaned up.
            device_id = self._session_devices.pop(session_id, None)
            if device_id is not None:
                self._latest_detections.pop(device_id, None)
            logger.info("Stopped inference task", session_id=str(session_id))

    async def _inference_task(
        self,
        session_id: UUID,
        device_id: UUID,
        vas_stream_id: Optional[str],
        model_id: str,
        model_version: Optional[str],
        model_config: Optional[Dict[str, Any]],
        inference_fps: int,
        confidence_threshold: float,
    ) -> None:
        """
        Run continuous inference for a single session.

        Args:
            session_id: Stream session UUID
            device_id: Device UUID
            vas_stream_id: VAS stream ID for frame fetching
            model_id: AI model to run
            model_version: Model version
            model_config: Model-specific config (zones, thresholds, etc.)
            inference_fps: Target FPS for inference
            confidence_threshold: Minimum confidence for detections
        """
        consecutive_errors = 0
        max_consecutive_errors = 10

        # The session's configured inference_fps is now an upper bound, not a
        # promise: the budget hands out the achievable rate given how many
        # cameras are sharing the GPU. Interval is recomputed every iteration
        # so sessions starting or stopping re-pace the survivors immediately.
        self._budget.register(session_id)
        interval = self._budget.interval_for(model_id)

        logger.info(
            "Starting inference task",
            session_id=str(session_id),
            model_id=model_id,
            config=model_config,
            requested_fps=inference_fps,
            scheduled_fps=round(self._budget.fps_for(model_id), 2),
            active_sessions=self._budget.active_count,
        )

        while self._running and session_id in self._session_tasks:
            try:
                start_time = asyncio.get_event_loop().time()

                # Skip inference only when VAS has explicitly reported this
                # stream as paused/stopped/crashed. Unknown state proceeds —
                # snapshot fetch will fail loudly if VAS isn't producing.
                # We use device_id as the key because the VAS supervisor publishes
                # stream_id == room_id == device_id (the same UUID).
                if self.vas_stream_is_paused(str(device_id)):
                    logger.debug(
                        "Skipping inference — VAS stream paused",
                        stream_id=str(device_id),
                    )
                    await asyncio.sleep(interval)
                    continue

                # Skip if no VAS stream ID
                if not vas_stream_id:
                    logger.warning(
                        "No VAS stream ID for session",
                        session_id=str(session_id),
                    )
                    await asyncio.sleep(interval)
                    continue

                # Submit inference via runtime router. The semaphore caps how
                # many inferences are in flight across all sessions; the timing
                # around it feeds the budget so pacing tracks what the GPU is
                # actually delivering rather than a number we guessed.
                async with self._gpu_slots:
                    inference_started = asyncio.get_event_loop().time()
                    result = await self._runtime_router.submit_inference(
                        model_id=model_id,
                        stream_id=UUID(vas_stream_id) if vas_stream_id else session_id,
                        device_id=device_id,
                        model_version=model_version,
                        timestamp=datetime.now(timezone.utc),
                        priority=5,
                        metadata={"session_id": str(session_id)},
                        config=model_config,
                    )
                    self._budget.record_latency(
                        model_id,
                        asyncio.get_event_loop().time() - inference_started,
                    )

                # Check for violations with debouncing
                if result.get("status") == "success" and result.get("result"):
                    # Frame was actually inferenced and we got a usable result —
                    # count it. (Failed/empty results don't count.)
                    await self._increment_session_counter(session_id, "frames_processed")

                    inference_result = result["result"]
                    violation_detected = inference_result.get("violation_detected", False)
                    confidence = inference_result.get("confidence", 0.0)

                    # Publish for browser overlays. Freshest-wins, one entry per
                    # device, so this is a fixed-size dict rather than a stream:
                    # nobody wants a detection from 10 seconds ago, and writing
                    # ~2/sec/camera to Postgres would be pure write
                    # amplification for data that is stale within 500ms.
                    self._latest_detections[device_id] = {
                        "device_id": str(device_id),
                        "model_id": model_id,
                        "model_version": result.get("model_version"),
                        "result": inference_result,
                        # Coordinate reference. Bounding boxes are only
                        # meaningful against the frame they were computed on,
                        # so the frame geometry travels with them.
                        "frame_width": result.get("frame_width"),
                        "frame_height": result.get("frame_height"),
                        "captured_at": asyncio.get_event_loop().time(),
                    }

                    # Get or initialize session violation state
                    if session_id not in self._violation_state:
                        self._violation_state[session_id] = {
                            "was_in_violation": False,
                            "last_violation_time": None,
                            "active_zones": set(),
                        }
                    state = self._violation_state[session_id]

                    if violation_detected and confidence >= confidence_threshold:
                        # Get the zone ID from detections
                        detections = inference_result.get("detections", [])
                        current_zones = {d.get("zone_id") for d in detections if d.get("in_zone")}

                        # Check if this is a NEW violation (wasn't in violation before, or new zone)
                        new_zones = current_zones - state["active_zones"]
                        now = datetime.now(timezone.utc)

                        should_create = False
                        if not state["was_in_violation"]:
                            # First time entering violation state
                            should_create = True
                            logger.info("New violation: person entered restricted zone",
                                       session_id=str(session_id), zones=list(current_zones))
                        elif new_zones:
                            # Person entered a new zone they weren't in before
                            should_create = True
                            logger.info("New violation: person entered additional zone",
                                       session_id=str(session_id), new_zones=list(new_zones))
                        elif state["last_violation_time"]:
                            # Check cooldown - only create new violation after cooldown period
                            elapsed = (now - state["last_violation_time"]).total_seconds()
                            if elapsed >= self._violation_cooldown_seconds:
                                # Cooldown expired, but person still in zone - don't create new violation
                                # This prevents flooding. Only create when they RE-ENTER after leaving.
                                pass

                        if should_create:
                            await self._create_violation(
                                session_id=session_id,
                                device_id=device_id,
                                model_id=model_id,
                                model_version=result.get("model_version", "1.0.0"),
                                inference_result=inference_result,
                                vas_stream_id=vas_stream_id,
                                frame_width=result.get("frame_width"),
                                frame_height=result.get("frame_height"),
                            )
                            state["last_violation_time"] = now

                        # Update state
                        state["was_in_violation"] = True
                        state["active_zones"] = current_zones
                    else:
                        # No violation - person left the zone
                        if state["was_in_violation"]:
                            logger.info("Violation cleared: person left restricted zone",
                                       session_id=str(session_id))
                        state["was_in_violation"] = False
                        state["active_zones"] = set()

                # Reset error counter on success
                consecutive_errors = 0

                # Re-derive the pace from the budget every iteration, so a
                # camera starting or stopping (or a model turning out slower
                # than assumed) immediately re-paces this session too.
                interval = self._budget.interval_for(model_id)

                # Sleep the remainder of the interval. When the GPU is
                # saturated, elapsed already exceeds interval and this is 0 —
                # the loop simply runs as fast as the GPU allows instead of
                # queueing work it cannot keep up with.
                elapsed = asyncio.get_event_loop().time() - start_time
                sleep_time = max(0, interval - elapsed)
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                logger.info(
                    "Inference task cancelled",
                    session_id=str(session_id),
                )
                break

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    f"Inference error (attempt {consecutive_errors}): {e}",
                    session_id=str(session_id),
                    exc_info=True,
                )

                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        "Max consecutive errors reached, stopping task",
                        session_id=str(session_id),
                    )
                    break

                # Exponential backoff on errors.
                #
                # This used to need a 5s floor: fetching a frame meant asking
                # VAS to create a snapshot, which opened a fresh RTSP
                # connection to the camera, and retrying quickly stacked
                # concurrent connections on a camera that was already
                # struggling — a self-sustaining cascade.
                #
                # Reading the frame tap has no such coupling. A miss means the
                # file isn't there or is stale, which costs one cheap HTTP GET
                # and touches neither the camera nor the live pipeline, so the
                # long floor is no longer warranted. A modest floor remains so
                # a genuinely dead stream isn't polled in a tight loop.
                backoff = min(max(1.0, interval * (2 ** consecutive_errors)), 15)
                await asyncio.sleep(backoff)

        # Natural exit (loop condition false, or the error threshold tripped).
        # Cancellation is handled in _stop_session_task, which unregisters
        # there because a cancelled task never reaches this line.
        self._budget.unregister(session_id)

        # Drop our own entry so _main_loop can revive this session.
        #
        # Without this, a task that tripped max_consecutive_errors was dead
        # permanently: the coroutine returned but its entry stayed in
        # _session_tasks, and _main_loop only starts tasks for sessions NOT in
        # that dict. A transient burst — VAS restarting, a camera blipping,
        # the frame tap not yet warm after a stream restart — therefore ended
        # inference for that camera until the whole service was restarted,
        # even though the session stayed LIVE and healthy.
        #
        # Removing the entry lets the next _main_loop pass (every 500ms) spawn
        # a fresh task, matching the auto-recovery the stream and producer
        # paths already have. This does not spin on a genuinely dead camera:
        # reaching the ceiling costs 10 attempts with 1s-doubling backoff
        # capped at 15s, so each retry cycle is ~100s rather than a hot loop.
        #
        # pop(..., None) because _stop_session_task may have removed it first.
        self._session_tasks.pop(session_id, None)
        self._session_devices.pop(session_id, None)
        self._latest_detections.pop(device_id, None)

    def _db(self):
        """A DB session whose rollback path actually runs on failure.

        The factory is an async generator with the right semantics already:

            try:     yield session; await session.commit()
            except:  await session.rollback(); raise
            finally: await session.close()

        but driving it by hand — ``db = await gen.__anext__()`` then advancing
        it again in a ``finally`` — never throws the exception INTO the
        generator, so that ``except`` branch was unreachable. A failed flush
        left the session needing rollback, the ``finally`` resumed the
        generator at ``await session.commit()``, and SQLAlchemy raised
        PendingRollbackError — which is what got logged, MASKING the real
        error behind "This Session's transaction has been rolled back".

        asynccontextmanager's __aexit__ calls athrow(), so the generator sees
        the exception, rolls back, and the original error propagates intact.
        """
        return asynccontextmanager(self._db_session_factory)()

    def get_latest_detection(self, device_id: UUID) -> Optional[Dict[str, Any]]:
        """Newest detection result for a device, or None if there isn't one.

        Returns a copy with ``age_ms`` filled in, so callers can decide for
        themselves whether a result is too old to draw rather than having that
        policy baked in here.
        """
        entry = self._latest_detections.get(device_id)
        if entry is None:
            return None

        age_ms = int(
            (asyncio.get_event_loop().time() - entry["captured_at"]) * 1000
        )
        payload = {k: v for k, v in entry.items() if k != "captured_at"}
        payload["age_ms"] = age_ms
        return payload

    async def _increment_session_counter(
        self,
        session_id: UUID,
        column_name: str,
    ) -> None:
        """Atomic +1 on a stream_sessions counter column.

        Uses ``UPDATE ... SET col = col + 1`` so concurrent ticks on the
        same session can't lose updates. Failures are logged at debug
        level and swallowed — counters are a monitoring signal, never a
        reason to break the inference loop.

        Args:
            session_id: stream_sessions.id to increment.
            column_name: one of "frames_processed" / "events_count" /
                "violations_count". The column attribute is resolved on
                StreamSession so a typo fails fast in tests.
        """
        try:
            column = getattr(StreamSession, column_name)
        except AttributeError:
            logger.warning(
                "Unknown stream_session counter column",
                column_name=column_name,
            )
            return

        try:
            async with self._db() as db:
                await db.execute(
                    update(StreamSession)
                    .where(StreamSession.id == session_id)
                    .values({column_name: column + 1})
                )
                await db.commit()
        except Exception as e:
            # Counter is observational; never break the inference loop for it.
            logger.debug(
                "Failed to increment stream_session counter",
                session_id=str(session_id),
                column_name=column_name,
                error=str(e),
            )

    async def _create_violation(
        self,
        session_id: UUID,
        device_id: UUID,
        model_id: str,
        model_version: str,
        inference_result: Dict[str, Any],
        vas_stream_id: Optional[str] = None,
        frame_width: Optional[int] = None,
        frame_height: Optional[int] = None,
    ) -> None:
        """
        Create a violation record from inference result with evidence capture.

        Args:
            session_id: Stream session UUID
            device_id: Device UUID
            model_id: AI model that detected violation
            model_version: Model version
            inference_result: Full inference result
            vas_stream_id: VAS stream ID for snapshot capture
            frame_width: Width of the inferenced frame (for overlay mapping)
            frame_height: Height of the inferenced frame (for overlay mapping)
        """
        try:
            async with self._db() as db:
                # Get device name
                stmt = select(Device).where(Device.id == device_id)
                result = await db.execute(stmt)
                device = result.scalar_one_or_none()
                camera_name = device.name if device else "Unknown"

                # Extract detection details.
                #
                # `or model_id` rather than a dict default: models emit an
                # explicit "violation_type": None (fall_detection does), which
                # .get(key, default) would pass straight through as None.
                raw_violation_type = inference_result.get("violation_type") or model_id
                violation_enum, violation_detail = resolve_violation_type(raw_violation_type)

                if not is_known_violation_type(raw_violation_type):
                    # Loud, because this is how the next unmapped model value
                    # announces itself. It no longer costs us the row — the
                    # violation is stored under a generic type with the raw
                    # string in type_detail — but it does need a human to add
                    # it to VIOLATION_TYPE_MAP.
                    logger.warning(
                        "Unmapped violation_type from model — stored under fallback type. "
                        "Add it to VIOLATION_TYPE_MAP.",
                        raw_violation_type=raw_violation_type,
                        model_id=model_id,
                        fallback_type=violation_enum.value,
                        device_id=str(device_id),
                    )

                # Keep the model's own string for labelling and evidence, so
                # the specific value survives in bounding_boxes[].label too.
                violation_type = raw_violation_type
                confidence = inference_result.get("confidence", 0.0)
                detections = inference_result.get("detections", [])

                # Extract bounding boxes from detections.
                #
                # Stored as {x, y, width, height, label, confidence} plus the
                # dimensions of the frame they were computed against — the
                # shape the violation detail overlay renders. The snapshot
                # image is left untouched (clean raw frame for training).
                bounding_boxes = []
                for det in detections:
                    if det.get("in_zone", False) or det.get("bbox"):
                        box = _normalize_bbox(det.get("bbox"))
                        if box is None:
                            continue
                        box.update({
                            "confidence": det.get("confidence", 0.0),
                            "label": det.get("zone_id") or violation_type,
                        })
                        if frame_width and frame_height:
                            box["frame_width"] = frame_width
                            box["frame_height"] = frame_height
                        bounding_boxes.append(box)

                # Create violation
                violation = Violation(
                    device_id=device_id,
                    stream_session_id=session_id,
                    type=violation_enum,
                    type_detail=violation_detail,
                    status=ViolationStatus.OPEN,  # New violations start as OPEN
                    confidence=confidence,
                    timestamp=datetime.now(timezone.utc),
                    camera_name=camera_name,
                    model_id=model_id,
                    model_version=model_version,
                    bounding_boxes=bounding_boxes,
                )

                db.add(violation)
                await db.commit()
                await db.refresh(violation)

                logger.info(
                    "Created violation",
                    violation_id=str(violation.id),
                    type=violation_type,
                    confidence=confidence,
                    device_id=str(device_id),
                    model_id=model_id,
                )

                # Bump the session's running total. Best-effort —
                # see _increment_session_counter for failure semantics.
                await self._increment_session_counter(session_id, "violations_count")

                # Capture snapshot evidence asynchronously
                if vas_stream_id:
                    asyncio.create_task(
                        self._capture_violation_evidence(
                            violation_id=violation.id,
                            vas_stream_id=vas_stream_id,
                            violation_type=violation_type,
                        )
                    )

        except Exception as e:
            logger.error(
                f"Failed to create violation: {e}",
                session_id=str(session_id),
                exc_info=True,
            )

    async def _capture_violation_evidence(
        self,
        violation_id: UUID,
        vas_stream_id: str,
        violation_type: str,
    ) -> None:
        """
        Capture snapshot evidence for a violation asynchronously.

        Args:
            violation_id: Violation UUID to attach evidence to
            vas_stream_id: VAS stream ID to capture from
            violation_type: Type of violation for labeling
        """
        from app.models import Evidence, EvidenceType, EvidenceStatus
        from app.integrations.vas.models import SnapshotCreateRequest

        try:
            # Create snapshot via VAS
            snapshot_request = SnapshotCreateRequest(
                created_by=f"ruth-ai-{violation_type}",
                metadata={"violation_type": violation_type},
            )
            snapshot = await self._vas_client.create_snapshot(
                stream_id=vas_stream_id,
                request=snapshot_request,
            )

            if not snapshot:
                logger.warning(
                    "Failed to create snapshot for violation evidence",
                    violation_id=str(violation_id),
                )
                return

            async with self._db() as db:
                evidence = Evidence(
                    violation_id=violation_id,
                    evidence_type=EvidenceType.SNAPSHOT,
                    status=EvidenceStatus.READY,
                    vas_snapshot_id=snapshot.id,
                    requested_at=datetime.now(timezone.utc),
                    ready_at=datetime.now(timezone.utc),
                )

                db.add(evidence)
                await db.commit()

                logger.info(
                    "Captured violation evidence",
                    violation_id=str(violation_id),
                    snapshot_id=snapshot.id,
                )

        except Exception as e:
            logger.error(
                f"Failed to capture violation evidence: {e}",
                violation_id=str(violation_id),
                exc_info=True,
            )


# Global instance (initialized in main.py startup)
_inference_loop: Optional[InferenceLoopService] = None


def get_inference_loop() -> Optional[InferenceLoopService]:
    """Get the global inference loop instance."""
    return _inference_loop


def set_inference_loop(loop: InferenceLoopService) -> None:
    """Set the global inference loop instance."""
    global _inference_loop
    _inference_loop = loop

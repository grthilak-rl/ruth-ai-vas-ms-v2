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

    # Multi-model sessions register one consumer per (session, model) rather
    # than one per session, so active_count counts every model stream sharing
    # the GPU. With no multi-model session, consumers == sessions and the
    # single-model pacing above is exactly what it was.

    def fps_for_consumer(self, model_id: str, desired_fps: float) -> float:
        """fps for one model on a multi-model camera, capped at what it asks for.

        Same fair-share rule as fps_for, but the cap is the model's own desired
        rate (recommended_fps or a per-camera override) instead of TARGET_FPS.
        MIN_FPS is a floor on the *schedule*, not a guarantee: see the module
        notes on saturation.
        """
        n = max(1, self.active_count)
        latency = self.latency_for(model_id)
        if latency <= 0:
            return desired_fps
        fair_share_fps = MAX_GPU_UTILIZATION / (n * latency)
        return max(MIN_FPS, min(desired_fps, fair_share_fps))


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

        # --- Multi-model sessions (stream_sessions.models) -------------------
        # Sessions whose `models` is NULL never touch any of this: they run
        # _inference_task exactly as before.
        #
        # Per-session task bookkeeping:
        #   {"kind": "legacy"|"multi", "revision": int|None, "model_id": str}
        self._task_meta: Dict[UUID, Dict[str, Any]] = {}
        # Sessions whose task is being swapped right now; _main_loop skips them
        # so it can't start a second task in the middle of the handover.
        self._handovers: set = set()
        # Violation writes in progress per session. A handover cancels the old
        # task only when this is 0, i.e. never between a violation's commit and
        # the duplicate-suppression state update that follows it.
        self._violation_writes: Dict[UUID, int] = {}
        # Duplicate-suppression state per (session_id, model_id).
        self._model_violation_state: Dict[tuple, Dict[str, Any]] = {}
        # Newest result per (device_id, model_id). The session's first model is
        # also published to _latest_detections, so /detections/latest keeps
        # working for every camera.
        self._latest_model_detections: Dict[tuple, Dict[str, Any]] = {}
        # Cooperative stop for multi-model tasks: a handover sets the event
        # and the task exits after finishing its current tick, so no DB write
        # or inference is ever cancelled half-way.
        self._task_stop: Dict[UUID, asyncio.Event] = {}

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
        # Iterate a snapshot: each cancelled task's own exit cleanup removes
        # its entry from _session_tasks, which would otherwise raise
        # "dictionary changed size during iteration" and skip cancelling the
        # main loop below.
        for session_id, task in list(self._session_tasks.items()):
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
                        if session.id in self._handovers:
                            continue
                        if session.id not in self._session_tasks:
                            if session.models is None:
                                self._start_session_task(session)
                                self._task_meta[session.id] = {
                                    "kind": "legacy",
                                    "revision": None,
                                    "model_id": session.model_id,
                                }
                            else:
                                self._start_multi_task(session)
                        elif session.models is not None and self._needs_handover(session):
                            self._handovers.add(session.id)
                            asyncio.create_task(self._handover(session))

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
                self._clear_model_detections(device_id)
            self._task_meta.pop(session_id, None)
            self._task_stop.pop(session_id, None)
            self._clear_model_violation_state(session_id)
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

    def get_latest_detections(self, device_id: UUID) -> list[Dict[str, Any]]:
        """Newest result per model for a device (multi-model aware).

        A multi-model session returns one entry per model that has produced a
        result; a legacy session returns its single entry; none -> [].
        """
        now = asyncio.get_event_loop().time()
        entries = [
            entry
            for (dev, _model), entry in self._latest_model_detections.items()
            if dev == device_id
        ]
        if not entries and device_id in self._latest_detections:
            entries = [self._latest_detections[device_id]]
        out = []
        for entry in entries:
            payload = {k: v for k, v in entry.items() if k != "captured_at"}
            payload["age_ms"] = int((now - entry["captured_at"]) * 1000)
            out.append(payload)
        return sorted(out, key=lambda p: p["model_id"])

    # =========================================================================
    # Multi-model sessions
    # =========================================================================
    #
    # A session whose `models` column is set (even with one entry) runs
    # _multi_inference_task: per tick it reads the frame tap ONCE and runs only
    # the models that are due, each on its own interval (fps_override, else the
    # model's recommended_fps capped at TARGET_FPS, then the GPU budget).
    #
    # Sessions with models = NULL run _inference_task, unchanged. The only path
    # between the two is legacy -> multi, when a model is added to a legacy
    # session; a multi session stays multi (also at 1 model), and every change
    # to its list or entries bumps models_revision, which restarts its task
    # with the new configuration through the same handover.

    # Run a model that is due within this fraction of its interval on the
    # current tick, so slower models ride on faster models' frame reads.
    _DUE_TOLERANCE = 0.25
    _MAX_TICK_ERRORS = 10
    _STOP_TIMEOUT = 10.0

    @staticmethod
    async def _sleep_unless_stopped(stop: asyncio.Event, seconds: float) -> None:
        if seconds <= 0 or stop.is_set():
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    @staticmethod
    def _entries(session: StreamSession) -> list[Dict[str, Any]]:
        return [dict(e) for e in (session.models or []) if e.get("model_id")]

    def _needs_handover(self, session: StreamSession) -> bool:
        meta = self._task_meta.get(session.id)
        if meta is None or meta["kind"] == "legacy":
            return True
        return meta["revision"] != session.models_revision

    def _multi_interval(self, entry: Dict[str, Any]) -> float:
        from app.services.model_rates import desired_fps

        fps = self._budget.fps_for_consumer(
            entry["model_id"], desired_fps(entry, TARGET_FPS)
        )
        return 1.0 / fps

    def _clear_model_detections(self, device_id: UUID, keep: Optional[set] = None) -> None:
        for key in [k for k in self._latest_model_detections if k[0] == device_id]:
            if keep is None or key[1] not in keep:
                del self._latest_model_detections[key]

    def _clear_model_violation_state(self, session_id: UUID, keep: Optional[set] = None) -> None:
        for key in [k for k in self._model_violation_state if k[0] == session_id]:
            if keep is None or key[1] not in keep:
                del self._model_violation_state[key]

    def _start_multi_task(self, session: StreamSession) -> None:
        entries = self._entries(session)
        stop = asyncio.Event()
        self._task_stop[session.id] = stop
        task = asyncio.create_task(
            self._multi_inference_task(
                session_id=session.id,
                device_id=session.device_id,
                vas_stream_id=session.vas_stream_id,
                entries=entries,
                confidence_threshold=session.confidence_threshold or 0.7,
                stop=stop,
            )
        )
        self._session_tasks[session.id] = task
        self._session_devices[session.id] = session.device_id
        self._task_meta[session.id] = {
            "kind": "multi",
            "revision": session.models_revision,
            "model_id": entries[0]["model_id"] if entries else session.model_id,
        }
        logger.info(
            "Started multi-model inference task",
            session_id=str(session.id),
            models=[e["model_id"] for e in entries],
            revision=session.models_revision,
        )

    async def _handover(self, session: StreamSession) -> None:
        """Swap a session's task for one matching its current models.

        Ordering guarantees:
          - no double run: the old task has fully exited (cleanup included)
            before the new one is created, and _main_loop skips the session
            meanwhile;
          - no duplicate violation: the old task is cancelled only when no
            violation write is in flight, and duplicate-suppression state is
            carried over per model;
          - no gap: the new task runs its first tick immediately, and the last
            detections are restored so overlays don't blink.
        """
        session_id = session.id
        device_id = session.device_id
        try:
            old_task = self._session_tasks.get(session_id)
            old_meta = self._task_meta.get(session_id) or {}
            saved_device = self._latest_detections.get(device_id)
            saved_models = {
                k: v for k, v in self._latest_model_detections.items() if k[0] == device_id
            }

            if old_task is not None and not old_task.done():
                stop = self._task_stop.get(session_id)
                if old_meta.get("kind") == "multi" and stop is not None:
                    # Cooperative: the old task finishes its current tick
                    # (inference, detections, violation writes) and exits.
                    stop.set()
                    finished, _ = await asyncio.wait({old_task}, timeout=self._STOP_TIMEOUT)
                    if not finished:  # safety net only; logged
                        logger.warning("Multi-model task did not stop in time; cancelling",
                                       session_id=str(session_id))
                        old_task.cancel()
                        await asyncio.wait({old_task})
                else:
                    # Legacy task (unmodified code, no stop hook): cancel at a
                    # safe point, never between a violation's commit and the
                    # duplicate-suppression update that follows it. No await
                    # between the check and cancel().
                    while self._violation_writes.get(session_id, 0) > 0:
                        await asyncio.sleep(0.005)
                    old_task.cancel()
                    await asyncio.wait({old_task})

            entries = self._entries(session)
            model_ids = {e["model_id"] for e in entries}

            # Carry duplicate-suppression state across the swap.
            if old_meta.get("kind") == "legacy":
                legacy_state = self._violation_state.get(session_id)
                legacy_model = old_meta.get("model_id")
                if legacy_state is not None and legacy_model in model_ids:
                    self._model_violation_state[(session_id, legacy_model)] = {
                        "was_in_violation": legacy_state["was_in_violation"],
                        "last_violation_time": legacy_state["last_violation_time"],
                        "active_zones": set(legacy_state["active_zones"]),
                    }
            self._clear_model_violation_state(session_id, keep=model_ids)

            if not self._running or not entries:
                return

            # Install the new task (synchronously: nothing can interleave).
            self._start_multi_task(session)

            # Restore detections the old task's cleanup dropped, for models
            # that are still running, so overlays carry on seamlessly.
            for key, value in saved_models.items():
                if key[1] in model_ids:
                    self._latest_model_detections.setdefault(key, value)
            if saved_device is not None and saved_device.get("model_id") in model_ids:
                if (device_id, saved_device["model_id"]) not in self._latest_model_detections:
                    self._latest_model_detections[(device_id, saved_device["model_id"])] = saved_device
            primary = entries[0]["model_id"]
            primary_entry = self._latest_model_detections.get((device_id, primary))
            if primary_entry is not None:
                self._latest_detections.setdefault(device_id, primary_entry)

            logger.info(
                "Handed over inference task",
                session_id=str(session_id),
                from_kind=old_meta.get("kind"),
                from_revision=old_meta.get("revision"),
                to_revision=session.models_revision,
                models=sorted(model_ids),
            )
        except Exception as e:  # pragma: no cover - logged, _main_loop retries
            logger.error(f"Inference task handover failed: {e}", session_id=str(session_id), exc_info=True)
        finally:
            self._handovers.discard(session_id)

    async def _run_model(
        self,
        session_id: UUID,
        device_id: UUID,
        vas_stream_id: str,
        entry: Dict[str, Any],
        frame: Any,
        fetch_seconds: float,
    ) -> Dict[str, Any]:
        """One model on the shared frame, under the GPU-concurrency semaphore."""
        clock = asyncio.get_event_loop().time
        async with self._gpu_slots:
            started = clock()
            result = await self._runtime_router.submit_inference_with_frame(
                model_id=entry["model_id"],
                frame_data=frame,
                stream_id=UUID(vas_stream_id),
                device_id=device_id,
                model_version=entry.get("model_version"),
                timestamp=datetime.now(timezone.utc),
                priority=5,
                metadata={"session_id": str(session_id)},
                config=entry.get("config"),
            )
            # Same accounting as single-model sessions: the budget's latency
            # includes the frame fetch (see MAX_GPU_UTILIZATION).
            self._budget.record_latency(entry["model_id"], fetch_seconds + clock() - started)
        return result

    async def _process_model_result(
        self,
        session_id: UUID,
        device_id: UUID,
        vas_stream_id: str,
        model_id: str,
        is_primary: bool,
        result: Dict[str, Any],
        confidence_threshold: float,
    ) -> None:
        """Publish one model's result and apply the violation rules.

        The violation rules are the single-model loop's, verbatim, with the
        state keyed by (session, model) instead of session.
        """
        if not (result.get("status") == "success" and result.get("result")):
            return
        await self._increment_session_counter(session_id, "frames_processed")

        inference_result = result["result"]
        entry = {
            "device_id": str(device_id),
            "model_id": model_id,
            "model_version": result.get("model_version"),
            "result": inference_result,
            "frame_width": result.get("frame_width"),
            "frame_height": result.get("frame_height"),
            "captured_at": asyncio.get_event_loop().time(),
        }
        self._latest_model_detections[(device_id, model_id)] = entry
        if is_primary:
            self._latest_detections[device_id] = entry

        key = (session_id, model_id)
        state = self._model_violation_state.setdefault(
            key,
            {"was_in_violation": False, "last_violation_time": None, "active_zones": set()},
        )
        violation_detected = inference_result.get("violation_detected", False)
        confidence = inference_result.get("confidence", 0.0)

        if violation_detected and confidence >= confidence_threshold:
            detections = inference_result.get("detections", [])
            current_zones = {d.get("zone_id") for d in detections if d.get("in_zone")}
            new_zones = current_zones - state["active_zones"]
            if not state["was_in_violation"] or new_zones:
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
                state["last_violation_time"] = datetime.now(timezone.utc)
            state["was_in_violation"] = True
            state["active_zones"] = current_zones
        else:
            state["was_in_violation"] = False
            state["active_zones"] = set()

    async def _multi_inference_task(
        self,
        session_id: UUID,
        device_id: UUID,
        vas_stream_id: Optional[str],
        entries: list[Dict[str, Any]],
        confidence_threshold: float,
        stop: Optional[asyncio.Event] = None,
    ) -> None:
        """Run several models on one camera, one frame-tap read per tick."""
        stop = stop or asyncio.Event()
        me = asyncio.current_task()
        clock = asyncio.get_event_loop().time
        model_ids = [e["model_id"] for e in entries]
        primary = model_ids[0] if model_ids else None
        consumers = [(session_id, m) for m in model_ids]
        for consumer in consumers:
            self._budget.register(consumer)
        next_due = {m: clock() for m in model_ids}
        model_errors = {m: 0 for m in model_ids}
        tick_errors = 0

        try:
            while (
                entries
                and self._running
                and not stop.is_set()
                and self._session_tasks.get(session_id) is me
            ):
                now = clock()
                intervals = {e["model_id"]: self._multi_interval(e) for e in entries}
                due = [
                    e for e in entries
                    if next_due[e["model_id"]] - now
                    <= self._DUE_TOLERANCE * intervals[e["model_id"]]
                ]
                if not due:
                    await self._sleep_unless_stopped(stop, min(next_due.values()) - now)
                    continue

                if self.vas_stream_is_paused(str(device_id)) or not vas_stream_id:
                    if not vas_stream_id:
                        logger.warning("No VAS stream ID for session", session_id=str(session_id))
                    for e in due:
                        next_due[e["model_id"]] = now + intervals[e["model_id"]]
                    await self._sleep_unless_stopped(stop, min(intervals[e["model_id"]] for e in due))
                    continue

                # One frame-tap read for every model due on this tick.
                try:
                    fetch_started = clock()
                    frame = await self._runtime_router.fetch_frame(
                        stream_id=UUID(vas_stream_id), device_id=device_id
                    )
                    fetch_seconds = clock() - fetch_started
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    tick_errors += 1
                    logger.error(
                        f"Frame fetch failed (attempt {tick_errors}): {e}",
                        session_id=str(session_id),
                    )
                    if tick_errors >= self._MAX_TICK_ERRORS:
                        logger.error("Max consecutive errors reached, stopping task", session_id=str(session_id))
                        break
                    backoff = min(max(1.0, min(intervals.values()) * (2 ** tick_errors)), 15)
                    for e in due:
                        next_due[e["model_id"]] = now + backoff
                    await self._sleep_unless_stopped(stop, backoff)
                    continue
                tick_errors = 0

                outcomes = await asyncio.gather(
                    *(
                        self._run_model(session_id, device_id, vas_stream_id, e, frame, fetch_seconds)
                        for e in due
                    ),
                    return_exceptions=True,
                )
                succeeded = []
                for e, outcome in zip(due, outcomes):
                    m = e["model_id"]
                    if isinstance(outcome, BaseException):
                        if isinstance(outcome, asyncio.CancelledError):
                            raise outcome
                        model_errors[m] += 1
                        logger.error(
                            f"Inference error (attempt {model_errors[m]}): {outcome}",
                            session_id=str(session_id),
                            model_id=m,
                        )
                        # Back off this model only; the others keep running.
                        next_due[m] = now + min(max(1.0, intervals[m] * (2 ** model_errors[m])), 15)
                        continue
                    model_errors[m] = 0
                    next_due[m] = now + intervals[m]
                    succeeded.append((m, outcome))

                # Each model's results (detections, violation write) are
                # independent, so process them concurrently: one model's
                # violation write must not delay the camera's other models.
                processed = await asyncio.gather(
                    *(
                        self._process_model_result(
                            session_id, device_id, vas_stream_id, m, m == primary, outcome, confidence_threshold
                        )
                        for m, outcome in succeeded
                    ),
                    return_exceptions=True,
                )
                for (m, _), failure in zip(succeeded, processed):
                    if isinstance(failure, asyncio.CancelledError):
                        raise failure
                    if isinstance(failure, BaseException):
                        logger.error(
                            f"Result processing failed: {failure}",
                            session_id=str(session_id),
                            model_id=m,
                        )

                await self._sleep_unless_stopped(stop, min(next_due.values()) - clock())
        finally:
            for consumer in consumers:
                self._budget.unregister(consumer)
            # Only clean up if this task is still the session's task; a
            # handover installs the replacement only after this has run.
            if self._task_stop.get(session_id) is stop:
                self._task_stop.pop(session_id, None)
            if self._session_tasks.get(session_id) is me:
                self._session_tasks.pop(session_id, None)
                self._task_meta.pop(session_id, None)
                self._session_devices.pop(session_id, None)
                self._latest_detections.pop(device_id, None)
                self._clear_model_detections(device_id)

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
        # Marks "a violation write is in progress" for this session; a
        # multi-model handover waits for it to drop to 0 before cancelling the
        # old task (see _handover). No effect on what gets written.
        self._violation_writes[session_id] = self._violation_writes.get(session_id, 0) + 1
        try:
            await self._create_violation_unguarded(
                session_id=session_id,
                device_id=device_id,
                model_id=model_id,
                model_version=model_version,
                inference_result=inference_result,
                vas_stream_id=vas_stream_id,
                frame_width=frame_width,
                frame_height=frame_height,
            )
        finally:
            remaining = self._violation_writes.get(session_id, 1) - 1
            if remaining > 0:
                self._violation_writes[session_id] = remaining
            else:
                self._violation_writes.pop(session_id, None)

    async def _create_violation_unguarded(
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
        """Body of _create_violation (unchanged); call _create_violation instead."""
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

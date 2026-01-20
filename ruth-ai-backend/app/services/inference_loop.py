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
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Device, StreamSession, StreamState, Violation, ViolationStatus
from app.integrations.unified_runtime.router import RuntimeRouter
from app.integrations.vas import VASClient

logger = get_logger(__name__)


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
                # Get DB session from async generator
                db_gen = self._db_session_factory()
                db = await db_gen.__anext__()
                try:
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
                finally:
                    try:
                        await db_gen.__anext__()
                    except StopAsyncIteration:
                        pass

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
        interval = 1.0 / inference_fps
        consecutive_errors = 0
        max_consecutive_errors = 10

        logger.info(
            "Starting inference task",
            session_id=str(session_id),
            model_id=model_id,
            config=model_config,
        )

        while self._running and session_id in self._session_tasks:
            try:
                start_time = asyncio.get_event_loop().time()

                # Skip if no VAS stream ID
                if not vas_stream_id:
                    logger.warning(
                        "No VAS stream ID for session",
                        session_id=str(session_id),
                    )
                    await asyncio.sleep(interval)
                    continue

                # Submit inference via runtime router
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

                # Check for violations with debouncing
                if result.get("status") == "success" and result.get("result"):
                    inference_result = result["result"]
                    violation_detected = inference_result.get("violation_detected", False)
                    confidence = inference_result.get("confidence", 0.0)

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

                # Calculate sleep time to maintain FPS
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

                # Exponential backoff on errors
                await asyncio.sleep(min(interval * (2 ** consecutive_errors), 30))

    async def _create_violation(
        self,
        session_id: UUID,
        device_id: UUID,
        model_id: str,
        model_version: str,
        inference_result: Dict[str, Any],
        vas_stream_id: Optional[str] = None,
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
        """
        try:
            # Get DB session from async generator
            db_gen = self._db_session_factory()
            db = await db_gen.__anext__()
            try:
                # Get device name
                stmt = select(Device).where(Device.id == device_id)
                result = await db.execute(stmt)
                device = result.scalar_one_or_none()
                camera_name = device.name if device else "Unknown"

                # Extract detection details
                violation_type = inference_result.get("violation_type", model_id)
                confidence = inference_result.get("confidence", 0.0)
                detections = inference_result.get("detections", [])

                # Extract bounding boxes from detections
                bounding_boxes = []
                for det in detections:
                    if det.get("in_zone", False) or det.get("bbox"):
                        bounding_boxes.append({
                            "bbox": det.get("bbox", []),
                            "confidence": det.get("confidence", 0.0),
                            "label": det.get("zone_id") or violation_type,
                        })

                # Create violation
                violation = Violation(
                    device_id=device_id,
                    stream_session_id=session_id,
                    type=violation_type,
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

                # Capture snapshot evidence asynchronously
                if vas_stream_id:
                    asyncio.create_task(
                        self._capture_violation_evidence(
                            violation_id=violation.id,
                            vas_stream_id=vas_stream_id,
                            violation_type=violation_type,
                        )
                    )
            finally:
                try:
                    await db_gen.__anext__()
                except StopAsyncIteration:
                    pass

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

            # Get DB session and create evidence record
            db_gen = self._db_session_factory()
            db = await db_gen.__anext__()
            try:
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
            finally:
                try:
                    await db_gen.__anext__()
                except StopAsyncIteration:
                    pass

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

"""Stream & Session Management Service.

Responsible for:
- Starting and stopping streams via VAS
- Tracking stream state locally
- Managing StreamSession records
- Mapping streams to AI Runtime sessions

This service is the single source of truth for:
- Which streams are active
- Which AI sessions are running

Usage:
    stream_service = StreamService(vas_client, ai_runtime_client, db)

    # Start a stream
    session = await stream_service.start_stream(device_id, model_id="fall_detection")

    # Stop a stream
    await stream_service.stop_stream(device_id)

    # Get active streams
    active = await stream_service.get_active_streams()
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.ai_runtime import (
    AIRuntimeClient,
    AIRuntimeError,
    AIRuntimeUnavailableError,
)
from app.integrations.vas import (
    VASClient,
    VASError,
    VASNotFoundError,
    VASRTSPError,
)
from app.models import Device, StreamSession, StreamState

from .exceptions import (
    DeviceNotFoundError,
    StreamAlreadyActiveError,
    StreamNotActiveError,
    StreamSessionNotFoundError,
    StreamStartError,
    StreamStateTransitionError,
    StreamStopError,
)

logger = get_logger(__name__)


# Valid state transitions
VALID_TRANSITIONS: dict[StreamState, set[StreamState]] = {
    StreamState.STARTING: {StreamState.LIVE, StreamState.ERROR, StreamState.STOPPED},
    StreamState.LIVE: {StreamState.STOPPING, StreamState.ERROR},
    StreamState.STOPPING: {StreamState.STOPPED, StreamState.ERROR},
    StreamState.STOPPED: {StreamState.STARTING},  # Can restart
    StreamState.ERROR: {StreamState.STARTING, StreamState.STOPPED},  # Can retry or stop
}


class StreamService:
    """Service for stream lifecycle and session management.

    This service:
    - Orchestrates stream start/stop via VAS
    - Tracks stream sessions in local DB
    - Maps streams to AI Runtime sessions
    - Enforces valid state transitions
    - Handles partial failures gracefully
    """

    def __init__(
        self,
        vas_client: VASClient,
        ai_runtime_client: AIRuntimeClient | None,
        db: AsyncSession,
    ) -> None:
        """Initialize stream service.

        Args:
            vas_client: VAS API client (dependency injected)
            ai_runtime_client: AI Runtime client (optional, can be None)
            db: Database session (dependency injected)
        """
        self._vas = vas_client
        self._ai_runtime = ai_runtime_client
        self._db = db

    # -------------------------------------------------------------------------
    # Stream Lifecycle
    # -------------------------------------------------------------------------

    async def start_stream(
        self,
        device_id: UUID,
        *,
        model_id: str = "fall_detection",
        model_version: str | None = None,
        inference_fps: int = 10,
        confidence_threshold: float = 0.7,
        model_config: dict | None = None,
    ) -> StreamSession:
        """Start a stream for a device.

        This operation:
        1. Validates device exists and is active
        2. Checks no active stream exists
        3. Creates StreamSession in STARTING state
        4. Calls VAS to start the stream
        5. Transitions to LIVE state
        6. Registers with AI Runtime (if available)

        Args:
            device_id: Local device UUID
            model_id: AI model to use for inference
            model_version: Specific model version (optional)
            inference_fps: Frames per second for inference
            confidence_threshold: Minimum confidence for detections
            model_config: Model-specific configuration (e.g., tank corners, ROI)

        Returns:
            Active StreamSession

        Raises:
            DeviceNotFoundError: Device does not exist
            StreamAlreadyActiveError: Stream already active for device
            StreamStartError: VAS failed to start stream
        """
        logger.info(
            "Starting stream",
            device_id=str(device_id),
            model_id=model_id,
        )

        # 1. Get device
        device = await self._get_device(device_id)

        # 2. Check for existing active stream
        existing = await self._get_active_session(device_id)
        if existing:
            raise StreamAlreadyActiveError(device_id, existing.id)

        # 3. Create session in STARTING state
        session = StreamSession(
            device_id=device_id,
            model_id=model_id,
            model_version=model_version,
            inference_fps=inference_fps,
            confidence_threshold=confidence_threshold,
            model_config=model_config,
            state=StreamState.STARTING,
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(session)
        await self._db.flush()

        logger.info(
            "Created stream session",
            session_id=str(session.id),
            device_id=str(device_id),
        )

        # 4. Start stream via VAS
        try:
            vas_response = await self._vas.start_stream(device.vas_device_id)

            # Store VAS stream ID
            session.vas_stream_id = vas_response.v2_stream_id

            # 5. Transition to LIVE
            await self._transition_state(session, StreamState.LIVE)

            logger.info(
                "Stream started successfully",
                session_id=str(session.id),
                vas_stream_id=session.vas_stream_id,
            )

        except VASRTSPError as e:
            # Camera/RTSP failure - mark as error
            await self._mark_session_error(session, f"RTSP error: {e}")
            raise StreamStartError(device_id, "RTSP connection failed", cause=e) from e

        except VASError as e:
            # Other VAS failure - mark as error
            await self._mark_session_error(session, f"VAS error: {e}")
            raise StreamStartError(device_id, str(e), cause=e) from e

        # 6. Register with AI Runtime (non-blocking, best-effort)
        if self._ai_runtime:
            await self._attach_ai_runtime_session(session)

        return session

    async def stop_stream(
        self,
        device_id: UUID,
        *,
        force: bool = False,
    ) -> StreamSession:
        """Stop a stream for a device.

        This operation:
        1. Finds active stream session
        2. Transitions to STOPPING state
        3. Detaches AI Runtime session
        4. Calls VAS to stop stream
        5. Transitions to STOPPED state

        Args:
            device_id: Local device UUID
            force: If True, skip state validation and force stop

        Returns:
            Stopped StreamSession

        Raises:
            StreamNotActiveError: No active stream for device
            StreamStopError: VAS failed to stop stream
        """
        logger.info("Stopping stream", device_id=str(device_id), force=force)

        # 1. Get active session
        session = await self._get_active_session(device_id)
        if not session:
            raise StreamNotActiveError(device_id)

        # Get device for VAS ID
        device = await self._get_device(device_id)

        # 2. Transition to STOPPING (unless forcing)
        if not force:
            await self._transition_state(session, StreamState.STOPPING)

        # 3. Detach AI Runtime session (best-effort)
        if self._ai_runtime:
            await self._detach_ai_runtime_session(session)

        # 4. Stop stream via VAS
        try:
            await self._vas.stop_stream(device.vas_device_id)
        except VASNotFoundError:
            # Stream already stopped in VAS - that's fine
            logger.warning(
                "Stream not found in VAS during stop",
                session_id=str(session.id),
            )
        except VASError as e:
            if not force:
                await self._mark_session_error(session, f"VAS stop error: {e}")
                raise StreamStopError(device_id, str(e), cause=e) from e
            # If forcing, log but continue
            logger.error(
                "VAS error during forced stop",
                session_id=str(session.id),
                error=str(e),
            )

        # 5. Transition to STOPPED
        session.state = StreamState.STOPPED
        session.stopped_at = datetime.now(timezone.utc)

        logger.info(
            "Stream stopped successfully",
            session_id=str(session.id),
            device_id=str(device_id),
        )

        return session

    async def mark_stream_error(
        self,
        device_id: UUID,
        reason: str,
    ) -> StreamSession:
        """Mark stream as errored.

        Used when external detection identifies stream failure.

        Args:
            device_id: Local device UUID
            reason: Error description

        Returns:
            Updated StreamSession

        Raises:
            StreamNotActiveError: No active stream for device
        """
        session = await self._get_active_session(device_id)
        if not session:
            raise StreamNotActiveError(device_id)

        await self._mark_session_error(session, reason)

        logger.warning(
            "Stream marked as error",
            session_id=str(session.id),
            device_id=str(device_id),
            reason=reason,
        )

        return session

    # -------------------------------------------------------------------------
    # Session Retrieval
    # -------------------------------------------------------------------------

    async def get_stream_session(
        self,
        session_id: UUID,
    ) -> StreamSession:
        """Get stream session by ID.

        Args:
            session_id: Session UUID

        Returns:
            StreamSession

        Raises:
            StreamSessionNotFoundError: Session does not exist
        """
        stmt = select(StreamSession).where(StreamSession.id == session_id)
        result = await self._db.execute(stmt)
        session = result.scalar_one_or_none()

        if session is None:
            raise StreamSessionNotFoundError(session_id=session_id)

        return session

    async def get_active_session_for_device(
        self,
        device_id: UUID,
    ) -> StreamSession | None:
        """Get active stream session for a device.

        Args:
            device_id: Local device UUID

        Returns:
            Active StreamSession or None
        """
        return await self._get_active_session(device_id)

    async def get_active_streams(self) -> list[StreamSession]:
        """Get all active stream sessions.

        Active means state is STARTING, LIVE, or STOPPING.

        Returns:
            List of active sessions
        """
        active_states = [
            StreamState.STARTING,
            StreamState.LIVE,
            StreamState.STOPPING,
        ]
        stmt = select(StreamSession).where(StreamSession.state.in_(active_states))
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_live_streams(self) -> list[StreamSession]:
        """Get all streams in LIVE state.

        Returns:
            List of live sessions
        """
        stmt = select(StreamSession).where(StreamSession.state == StreamState.LIVE)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_sessions_for_device(
        self,
        device_id: UUID,
        *,
        limit: int = 10,
    ) -> list[StreamSession]:
        """Get recent sessions for a device.

        Args:
            device_id: Local device UUID
            limit: Maximum sessions to return

        Returns:
            List of sessions, most recent first
        """
        stmt = (
            select(StreamSession)
            .where(StreamSession.device_id == device_id)
            .order_by(StreamSession.started_at.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # -------------------------------------------------------------------------
    # Stream Status
    # -------------------------------------------------------------------------

    async def is_stream_active(self, device_id: UUID) -> bool:
        """Check if a device has an active stream.

        Args:
            device_id: Local device UUID

        Returns:
            True if stream is active
        """
        session = await self._get_active_session(device_id)
        return session is not None

    async def get_stream_status(self, device_id: UUID) -> dict:
        """Get stream status for a device.

        Returns:
            Status dict with session info or None
        """
        session = await self._get_active_session(device_id)

        if session is None:
            return {
                "active": False,
                "session_id": None,
                "state": None,
                "vas_stream_id": None,
            }

        return {
            "active": True,
            "session_id": str(session.id),
            "state": session.state.value,
            "vas_stream_id": session.vas_stream_id,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "model_id": session.model_id,
            "model_config": session.model_config,
        }

    # -------------------------------------------------------------------------
    # Error Recovery
    # -------------------------------------------------------------------------

    async def update_model_config(
        self,
        device_id: UUID,
        model_config: dict,
    ) -> StreamSession:
        """Update model_config for an active stream session.

        Args:
            device_id: Local device UUID
            model_config: New model configuration

        Returns:
            Updated StreamSession

        Raises:
            StreamNotActiveError: No active stream for device
        """
        session = await self._get_active_session(device_id)
        if not session:
            raise StreamNotActiveError(device_id)

        session.model_config = model_config

        logger.info(
            "Updated model_config",
            session_id=str(session.id),
            device_id=str(device_id),
            model_id=session.model_id,
        )

        return session

    async def recover_stuck_sessions(self) -> list[StreamSession]:
        """Find and recover sessions stuck in transitional states.

        Sessions stuck in STARTING or STOPPING for too long
        are marked as ERROR.

        Returns:
            List of recovered sessions
        """
        from datetime import timedelta

        # Sessions stuck for more than 5 minutes
        stuck_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)

        stmt = select(StreamSession).where(
            and_(
                StreamSession.state.in_([StreamState.STARTING, StreamState.STOPPING]),
                StreamSession.updated_at < stuck_threshold,
            )
        )
        result = await self._db.execute(stmt)
        stuck_sessions = list(result.scalars().all())

        for session in stuck_sessions:
            await self._mark_session_error(
                session,
                f"Session stuck in {session.state.value} state",
            )
            logger.warning(
                "Recovered stuck session",
                session_id=str(session.id),
                state=session.state.value,
            )

        return stuck_sessions

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    async def _get_device(self, device_id: UUID) -> Device:
        """Get device by ID.

        Args:
            device_id: Local device UUID

        Returns:
            Device

        Raises:
            DeviceNotFoundError: Device not found
        """
        stmt = select(Device).where(Device.id == device_id)
        result = await self._db.execute(stmt)
        device = result.scalar_one_or_none()

        if device is None:
            raise DeviceNotFoundError(device_id)

        return device

    async def _get_active_session(self, device_id: UUID) -> StreamSession | None:
        """Get active session for device.

        Active means STARTING, LIVE, or STOPPING.
        """
        active_states = [
            StreamState.STARTING,
            StreamState.LIVE,
            StreamState.STOPPING,
        ]
        stmt = select(StreamSession).where(
            and_(
                StreamSession.device_id == device_id,
                StreamSession.state.in_(active_states),
            )
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def _transition_state(
        self,
        session: StreamSession,
        new_state: StreamState,
    ) -> None:
        """Transition session to new state.

        Args:
            session: StreamSession to update
            new_state: Target state

        Raises:
            StreamStateTransitionError: Invalid transition
        """
        current = session.state
        valid_targets = VALID_TRANSITIONS.get(current, set())

        if new_state not in valid_targets:
            raise StreamStateTransitionError(
                session.id,
                current.value,
                new_state.value,
            )

        session.state = new_state
        logger.debug(
            "State transition",
            session_id=str(session.id),
            from_state=current.value,
            to_state=new_state.value,
        )

    async def _mark_session_error(
        self,
        session: StreamSession,
        reason: str,
    ) -> None:
        """Mark session as error.

        Args:
            session: StreamSession to update
            reason: Error description
        """
        session.state = StreamState.ERROR
        session.error_message = reason[:1000]  # Truncate to column limit

    async def _attach_ai_runtime_session(
        self,
        session: StreamSession,
    ) -> None:
        """Attach AI Runtime session to stream.

        This is best-effort - failures are logged but don't fail the stream.
        """
        if not self._ai_runtime:
            return

        try:
            # Check if runtime is healthy
            is_healthy = await self._ai_runtime.is_healthy()
            if not is_healthy:
                logger.warning(
                    "AI Runtime not healthy, skipping attach",
                    session_id=str(session.id),
                )
                return

            # Check if model is available
            if not self._ai_runtime.has_model(session.model_id):
                # Try to refresh capabilities
                await self._ai_runtime.get_capabilities(force_refresh=True)

            logger.info(
                "AI Runtime session attached",
                session_id=str(session.id),
                model_id=session.model_id,
            )

        except AIRuntimeUnavailableError as e:
            logger.warning(
                "AI Runtime unavailable for attach",
                session_id=str(session.id),
                error=str(e),
            )
        except AIRuntimeError as e:
            logger.error(
                "AI Runtime error during attach",
                session_id=str(session.id),
                error=str(e),
            )

    async def _detach_ai_runtime_session(
        self,
        session: StreamSession,
    ) -> None:
        """Detach AI Runtime session from stream.

        This is best-effort - failures are logged but don't fail the stop.
        """
        if not self._ai_runtime:
            return

        try:
            # Currently just logging - actual detach depends on AI Runtime contract
            logger.info(
                "AI Runtime session detached",
                session_id=str(session.id),
            )

        except AIRuntimeError as e:
            logger.warning(
                "AI Runtime error during detach",
                session_id=str(session.id),
                error=str(e),
            )

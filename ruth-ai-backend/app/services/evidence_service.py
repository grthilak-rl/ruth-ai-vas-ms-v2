"""Evidence Orchestration Service.

Responsible for:
- Creating snapshots and bookmarks via VAS APIs
- Tracking evidence lifecycle locally
- Polling VAS for evidence readiness
- Handling failures gracefully

This service is the only authority for evidence creation and lifecycle.

Usage:
    evidence_service = EvidenceService(vas_client, db)

    # Create a snapshot for a violation
    evidence = await evidence_service.create_snapshot(violation)

    # Create a bookmark for a violation
    evidence = await evidence_service.create_bookmark(violation, before_seconds=5, after_seconds=10)

    # Poll until evidence is ready (or timeout)
    ready_evidence = await evidence_service.poll_evidence(evidence.id, timeout=30.0)

    # Get all evidence for a violation
    evidence_list = await evidence_service.get_evidence_for_violation(violation_id)

Design Principles:
    - Evidence creation is idempotent per (violation_id, evidence_type)
    - VAS failures do NOT corrupt local state
    - Polling is explicit and awaitable (no background workers)
    - Terminal states (ready, failed) are immutable
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.vas import (
    Bookmark as VASBookmark,
    BookmarkCreateRequest,
    Snapshot as VASSnapshot,
    SnapshotCreateRequest,
    VASClient,
    VASError,
    VASNotFoundError,
    VASStreamNotLiveError,
    VASTimeoutError,
)
from app.models import (
    Evidence,
    EvidenceStatus,
    EvidenceType,
    Violation,
)

from .exceptions import (
    EvidenceAlreadyExistsError,
    EvidenceCreationError,
    EvidenceNotFoundError,
    EvidencePollingTimeoutError,
    EvidenceStateError,
    EvidenceTerminalStateError,
    EvidenceVASError,
    NoActiveStreamError,
    ViolationNotFoundError,
)

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# State Machine
# -----------------------------------------------------------------------------

# Valid status transitions for evidence
VALID_STATUS_TRANSITIONS: dict[EvidenceStatus, set[EvidenceStatus]] = {
    EvidenceStatus.PENDING: {EvidenceStatus.PROCESSING, EvidenceStatus.FAILED},
    EvidenceStatus.PROCESSING: {EvidenceStatus.READY, EvidenceStatus.FAILED},
    EvidenceStatus.READY: set(),  # Terminal state
    EvidenceStatus.FAILED: set(),  # Terminal state
}

# Terminal states (cannot be modified)
TERMINAL_STATES: set[EvidenceStatus] = {
    EvidenceStatus.READY,
    EvidenceStatus.FAILED,
}

# Default polling configuration
DEFAULT_SNAPSHOT_TIMEOUT = 30.0  # seconds
DEFAULT_BOOKMARK_TIMEOUT = 60.0  # seconds (bookmarks take longer)
DEFAULT_POLL_INTERVAL = 1.0  # seconds


class EvidenceService:
    """Service for evidence orchestration via VAS APIs.

    This service:
    - Creates snapshots and bookmarks through VAS
    - Tracks evidence records locally with status
    - Polls VAS until evidence is ready or failed
    - Enforces idempotency per (violation_id, evidence_type)

    Evidence is NEVER modified after reaching terminal state.
    """

    def __init__(
        self,
        vas_client: VASClient,
        db: AsyncSession,
    ) -> None:
        """Initialize evidence service.

        Args:
            vas_client: VAS API client (dependency injected)
            db: Database session (dependency injected)
        """
        self._vas = vas_client
        self._db = db

    # -------------------------------------------------------------------------
    # Snapshot Creation
    # -------------------------------------------------------------------------

    async def create_snapshot(
        self,
        violation: Violation,
        *,
        created_by: str = "ruth-ai",
        allow_existing: bool = True,
    ) -> Evidence:
        """Create a snapshot for a violation.

        Captures a frame from the VAS stream associated with the violation.

        Args:
            violation: Violation to capture snapshot for
            created_by: Creator identifier for VAS
            allow_existing: If True, return existing snapshot instead of error

        Returns:
            Evidence record (status may be pending, processing, ready, or failed)

        Raises:
            EvidenceAlreadyExistsError: Snapshot already exists (if allow_existing=False)
            NoActiveStreamError: No active VAS stream for capture
            EvidenceCreationError: Failed to create snapshot
        """
        logger.info(
            "Creating snapshot for violation",
            violation_id=str(violation.id),
            device_id=str(violation.device_id),
        )

        # Check for existing snapshot (idempotency)
        existing = await self._get_existing_evidence(
            violation.id,
            EvidenceType.SNAPSHOT,
        )
        if existing:
            if allow_existing:
                logger.debug(
                    "Returning existing snapshot",
                    evidence_id=str(existing.id),
                    status=existing.status.value,
                )
                return existing
            raise EvidenceAlreadyExistsError(
                violation.id,
                EvidenceType.SNAPSHOT.value,
                existing.id,
            )

        # Resolve VAS stream ID
        vas_stream_id = await self._resolve_vas_stream_id(violation)

        # Create evidence record with pending status
        evidence = Evidence(
            violation_id=violation.id,
            evidence_type=EvidenceType.SNAPSHOT,
            status=EvidenceStatus.PENDING,
            requested_at=datetime.now(timezone.utc),
        )
        self._db.add(evidence)
        await self._db.flush()

        logger.info(
            "Created pending snapshot evidence",
            evidence_id=str(evidence.id),
            violation_id=str(violation.id),
        )

        # Trigger VAS snapshot creation
        try:
            vas_snapshot = await self._vas.create_snapshot(
                vas_stream_id,
                SnapshotCreateRequest(
                    source="live",
                    created_by=created_by,
                    metadata={
                        "violation_id": str(violation.id),
                        "device_id": str(violation.device_id),
                    },
                ),
            )

            # Update evidence with VAS ID and transition to processing
            evidence.vas_snapshot_id = vas_snapshot.id
            evidence.status = EvidenceStatus.PROCESSING

            logger.info(
                "VAS snapshot created",
                evidence_id=str(evidence.id),
                vas_snapshot_id=vas_snapshot.id,
            )

        except VASStreamNotLiveError as e:
            await self._mark_evidence_failed(
                evidence,
                f"Stream not live: {e}",
            )
            raise NoActiveStreamError(violation.id, violation.device_id) from e

        except VASError as e:
            await self._mark_evidence_failed(
                evidence,
                f"VAS error: {e}",
            )
            raise EvidenceVASError(
                "Failed to create VAS snapshot",
                evidence_id=evidence.id,
                vas_error=str(e),
                cause=e,
            ) from e

        return evidence

    # -------------------------------------------------------------------------
    # Bookmark Creation
    # -------------------------------------------------------------------------

    async def create_bookmark(
        self,
        violation: Violation,
        *,
        before_seconds: int = 5,
        after_seconds: int = 10,
        created_by: str = "ruth-ai",
        allow_existing: bool = True,
    ) -> Evidence:
        """Create a bookmark (video clip) for a violation.

        Captures a video segment around the violation timestamp.

        Args:
            violation: Violation to capture bookmark for
            before_seconds: Seconds before violation timestamp
            after_seconds: Seconds after violation timestamp
            created_by: Creator identifier for VAS
            allow_existing: If True, return existing bookmark instead of error

        Returns:
            Evidence record (status may be pending, processing, ready, or failed)

        Raises:
            EvidenceAlreadyExistsError: Bookmark already exists (if allow_existing=False)
            NoActiveStreamError: No active VAS stream for capture
            EvidenceCreationError: Failed to create bookmark
        """
        logger.info(
            "Creating bookmark for violation",
            violation_id=str(violation.id),
            device_id=str(violation.device_id),
            before_seconds=before_seconds,
            after_seconds=after_seconds,
        )

        # Check for existing bookmark (idempotency)
        existing = await self._get_existing_evidence(
            violation.id,
            EvidenceType.BOOKMARK,
        )
        if existing:
            if allow_existing:
                logger.debug(
                    "Returning existing bookmark",
                    evidence_id=str(existing.id),
                    status=existing.status.value,
                )
                return existing
            raise EvidenceAlreadyExistsError(
                violation.id,
                EvidenceType.BOOKMARK.value,
                existing.id,
            )

        # Resolve VAS stream ID
        vas_stream_id = await self._resolve_vas_stream_id(violation)

        # Calculate duration
        duration_seconds = before_seconds + after_seconds

        # Create evidence record with pending status
        evidence = Evidence(
            violation_id=violation.id,
            evidence_type=EvidenceType.BOOKMARK,
            status=EvidenceStatus.PENDING,
            requested_at=datetime.now(timezone.utc),
            bookmark_duration_seconds=duration_seconds,
        )
        self._db.add(evidence)
        await self._db.flush()

        logger.info(
            "Created pending bookmark evidence",
            evidence_id=str(evidence.id),
            violation_id=str(violation.id),
        )

        # Trigger VAS bookmark creation
        try:
            vas_bookmark = await self._vas.create_bookmark(
                vas_stream_id,
                BookmarkCreateRequest(
                    source="live",
                    label=f"Violation: {violation.type.value}",
                    event_type=violation.type.value,
                    confidence=violation.confidence,
                    before_seconds=before_seconds,
                    after_seconds=after_seconds,
                    center_timestamp=violation.timestamp,
                    created_by=created_by,
                    metadata={
                        "violation_id": str(violation.id),
                        "device_id": str(violation.device_id),
                    },
                ),
            )

            # Update evidence with VAS ID and transition to processing
            evidence.vas_bookmark_id = vas_bookmark.id
            evidence.status = EvidenceStatus.PROCESSING

            logger.info(
                "VAS bookmark created",
                evidence_id=str(evidence.id),
                vas_bookmark_id=vas_bookmark.id,
            )

        except VASStreamNotLiveError as e:
            await self._mark_evidence_failed(
                evidence,
                f"Stream not live: {e}",
            )
            raise NoActiveStreamError(violation.id, violation.device_id) from e

        except VASError as e:
            await self._mark_evidence_failed(
                evidence,
                f"VAS error: {e}",
            )
            raise EvidenceVASError(
                "Failed to create VAS bookmark",
                evidence_id=evidence.id,
                vas_error=str(e),
                cause=e,
            ) from e

        return evidence

    # -------------------------------------------------------------------------
    # Polling
    # -------------------------------------------------------------------------

    async def poll_evidence(
        self,
        evidence_id: UUID,
        *,
        timeout: float | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> Evidence:
        """Poll VAS until evidence is ready or failed.

        This method blocks until the evidence reaches a terminal state
        (ready or failed) or the timeout is reached.

        Args:
            evidence_id: Evidence UUID
            timeout: Maximum wait time (uses defaults based on type if None)
            poll_interval: Time between status checks

        Returns:
            Evidence in terminal state (ready or failed)

        Raises:
            EvidenceNotFoundError: Evidence does not exist
            EvidencePollingTimeoutError: Timeout waiting for evidence
        """
        evidence = await self.get_evidence_by_id(evidence_id)

        # Already in terminal state
        if evidence.status in TERMINAL_STATES:
            return evidence

        # Determine timeout based on evidence type
        if timeout is None:
            timeout = (
                DEFAULT_BOOKMARK_TIMEOUT
                if evidence.evidence_type == EvidenceType.BOOKMARK
                else DEFAULT_SNAPSHOT_TIMEOUT
            )

        logger.info(
            "Polling evidence status",
            evidence_id=str(evidence_id),
            evidence_type=evidence.evidence_type.value,
            timeout=timeout,
        )

        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            # Refresh evidence from database
            await self._db.refresh(evidence)

            # Check if terminal
            if evidence.status in TERMINAL_STATES:
                logger.info(
                    "Evidence reached terminal state",
                    evidence_id=str(evidence_id),
                    status=evidence.status.value,
                )
                return evidence

            # Poll VAS for status
            try:
                await self._sync_evidence_from_vas(evidence)
            except VASNotFoundError:
                # VAS resource deleted - mark as failed
                await self._mark_evidence_failed(
                    evidence,
                    "VAS resource not found",
                )
                return evidence
            except VASError as e:
                # Log but continue polling - might be transient
                logger.warning(
                    "VAS poll error (will retry)",
                    evidence_id=str(evidence_id),
                    error=str(e),
                )

            # Check terminal state after sync
            if evidence.status in TERMINAL_STATES:
                logger.info(
                    "Evidence reached terminal state after VAS sync",
                    evidence_id=str(evidence_id),
                    status=evidence.status.value,
                )
                return evidence

            await asyncio.sleep(poll_interval)

        # Timeout - mark as failed
        await self._mark_evidence_failed(
            evidence,
            f"Polling timeout after {timeout}s",
        )

        raise EvidencePollingTimeoutError(evidence_id, timeout)

    async def sync_evidence_status(self, evidence: Evidence) -> None:
        """Sync evidence status from VAS.

        Public method for syncing evidence status when fetching violation details.
        This ensures evidence that was captured asynchronously gets its final status.

        Args:
            evidence: Evidence record to sync
        """
        await self._sync_evidence_from_vas(evidence)

    async def _sync_evidence_from_vas(self, evidence: Evidence) -> None:
        """Sync evidence status from VAS.

        Args:
            evidence: Evidence record to sync
        """
        if evidence.evidence_type == EvidenceType.SNAPSHOT:
            await self._sync_snapshot_from_vas(evidence)
        elif evidence.evidence_type == EvidenceType.BOOKMARK:
            await self._sync_bookmark_from_vas(evidence)

    async def _sync_snapshot_from_vas(self, evidence: Evidence) -> None:
        """Sync snapshot status from VAS.

        Args:
            evidence: Snapshot evidence record
        """
        if not evidence.vas_snapshot_id:
            return

        vas_snapshot = await self._vas.get_snapshot(evidence.vas_snapshot_id)

        if vas_snapshot.status:
            if vas_snapshot.status.value == "ready":
                evidence.status = EvidenceStatus.READY
                evidence.ready_at = datetime.now(timezone.utc)
            elif vas_snapshot.status.value == "failed":
                evidence.status = EvidenceStatus.FAILED
                evidence.error_message = vas_snapshot.error or "VAS processing failed"

    async def _sync_bookmark_from_vas(self, evidence: Evidence) -> None:
        """Sync bookmark status from VAS.

        Args:
            evidence: Bookmark evidence record
        """
        if not evidence.vas_bookmark_id:
            return

        vas_bookmark = await self._vas.get_bookmark(evidence.vas_bookmark_id)

        if vas_bookmark.status:
            if vas_bookmark.status.value == "ready":
                evidence.status = EvidenceStatus.READY
                evidence.ready_at = datetime.now(timezone.utc)
            elif vas_bookmark.status.value == "failed":
                evidence.status = EvidenceStatus.FAILED
                evidence.error_message = vas_bookmark.error or "VAS processing failed"

    # -------------------------------------------------------------------------
    # Retrieval
    # -------------------------------------------------------------------------

    async def get_evidence_by_id(self, evidence_id: UUID) -> Evidence:
        """Get evidence by ID.

        Args:
            evidence_id: Evidence UUID

        Returns:
            Evidence record

        Raises:
            EvidenceNotFoundError: Evidence does not exist
        """
        stmt = select(Evidence).where(Evidence.id == evidence_id)
        result = await self._db.execute(stmt)
        evidence = result.scalar_one_or_none()

        if evidence is None:
            raise EvidenceNotFoundError(evidence_id)

        return evidence

    async def get_evidence_for_violation(
        self,
        violation_id: UUID,
        *,
        evidence_type: EvidenceType | None = None,
        status: EvidenceStatus | None = None,
    ) -> list[Evidence]:
        """Get evidence for a violation.

        Args:
            violation_id: Violation UUID
            evidence_type: Filter by type (optional)
            status: Filter by status (optional)

        Returns:
            List of evidence records
        """
        stmt = (
            select(Evidence)
            .where(Evidence.violation_id == violation_id)
            .order_by(Evidence.requested_at.desc())
        )

        if evidence_type is not None:
            stmt = stmt.where(Evidence.evidence_type == evidence_type)

        if status is not None:
            stmt = stmt.where(Evidence.status == status)

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_ready_evidence_for_violation(
        self,
        violation_id: UUID,
    ) -> list[Evidence]:
        """Get all ready evidence for a violation.

        Args:
            violation_id: Violation UUID

        Returns:
            List of ready evidence records
        """
        return await self.get_evidence_for_violation(
            violation_id,
            status=EvidenceStatus.READY,
        )

    async def get_pending_evidence(
        self,
        *,
        limit: int = 100,
    ) -> list[Evidence]:
        """Get all pending/processing evidence.

        Useful for finding evidence that needs polling.

        Args:
            limit: Maximum records to return

        Returns:
            List of non-terminal evidence records
        """
        non_terminal = [EvidenceStatus.PENDING, EvidenceStatus.PROCESSING]

        stmt = (
            select(Evidence)
            .where(Evidence.status.in_(non_terminal))
            .order_by(Evidence.requested_at.asc())
            .limit(limit)
        )

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # -------------------------------------------------------------------------
    # Status Management
    # -------------------------------------------------------------------------

    async def transition_status(
        self,
        evidence_id: UUID,
        new_status: EvidenceStatus,
        *,
        error_message: str | None = None,
    ) -> Evidence:
        """Transition evidence to a new status.

        Enforces valid state transitions.

        Args:
            evidence_id: Evidence UUID
            new_status: Target status
            error_message: Error message (for FAILED status)

        Returns:
            Updated Evidence record

        Raises:
            EvidenceNotFoundError: Evidence does not exist
            EvidenceTerminalStateError: Evidence is in terminal state
            EvidenceStateError: Invalid transition
        """
        evidence = await self.get_evidence_by_id(evidence_id)
        current_status = evidence.status

        logger.info(
            "Transitioning evidence status",
            evidence_id=str(evidence_id),
            current_status=current_status.value,
            new_status=new_status.value,
        )

        # Check terminal state
        if current_status in TERMINAL_STATES:
            raise EvidenceTerminalStateError(evidence_id, current_status.value)

        # Check valid transition
        valid_targets = VALID_STATUS_TRANSITIONS.get(current_status, set())
        if new_status not in valid_targets:
            raise EvidenceStateError(
                evidence_id,
                current_status.value,
                new_status.value,
            )

        # Apply transition
        evidence.status = new_status

        if new_status == EvidenceStatus.READY:
            evidence.ready_at = datetime.now(timezone.utc)

        if new_status == EvidenceStatus.FAILED and error_message:
            evidence.error_message = error_message[:1000]

        logger.info(
            "Evidence status transitioned",
            evidence_id=str(evidence_id),
            from_status=current_status.value,
            to_status=new_status.value,
        )

        return evidence

    # -------------------------------------------------------------------------
    # Retry Support
    # -------------------------------------------------------------------------

    async def retry_failed_evidence(
        self,
        evidence_id: UUID,
        *,
        max_retries: int = 3,
    ) -> Evidence:
        """Retry creating failed evidence.

        Only evidence in FAILED status with retry_count < max_retries can be retried.
        This resets the evidence to PENDING and re-triggers VAS creation.

        Args:
            evidence_id: Evidence UUID
            max_retries: Maximum retry attempts

        Returns:
            Updated Evidence record

        Raises:
            EvidenceNotFoundError: Evidence does not exist
            EvidenceCreationError: Max retries exceeded or retry not allowed
        """
        evidence = await self.get_evidence_by_id(evidence_id)

        if evidence.status != EvidenceStatus.FAILED:
            raise EvidenceCreationError(
                "Only failed evidence can be retried",
                evidence_type=evidence.evidence_type.value,
            )

        if evidence.retry_count >= max_retries:
            raise EvidenceCreationError(
                f"Max retries ({max_retries}) exceeded",
                evidence_type=evidence.evidence_type.value,
            )

        # Get violation for re-creation
        stmt = select(Violation).where(Violation.id == evidence.violation_id)
        result = await self._db.execute(stmt)
        violation = result.scalar_one_or_none()

        if violation is None:
            raise ViolationNotFoundError(evidence.violation_id)

        # Increment retry count
        evidence.retry_count += 1
        evidence.last_retry_at = datetime.now(timezone.utc)
        evidence.error_message = None

        logger.info(
            "Retrying failed evidence",
            evidence_id=str(evidence_id),
            retry_count=evidence.retry_count,
        )

        # Re-trigger VAS creation based on type
        vas_stream_id = await self._resolve_vas_stream_id(violation)

        try:
            if evidence.evidence_type == EvidenceType.SNAPSHOT:
                vas_snapshot = await self._vas.create_snapshot(
                    vas_stream_id,
                    SnapshotCreateRequest(
                        source="live",
                        created_by="ruth-ai",
                        metadata={
                            "violation_id": str(violation.id),
                            "retry": evidence.retry_count,
                        },
                    ),
                )
                evidence.vas_snapshot_id = vas_snapshot.id
                evidence.status = EvidenceStatus.PROCESSING

            elif evidence.evidence_type == EvidenceType.BOOKMARK:
                vas_bookmark = await self._vas.create_bookmark(
                    vas_stream_id,
                    BookmarkCreateRequest(
                        source="live",
                        label=f"Violation: {violation.type.value}",
                        event_type=violation.type.value,
                        confidence=violation.confidence,
                        before_seconds=5,
                        after_seconds=10,
                        center_timestamp=violation.timestamp,
                        created_by="ruth-ai",
                        metadata={
                            "violation_id": str(violation.id),
                            "retry": evidence.retry_count,
                        },
                    ),
                )
                evidence.vas_bookmark_id = vas_bookmark.id
                evidence.status = EvidenceStatus.PROCESSING

        except VASError as e:
            await self._mark_evidence_failed(evidence, f"Retry failed: {e}")
            raise EvidenceVASError(
                "Retry VAS creation failed",
                evidence_id=evidence.id,
                vas_error=str(e),
                cause=e,
            ) from e

        return evidence

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    async def _get_existing_evidence(
        self,
        violation_id: UUID,
        evidence_type: EvidenceType,
    ) -> Evidence | None:
        """Get existing evidence for violation/type combination.

        Args:
            violation_id: Violation UUID
            evidence_type: Type of evidence

        Returns:
            Existing Evidence or None
        """
        stmt = select(Evidence).where(
            and_(
                Evidence.violation_id == violation_id,
                Evidence.evidence_type == evidence_type,
            )
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def _resolve_vas_stream_id(self, violation: Violation) -> str:
        """Resolve VAS stream ID for a violation.

        Uses the violation's stream session if available.

        Args:
            violation: Violation to resolve stream for

        Returns:
            VAS stream ID

        Raises:
            NoActiveStreamError: No active stream for violation
        """
        # Try to get VAS stream ID from stream session
        if violation.stream_session_id:
            from app.models import StreamSession

            stmt = select(StreamSession).where(
                StreamSession.id == violation.stream_session_id
            )
            result = await self._db.execute(stmt)
            session = result.scalar_one_or_none()

            if session and session.vas_stream_id:
                return session.vas_stream_id

        # Fallback: try to find active stream for device
        from app.models import StreamSession, StreamState

        active_states = [StreamState.LIVE, StreamState.STARTING]
        stmt = select(StreamSession).where(
            and_(
                StreamSession.device_id == violation.device_id,
                StreamSession.state.in_(active_states),
            )
        )
        result = await self._db.execute(stmt)
        active_session = result.scalar_one_or_none()

        if active_session and active_session.vas_stream_id:
            return active_session.vas_stream_id

        raise NoActiveStreamError(violation.id, violation.device_id)

    async def _mark_evidence_failed(
        self,
        evidence: Evidence,
        error_message: str,
    ) -> None:
        """Mark evidence as failed.

        Args:
            evidence: Evidence record
            error_message: Error description
        """
        evidence.status = EvidenceStatus.FAILED
        evidence.error_message = error_message[:1000]

        logger.warning(
            "Evidence marked as failed",
            evidence_id=str(evidence.id),
            error=error_message,
        )

    def is_valid_transition(
        self,
        current_status: EvidenceStatus,
        target_status: EvidenceStatus,
    ) -> bool:
        """Check if a status transition is valid.

        Args:
            current_status: Current evidence status
            target_status: Target evidence status

        Returns:
            True if transition is valid
        """
        if current_status in TERMINAL_STATES:
            return False
        valid_targets = VALID_STATUS_TRANSITIONS.get(current_status, set())
        return target_status in valid_targets

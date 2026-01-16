"""Violation Orchestration Service.

Responsible for:
- Creating Violations from actionable Events
- Enforcing violation lifecycle rules
- Preventing duplicate or conflicting violations
- Guaranteeing idempotency across repeated event ingestion
- Triggering evidence capture (snapshots) when violations are created

This service is the single source of truth for violation state.

Usage:
    violation_service = ViolationService(db, evidence_service=evidence_service)

    # Process an event (creates or attaches to violation)
    violation = await violation_service.process_event(event)

    # Get open violation for aggregation check
    open_violation = await violation_service.get_open_violation(
        device_id, session_id, ViolationType.FALL_DETECTED
    )

    # Transition status with enforcement
    violation = await violation_service.transition_status(
        violation_id, ViolationStatus.REVIEWED
    )

Design Principles:
    - Violations are deterministically created from Events
    - Same Event processed multiple times = no duplicate Violations
    - Aggregation: subsequent Events attach to existing open Violation
    - State transitions are enforced (terminal states are immutable)
    - Evidence capture is fire-and-forget (failures don't block violation creation)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Event, EventType, Violation, ViolationStatus, ViolationType

from .exceptions import (
    DuplicateViolationError,
    ViolationCreationError,
    ViolationNotFoundError,
    ViolationStateError,
    ViolationTerminalStateError,
)

if TYPE_CHECKING:
    from .evidence_service import EvidenceService

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# State Machine
# -----------------------------------------------------------------------------

# Valid status transitions
# From API Contract Section 3.2 - ViolationStatus transitions
VALID_STATUS_TRANSITIONS: dict[ViolationStatus, set[ViolationStatus]] = {
    ViolationStatus.OPEN: {ViolationStatus.REVIEWED, ViolationStatus.DISMISSED},
    ViolationStatus.REVIEWED: {ViolationStatus.DISMISSED, ViolationStatus.RESOLVED},
    ViolationStatus.DISMISSED: {ViolationStatus.OPEN},  # Can re-open dismissed
    ViolationStatus.RESOLVED: set(),  # Terminal state - no transitions allowed
}

# Terminal states (cannot be modified)
TERMINAL_STATES: set[ViolationStatus] = {ViolationStatus.RESOLVED}

# States considered "open" for aggregation purposes
OPEN_STATES: set[ViolationStatus] = {
    ViolationStatus.OPEN,
    ViolationStatus.REVIEWED,
}

# Mapping from EventType to ViolationType
EVENT_TYPE_TO_VIOLATION_TYPE: dict[EventType, ViolationType] = {
    EventType.FALL_DETECTED: ViolationType.FALL_DETECTED,
}


class ViolationService:
    """Service for violation orchestration and lifecycle management.

    This service:
    - Creates Violations from actionable Events
    - Enforces aggregation rules (one open violation per device/session/type)
    - Manages violation lifecycle with enforced state transitions
    - Guarantees idempotency (same event = same result)
    - Triggers evidence capture on violation creation (if EvidenceService provided)

    Violations are NEVER duplicated.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        evidence_service: EvidenceService | None = None,
    ) -> None:
        """Initialize violation service.

        Args:
            db: Database session (dependency injected)
            evidence_service: Optional evidence service for auto-capturing snapshots
        """
        self._db = db
        self._evidence_service = evidence_service

    # -------------------------------------------------------------------------
    # Event Processing (Main Entry Point)
    # -------------------------------------------------------------------------

    async def process_event(self, event: Event) -> Violation | None:
        """Process an event and create or attach to a violation.

        This is the main entry point for violation orchestration.
        Called by EventIngestionService when an actionable event is detected.

        Rules:
        - If event already has a violation_id, return None (already processed)
        - If an open violation exists for same device/session/type, attach event
        - Otherwise, create a new violation

        Args:
            event: Actionable Event entity (already persisted)

        Returns:
            Violation that was created or updated, or None if event already processed

        Raises:
            ViolationCreationError: Failed to create violation
        """
        logger.info(
            "Processing event for violation",
            event_id=str(event.id),
            event_type=event.event_type.value,
            device_id=str(event.device_id),
        )

        # Check if event already processed (idempotency)
        if event.violation_id is not None:
            logger.debug(
                "Event already has violation",
                event_id=str(event.id),
                violation_id=str(event.violation_id),
            )
            return None

        # Map event type to violation type
        violation_type = self._map_event_to_violation_type(event.event_type)
        if violation_type is None:
            logger.debug(
                "Event type not mappable to violation",
                event_id=str(event.id),
                event_type=event.event_type.value,
            )
            return None

        # Check for existing open violation (aggregation)
        existing = await self.get_open_violation(
            device_id=event.device_id,
            stream_session_id=event.stream_session_id,
            violation_type=violation_type,
        )

        if existing is not None:
            # Attach event to existing violation
            return await self._attach_event_to_violation(event, existing)

        # Create new violation
        return await self._create_violation_from_event(event, violation_type)

    async def create_violation_from_event(self, event: Event) -> None:
        """Create a violation from an actionable event.

        This method implements ViolationServiceProtocol for EventIngestionService.
        It delegates to process_event() internally.

        Args:
            event: Actionable Event entity
        """
        await self.process_event(event)

    # -------------------------------------------------------------------------
    # Violation Creation
    # -------------------------------------------------------------------------

    async def _create_violation_from_event(
        self,
        event: Event,
        violation_type: ViolationType,
    ) -> Violation:
        """Create a new violation from an event.

        Args:
            event: Triggering Event entity
            violation_type: Type of violation to create

        Returns:
            Created Violation entity

        Raises:
            ViolationCreationError: Failed to create violation
        """
        try:
            # Get device name for denormalization
            # Event already has device relationship loaded
            device = event.device
            camera_name = device.name if device else "Unknown Camera"

            violation = Violation(
                device_id=event.device_id,
                stream_session_id=event.stream_session_id,
                type=violation_type,
                status=ViolationStatus.OPEN,
                confidence=event.confidence,
                timestamp=event.timestamp,
                camera_name=camera_name,
                model_id=event.model_id,
                model_version=event.model_version,
                bounding_boxes=event.bounding_boxes,
            )

            self._db.add(violation)
            await self._db.flush()

            # Link event to violation
            event.violation_id = violation.id

            logger.info(
                "Created violation from event",
                violation_id=str(violation.id),
                event_id=str(event.id),
                violation_type=violation_type.value,
                confidence=event.confidence,
            )

            # Trigger evidence capture (fire-and-forget)
            # Failures should NOT block violation creation
            await self._trigger_evidence_capture(violation)

            return violation

        except Exception as e:
            logger.error(
                "Failed to create violation",
                event_id=str(event.id),
                error=str(e),
            )
            raise ViolationCreationError(
                "Failed to create violation from event",
                event_id=event.id,
                device_id=event.device_id,
                cause=e,
            ) from e

    async def _attach_event_to_violation(
        self,
        event: Event,
        violation: Violation,
    ) -> Violation:
        """Attach an event to an existing violation.

        Updates violation confidence if the new event has higher confidence.

        Args:
            event: Event to attach
            violation: Existing Violation to attach to

        Returns:
            Updated Violation entity
        """
        # Link event to violation
        event.violation_id = violation.id

        # Update confidence if higher
        if event.confidence > violation.confidence:
            violation.confidence = event.confidence
            violation.bounding_boxes = event.bounding_boxes

        logger.info(
            "Attached event to existing violation",
            event_id=str(event.id),
            violation_id=str(violation.id),
            new_confidence=event.confidence,
            violation_confidence=violation.confidence,
        )

        return violation

    # -------------------------------------------------------------------------
    # Violation Retrieval
    # -------------------------------------------------------------------------

    async def get_violation_by_id(self, violation_id: UUID) -> Violation:
        """Get violation by ID.

        Args:
            violation_id: Violation UUID

        Returns:
            Violation entity

        Raises:
            ViolationNotFoundError: Violation does not exist
        """
        stmt = select(Violation).where(Violation.id == violation_id)
        result = await self._db.execute(stmt)
        violation = result.scalar_one_or_none()

        if violation is None:
            raise ViolationNotFoundError(violation_id)

        return violation

    async def get_open_violation(
        self,
        device_id: UUID,
        stream_session_id: UUID | None,
        violation_type: ViolationType,
    ) -> Violation | None:
        """Get open violation for device/session/type combination.

        This is used for aggregation: if an open violation exists,
        subsequent events should be attached to it instead of creating new ones.

        Args:
            device_id: Local device UUID
            stream_session_id: Stream session UUID (can be None)
            violation_type: Type of violation

        Returns:
            Open Violation or None if not found
        """
        # Build conditions
        conditions = [
            Violation.device_id == device_id,
            Violation.type == violation_type,
            Violation.status.in_(OPEN_STATES),
        ]

        # Session matching
        if stream_session_id is not None:
            conditions.append(Violation.stream_session_id == stream_session_id)
        else:
            conditions.append(Violation.stream_session_id.is_(None))

        stmt = (
            select(Violation)
            .where(and_(*conditions))
            .order_by(Violation.timestamp.desc())
            .limit(1)
        )

        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_violations_for_device(
        self,
        device_id: UUID,
        *,
        status: ViolationStatus | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Violation]:
        """Get violations for a device.

        Args:
            device_id: Local device UUID
            status: Filter by status (optional)
            since: Only violations after this timestamp
            limit: Maximum violations to return

        Returns:
            List of violations, most recent first
        """
        stmt = (
            select(Violation)
            .where(Violation.device_id == device_id)
            .order_by(Violation.timestamp.desc())
            .limit(limit)
        )

        if status is not None:
            stmt = stmt.where(Violation.status == status)

        if since is not None:
            stmt = stmt.where(Violation.timestamp >= since)

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_open_violations(
        self,
        *,
        device_id: UUID | None = None,
        limit: int = 100,
    ) -> list[Violation]:
        """Get all open violations.

        Args:
            device_id: Filter by device (optional)
            limit: Maximum violations to return

        Returns:
            List of open violations, most recent first
        """
        stmt = (
            select(Violation)
            .where(Violation.status.in_(OPEN_STATES))
            .order_by(Violation.timestamp.desc())
            .limit(limit)
        )

        if device_id is not None:
            stmt = stmt.where(Violation.device_id == device_id)

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # -------------------------------------------------------------------------
    # Status Transitions
    # -------------------------------------------------------------------------

    async def transition_status(
        self,
        violation_id: UUID,
        new_status: ViolationStatus,
        *,
        reviewed_by: str | None = None,
        resolution_notes: str | None = None,
    ) -> Violation:
        """Transition violation to a new status.

        Enforces valid state transitions.

        Args:
            violation_id: Violation UUID
            new_status: Target status
            reviewed_by: Operator identifier (for REVIEWED/RESOLVED transitions)
            resolution_notes: Notes about resolution (for RESOLVED)

        Returns:
            Updated Violation entity

        Raises:
            ViolationNotFoundError: Violation does not exist
            ViolationTerminalStateError: Violation is in terminal state
            ViolationStateError: Invalid transition
        """
        violation = await self.get_violation_by_id(violation_id)
        current_status = violation.status

        logger.info(
            "Transitioning violation status",
            violation_id=str(violation_id),
            current_status=current_status.value,
            new_status=new_status.value,
        )

        # Check terminal state
        if current_status in TERMINAL_STATES:
            raise ViolationTerminalStateError(violation_id, current_status.value)

        # Check valid transition
        valid_targets = VALID_STATUS_TRANSITIONS.get(current_status, set())
        if new_status not in valid_targets:
            raise ViolationStateError(
                violation_id,
                current_status.value,
                new_status.value,
            )

        # Apply transition
        violation.status = new_status

        # Update review metadata
        if new_status in {ViolationStatus.REVIEWED, ViolationStatus.RESOLVED}:
            if reviewed_by:
                violation.reviewed_by = reviewed_by
            violation.reviewed_at = datetime.now(timezone.utc)

        if new_status == ViolationStatus.RESOLVED and resolution_notes:
            violation.resolution_notes = resolution_notes[:2000]  # Truncate to limit

        logger.info(
            "Violation status transitioned",
            violation_id=str(violation_id),
            from_status=current_status.value,
            to_status=new_status.value,
        )

        return violation

    async def mark_reviewed(
        self,
        violation_id: UUID,
        reviewed_by: str,
    ) -> Violation:
        """Mark violation as reviewed.

        Convenience method for OPEN → REVIEWED transition.

        Args:
            violation_id: Violation UUID
            reviewed_by: Operator identifier

        Returns:
            Updated Violation entity
        """
        return await self.transition_status(
            violation_id,
            ViolationStatus.REVIEWED,
            reviewed_by=reviewed_by,
        )

    async def dismiss(
        self,
        violation_id: UUID,
        reviewed_by: str,
        *,
        notes: str | None = None,
    ) -> Violation:
        """Dismiss violation as false positive.

        Args:
            violation_id: Violation UUID
            reviewed_by: Operator identifier
            notes: Optional dismissal notes

        Returns:
            Updated Violation entity
        """
        return await self.transition_status(
            violation_id,
            ViolationStatus.DISMISSED,
            reviewed_by=reviewed_by,
            resolution_notes=notes,
        )

    async def resolve(
        self,
        violation_id: UUID,
        reviewed_by: str,
        notes: str,
    ) -> Violation:
        """Resolve violation.

        This is a terminal state - violation cannot be modified after this.

        Args:
            violation_id: Violation UUID
            reviewed_by: Operator identifier
            notes: Resolution notes (required)

        Returns:
            Updated Violation entity
        """
        return await self.transition_status(
            violation_id,
            ViolationStatus.RESOLVED,
            reviewed_by=reviewed_by,
            resolution_notes=notes,
        )

    async def reopen(self, violation_id: UUID) -> Violation:
        """Reopen a dismissed violation.

        Args:
            violation_id: Violation UUID

        Returns:
            Updated Violation entity
        """
        return await self.transition_status(
            violation_id,
            ViolationStatus.OPEN,
        )

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _map_event_to_violation_type(
        self,
        event_type: EventType,
    ) -> ViolationType | None:
        """Map event type to violation type.

        Args:
            event_type: Event type enum

        Returns:
            Corresponding ViolationType or None if not mappable
        """
        return EVENT_TYPE_TO_VIOLATION_TYPE.get(event_type)

    def is_valid_transition(
        self,
        current_status: ViolationStatus,
        target_status: ViolationStatus,
    ) -> bool:
        """Check if a status transition is valid.

        Args:
            current_status: Current violation status
            target_status: Target violation status

        Returns:
            True if transition is valid
        """
        if current_status in TERMINAL_STATES:
            return False
        valid_targets = VALID_STATUS_TRANSITIONS.get(current_status, set())
        return target_status in valid_targets

    async def _trigger_evidence_capture(self, violation: Violation) -> None:
        """Trigger evidence capture for a newly created violation.

        This is a fire-and-forget operation - failures are logged but do NOT
        block violation creation or raise exceptions.

        Args:
            violation: The newly created violation
        """
        if self._evidence_service is None:
            logger.debug(
                "No evidence service configured, skipping auto-capture",
                violation_id=str(violation.id),
            )
            return

        try:
            logger.info(
                "Triggering auto-snapshot capture for violation",
                violation_id=str(violation.id),
                device_id=str(violation.device_id),
            )

            # Create snapshot - this is idempotent (allow_existing=True)
            evidence = await self._evidence_service.create_snapshot(
                violation,
                created_by="ruth-ai-auto",
                allow_existing=True,
            )

            logger.info(
                "Auto-snapshot capture initiated",
                violation_id=str(violation.id),
                evidence_id=str(evidence.id),
                evidence_status=evidence.status.value,
            )

        except Exception as e:
            # Log but do NOT re-raise - evidence capture failure
            # should never block violation creation
            logger.warning(
                "Auto-snapshot capture failed (non-blocking)",
                violation_id=str(violation.id),
                device_id=str(violation.device_id),
                error=str(e),
                exc_info=True,
            )

    # -------------------------------------------------------------------------
    # Event Queries
    # -------------------------------------------------------------------------

    async def get_events_for_violation(
        self,
        violation_id: UUID,
        *,
        limit: int = 100,
    ) -> list[Event]:
        """Get events associated with a violation.

        Args:
            violation_id: Violation UUID
            limit: Maximum events to return

        Returns:
            List of events, ordered by timestamp
        """
        # Verify violation exists
        await self.get_violation_by_id(violation_id)

        stmt = (
            select(Event)
            .where(Event.violation_id == violation_id)
            .order_by(Event.timestamp.asc())
            .limit(limit)
        )

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def count_events_for_violation(self, violation_id: UUID) -> int:
        """Count events associated with a violation.

        Args:
            violation_id: Violation UUID

        Returns:
            Event count
        """
        from sqlalchemy import func

        # Verify violation exists
        await self.get_violation_by_id(violation_id)

        stmt = (
            select(func.count())
            .select_from(Event)
            .where(Event.violation_id == violation_id)
        )

        result = await self._db.execute(stmt)
        return result.scalar_one()

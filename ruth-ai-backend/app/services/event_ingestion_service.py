"""Event Ingestion Pipeline Service.

Responsible for:
- Accepting inference results from AI Runtime
- Normalizing detections into domain Events
- Persisting events immutably
- Applying confidence thresholds
- Delegating violation creation to ViolationService

This service does NOT create violations directly - it delegates to ViolationService.

Usage:
    event_service = EventIngestionService(
        device_service=device_service,
        stream_service=stream_service,
        violation_service=violation_service,  # Optional, for delegation
        db=db,
        confidence_threshold=0.7,
    )

    # Ingest an inference result
    events = await event_service.ingest_inference_result(inference_response)

    # Check if event should trigger violation
    if event_service.should_trigger_violation(event):
        # Violation service handles creation
        pass
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.ai_runtime import (
    Detection,
    InferenceResponse,
    InferenceStatus,
)
from app.models import Event, EventType

from .device_service import DeviceService
from .exceptions import (
    EventDeviceMissingError,
    EventIngestionError,
    EventSessionMissingError,
    InferenceFailedError,
)
from .stream_service import StreamService

if TYPE_CHECKING:
    from app.models import StreamSession

logger = get_logger(__name__)


# Protocol for ViolationService to avoid circular imports
class ViolationServiceProtocol(Protocol):
    """Protocol for violation service to enable loose coupling."""

    async def create_violation_from_event(self, event: Event) -> None:
        """Create a violation from an actionable event."""
        ...


# Mapping from detection class names to event types
DETECTION_CLASS_TO_EVENT_TYPE: dict[str, EventType] = {
    "fall_detected": EventType.FALL_DETECTED,
    "fall": EventType.FALL_DETECTED,
    "no_fall": EventType.NO_FALL,
    "person_detected": EventType.PERSON_DETECTED,
    "person": EventType.PERSON_DETECTED,
}

# Event types that can trigger violations
ACTIONABLE_EVENT_TYPES: set[EventType] = {
    EventType.FALL_DETECTED,
    EventType.PPE_VIOLATION,
}


class EventIngestionService:
    """Service for ingesting AI inference results into domain Events.

    This service:
    - Normalizes inference responses into Event entities
    - Persists ALL events (no drops)
    - Applies confidence thresholds
    - Marks events as actionable/non-actionable
    - Delegates violation creation to ViolationService

    Events are IMMUTABLE after creation.
    """

    def __init__(
        self,
        device_service: DeviceService,
        stream_service: StreamService,
        db: AsyncSession,
        *,
        violation_service: ViolationServiceProtocol | None = None,
        confidence_threshold: float = 0.7,
        require_active_session: bool = True,
    ) -> None:
        """Initialize event ingestion service.

        Args:
            device_service: Service for device resolution
            stream_service: Service for stream session resolution
            db: Database session (dependency injected)
            violation_service: Optional service for violation creation
            confidence_threshold: Minimum confidence for actionable events
            require_active_session: If True, reject events without active session
        """
        self._device_service = device_service
        self._stream_service = stream_service
        self._db = db
        self._violation_service = violation_service
        self._confidence_threshold = confidence_threshold
        self._require_active_session = require_active_session

    @property
    def confidence_threshold(self) -> float:
        """Get the confidence threshold for actionable events."""
        return self._confidence_threshold

    # -------------------------------------------------------------------------
    # Event Ingestion
    # -------------------------------------------------------------------------

    async def ingest_inference_result(
        self,
        inference: InferenceResponse,
    ) -> list[Event]:
        """Ingest inference result and create domain Events.

        This is the main entry point for the event ingestion pipeline.

        Args:
            inference: Inference response from AI Runtime

        Returns:
            List of persisted Event entities

        Raises:
            InferenceFailedError: Inference status is FAILED
            EventDeviceMissingError: Device not found
            EventSessionMissingError: No active session (if required)
        """
        logger.info(
            "Ingesting inference result",
            request_id=str(inference.request_id),
            stream_id=str(inference.stream_id),
            status=inference.status.value,
            detections=len(inference.detections),
        )

        # Check inference status
        if inference.status == InferenceStatus.FAILED:
            raise InferenceFailedError(
                inference.request_id,
                inference.error or "Unknown error",
            )

        if inference.status == InferenceStatus.TIMEOUT:
            raise InferenceFailedError(
                inference.request_id,
                "Inference timed out",
            )

        # Resolve device
        device_id = await self._resolve_device(inference)

        # Resolve session (may be None if not required)
        session = await self._resolve_session(device_id, inference)
        session_id = session.id if session else None

        # Create events from detections
        events: list[Event] = []

        if inference.has_detections:
            # Create event for each detection
            for detection in inference.detections:
                event = await self._create_event_from_detection(
                    detection=detection,
                    inference=inference,
                    device_id=device_id,
                    session_id=session_id,
                )
                events.append(event)
        else:
            # No detections - create a "no detection" event
            event = await self._create_no_detection_event(
                inference=inference,
                device_id=device_id,
                session_id=session_id,
            )
            events.append(event)

        # Flush to get IDs
        await self._db.flush()

        logger.info(
            "Events persisted",
            request_id=str(inference.request_id),
            event_count=len(events),
            actionable_count=sum(1 for e in events if self.should_trigger_violation(e)),
        )

        # Delegate violation creation for actionable events
        await self._delegate_violations(events)

        return events

    async def _resolve_device(
        self,
        inference: InferenceResponse,
    ) -> UUID:
        """Resolve device ID from inference response.

        Args:
            inference: Inference response

        Returns:
            Local device UUID

        Raises:
            EventDeviceMissingError: Device not found
        """
        # If device_id is provided directly, use it
        if inference.device_id:
            try:
                device = await self._device_service.get_device_by_id(
                    inference.device_id
                )
                return device.id
            except Exception:
                raise EventDeviceMissingError(inference.device_id)

        # Otherwise, we need to look up by stream session
        # The stream_id in inference maps to vas_stream_id in our session
        session = await self._stream_service.get_active_session_for_device(
            inference.stream_id  # This might be device_id in some cases
        )
        if session:
            return session.device_id

        raise EventDeviceMissingError(inference.stream_id)

    async def _resolve_session(
        self,
        device_id: UUID,
        inference: InferenceResponse,
    ) -> "StreamSession | None":
        """Resolve active stream session.

        Args:
            device_id: Local device UUID
            inference: Inference response

        Returns:
            Active StreamSession or None

        Raises:
            EventSessionMissingError: If required and not found
        """
        session = await self._stream_service.get_active_session_for_device(device_id)

        if session is None and self._require_active_session:
            raise EventSessionMissingError(
                device_id,
                stream_id=inference.stream_id,
            )

        return session

    async def _create_event_from_detection(
        self,
        detection: Detection,
        inference: InferenceResponse,
        device_id: UUID,
        session_id: UUID | None,
    ) -> Event:
        """Create Event entity from a detection.

        Args:
            detection: Detection from inference
            inference: Parent inference response
            device_id: Local device UUID
            session_id: Stream session UUID (may be None)

        Returns:
            Persisted Event entity
        """
        # Map detection class to event type
        event_type = self._map_detection_to_event_type(detection.class_name)

        # Convert bounding box to storage format
        bounding_boxes = None
        if detection.bounding_box:
            bb = detection.bounding_box
            bounding_boxes = [{
                "x": bb.x,
                "y": bb.y,
                "width": bb.width,
                "height": bb.height,
                "label": detection.class_name,
                "confidence": detection.confidence,
            }]

        event = Event(
            device_id=device_id,
            stream_session_id=session_id,
            event_type=event_type,
            confidence=detection.confidence,
            timestamp=inference.timestamp,
            model_id=inference.model_id,
            model_version=inference.model_version or "unknown",
            bounding_boxes=bounding_boxes,
            frame_id=str(inference.request_id),
            inference_time_ms=int(inference.inference_time_ms)
            if inference.inference_time_ms
            else None,
        )

        self._db.add(event)

        logger.debug(
            "Created event from detection",
            event_type=event_type.value,
            confidence=detection.confidence,
            device_id=str(device_id),
        )

        return event

    async def _create_no_detection_event(
        self,
        inference: InferenceResponse,
        device_id: UUID,
        session_id: UUID | None,
    ) -> Event:
        """Create Event for inference with no detections.

        Args:
            inference: Inference response with no detections
            device_id: Local device UUID
            session_id: Stream session UUID (may be None)

        Returns:
            Persisted Event entity
        """
        event = Event(
            device_id=device_id,
            stream_session_id=session_id,
            event_type=EventType.NO_FALL,  # No detection = no fall
            confidence=1.0 - inference.max_confidence,  # Inverse confidence
            timestamp=inference.timestamp,
            model_id=inference.model_id,
            model_version=inference.model_version or "unknown",
            bounding_boxes=None,
            frame_id=str(inference.request_id),
            inference_time_ms=int(inference.inference_time_ms)
            if inference.inference_time_ms
            else None,
        )

        self._db.add(event)

        logger.debug(
            "Created no-detection event",
            device_id=str(device_id),
        )

        return event

    def _map_detection_to_event_type(self, class_name: str) -> EventType:
        """Map detection class name to EventType enum.

        Args:
            class_name: Detection class from AI Runtime

        Returns:
            Corresponding EventType
        """
        normalized = class_name.lower().strip()
        return DETECTION_CLASS_TO_EVENT_TYPE.get(normalized, EventType.UNKNOWN)

    # -------------------------------------------------------------------------
    # Threshold Logic
    # -------------------------------------------------------------------------

    def should_trigger_violation(self, event: Event) -> bool:
        """Determine if an event should trigger a violation.

        An event is actionable if:
        1. Event type is in ACTIONABLE_EVENT_TYPES
        2. Confidence is >= threshold

        Args:
            event: Event entity to evaluate

        Returns:
            True if event should trigger violation
        """
        if event.event_type not in ACTIONABLE_EVENT_TYPES:
            return False

        return event.confidence >= self._confidence_threshold

    def is_above_threshold(self, confidence: float) -> bool:
        """Check if confidence is above threshold.

        Args:
            confidence: Confidence score (0.0 to 1.0)

        Returns:
            True if above threshold
        """
        return confidence >= self._confidence_threshold

    # -------------------------------------------------------------------------
    # Violation Delegation
    # -------------------------------------------------------------------------

    async def _delegate_violations(self, events: list[Event]) -> None:
        """Delegate violation creation for actionable events.

        This service does NOT create violations directly.
        It delegates to ViolationService.

        Args:
            events: List of events to evaluate
        """
        if not self._violation_service:
            logger.debug("No violation service configured, skipping delegation")
            return

        for event in events:
            if self.should_trigger_violation(event):
                try:
                    await self._violation_service.create_violation_from_event(event)
                    logger.info(
                        "Delegated violation creation",
                        event_id=str(event.id),
                        event_type=event.event_type.value,
                        confidence=event.confidence,
                    )
                except Exception as e:
                    # Log but don't fail - event is already persisted
                    logger.error(
                        "Violation creation failed",
                        event_id=str(event.id),
                        error=str(e),
                    )

    # -------------------------------------------------------------------------
    # Direct Event Creation (for testing/manual use)
    # -------------------------------------------------------------------------

    async def persist_event(
        self,
        device_id: UUID,
        event_type: EventType,
        confidence: float,
        timestamp: datetime,
        *,
        session_id: UUID | None = None,
        model_id: str = "manual",
        model_version: str = "1.0.0",
        bounding_boxes: list[dict] | None = None,
        frame_id: str | None = None,
    ) -> Event:
        """Persist an event directly (for testing or manual ingestion).

        Args:
            device_id: Local device UUID
            event_type: Type of event
            confidence: Confidence score (0.0 to 1.0)
            timestamp: Event timestamp
            session_id: Stream session UUID (optional)
            model_id: Model identifier
            model_version: Model version
            bounding_boxes: Detection bounding boxes
            frame_id: Frame reference

        Returns:
            Persisted Event entity
        """
        # Validate device exists
        try:
            await self._device_service.get_device_by_id(device_id)
        except Exception:
            raise EventDeviceMissingError(device_id)

        event = Event(
            device_id=device_id,
            stream_session_id=session_id,
            event_type=event_type,
            confidence=confidence,
            timestamp=timestamp,
            model_id=model_id,
            model_version=model_version,
            bounding_boxes=bounding_boxes,
            frame_id=frame_id,
        )

        self._db.add(event)
        await self._db.flush()

        logger.info(
            "Event persisted directly",
            event_id=str(event.id),
            event_type=event_type.value,
            confidence=confidence,
        )

        # Delegate violation if actionable
        if self._violation_service and self.should_trigger_violation(event):
            try:
                await self._violation_service.create_violation_from_event(event)
            except Exception as e:
                logger.error("Violation creation failed", error=str(e))

        return event

    # -------------------------------------------------------------------------
    # Query Methods
    # -------------------------------------------------------------------------

    async def get_event_by_id(self, event_id: UUID) -> Event | None:
        """Get event by ID.

        Args:
            event_id: Event UUID

        Returns:
            Event or None if not found
        """
        from sqlalchemy import select

        stmt = select(Event).where(Event.id == event_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_events_for_device(
        self,
        device_id: UUID,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Get recent events for a device.

        Args:
            device_id: Local device UUID
            since: Only events after this timestamp
            limit: Maximum events to return

        Returns:
            List of events, most recent first
        """
        from sqlalchemy import select

        stmt = (
            select(Event)
            .where(Event.device_id == device_id)
            .order_by(Event.timestamp.desc())
            .limit(limit)
        )

        if since:
            stmt = stmt.where(Event.timestamp >= since)

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_actionable_events_for_device(
        self,
        device_id: UUID,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Get actionable events (above threshold) for a device.

        Args:
            device_id: Local device UUID
            since: Only events after this timestamp
            limit: Maximum events to return

        Returns:
            List of actionable events
        """
        from sqlalchemy import and_, select

        stmt = (
            select(Event)
            .where(
                and_(
                    Event.device_id == device_id,
                    Event.event_type.in_(ACTIONABLE_EVENT_TYPES),
                    Event.confidence >= self._confidence_threshold,
                )
            )
            .order_by(Event.timestamp.desc())
            .limit(limit)
        )

        if since:
            stmt = stmt.where(Event.timestamp >= since)

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

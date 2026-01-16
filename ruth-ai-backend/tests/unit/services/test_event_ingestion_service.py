"""Unit tests for EventIngestionService.

Tests:
- Inference result ingestion
- Event creation from detections
- Confidence threshold logic
- Violation delegation
- Error conditions
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.ai_runtime import (
    BoundingBox,
    Detection,
    InferenceResponse,
    InferenceStatus,
)
from app.models import Device, Event, EventType, StreamSession, StreamState
from app.services.event_ingestion_service import (
    EventIngestionService,
    ACTIONABLE_EVENT_TYPES,
    DETECTION_CLASS_TO_EVENT_TYPE,
)
from app.services.exceptions import (
    EventDeviceMissingError,
    EventSessionMissingError,
    InferenceFailedError,
)


class TestIngestInferenceResult:
    """Tests for ingest_inference_result method."""

    @pytest.mark.asyncio
    async def test_creates_events_from_detections(
        self,
        mock_db,
        device_factory,
        stream_session_factory,
        inference_response_factory,
        detection_factory,
    ):
        """Creates events from inference detections."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(device_id=device.id)

        detections = [
            detection_factory(class_name="fall_detected", confidence=0.9),
            detection_factory(class_name="person_detected", confidence=0.8),
        ]
        inference = inference_response_factory(
            device_id=device.id,
            detections=detections,
        )

        # Create mock device service
        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(return_value=device)

        # Create mock stream service
        mock_stream_service = MagicMock()
        mock_stream_service.get_active_session_for_device = AsyncMock(return_value=session)

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act
        events = await service.ingest_inference_result(inference)

        # Assert
        assert len(events) == 2
        added_events = mock_db.get_added_of_type(Event)
        assert len(added_events) == 2

        # Check first event (fall_detected)
        fall_event = next(e for e in added_events if e.event_type == EventType.FALL_DETECTED)
        assert fall_event.confidence == 0.9
        assert fall_event.device_id == device.id

        # Check second event (person_detected)
        person_event = next(e for e in added_events if e.event_type == EventType.PERSON_DETECTED)
        assert person_event.confidence == 0.8

    @pytest.mark.asyncio
    async def test_creates_no_detection_event_when_empty(
        self,
        mock_db,
        device_factory,
        stream_session_factory,
        inference_response_factory,
    ):
        """Creates NO_FALL event when no detections."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(device_id=device.id)

        inference = inference_response_factory(
            device_id=device.id,
            detections=[],  # No detections
        )

        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(return_value=device)

        mock_stream_service = MagicMock()
        mock_stream_service.get_active_session_for_device = AsyncMock(return_value=session)

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act
        events = await service.ingest_inference_result(inference)

        # Assert
        assert len(events) == 1
        assert events[0].event_type == EventType.NO_FALL

    @pytest.mark.asyncio
    async def test_raises_on_failed_inference(
        self,
        mock_db,
        inference_response_factory,
    ):
        """Raises InferenceFailedError on failed inference."""
        # Arrange
        inference = inference_response_factory(
            status=InferenceStatus.FAILED,
            error="Model not loaded",
        )

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act & Assert
        with pytest.raises(InferenceFailedError) as exc_info:
            await service.ingest_inference_result(inference)

        assert "Model not loaded" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_on_timeout_inference(
        self,
        mock_db,
        inference_response_factory,
    ):
        """Raises InferenceFailedError on timeout inference."""
        # Arrange
        inference = inference_response_factory(
            status=InferenceStatus.TIMEOUT,
        )

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act & Assert
        with pytest.raises(InferenceFailedError) as exc_info:
            await service.ingest_inference_result(inference)

        assert "timed out" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_raises_on_unknown_device(
        self,
        mock_db,
        inference_response_factory,
    ):
        """Raises EventDeviceMissingError when device not found."""
        # Arrange
        inference = inference_response_factory(
            device_id=uuid.uuid4(),
        )

        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(
            side_effect=Exception("Device not found")
        )

        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act & Assert
        with pytest.raises(EventDeviceMissingError):
            await service.ingest_inference_result(inference)

    @pytest.mark.asyncio
    async def test_raises_on_missing_session_when_required(
        self,
        mock_db,
        device_factory,
        inference_response_factory,
    ):
        """Raises EventSessionMissingError when session required but missing."""
        # Arrange
        device = device_factory()
        inference = inference_response_factory(device_id=device.id)

        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(return_value=device)

        mock_stream_service = MagicMock()
        mock_stream_service.get_active_session_for_device = AsyncMock(return_value=None)

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            require_active_session=True,
        )

        # Act & Assert
        with pytest.raises(EventSessionMissingError):
            await service.ingest_inference_result(inference)

    @pytest.mark.asyncio
    async def test_allows_missing_session_when_not_required(
        self,
        mock_db,
        device_factory,
        inference_response_factory,
        detection_factory,
    ):
        """Allows missing session when require_active_session is False."""
        # Arrange
        device = device_factory()
        inference = inference_response_factory(
            device_id=device.id,
            detections=[detection_factory()],
        )

        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(return_value=device)

        mock_stream_service = MagicMock()
        mock_stream_service.get_active_session_for_device = AsyncMock(return_value=None)

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            require_active_session=False,
        )

        # Act
        events = await service.ingest_inference_result(inference)

        # Assert
        assert len(events) == 1
        assert events[0].stream_session_id is None


class TestConfidenceThreshold:
    """Tests for confidence threshold logic."""

    def test_should_trigger_violation_for_actionable_above_threshold(
        self,
        mock_db,
        event_factory,
    ):
        """Returns True for actionable event above threshold."""
        # Arrange
        event = event_factory(
            event_type=EventType.FALL_DETECTED,
            confidence=0.85,
        )

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            confidence_threshold=0.7,
        )

        # Act
        result = service.should_trigger_violation(event)

        # Assert
        assert result is True

    def test_should_not_trigger_violation_below_threshold(
        self,
        mock_db,
        event_factory,
    ):
        """Returns False for event below threshold."""
        # Arrange
        event = event_factory(
            event_type=EventType.FALL_DETECTED,
            confidence=0.5,  # Below 0.7 threshold
        )

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            confidence_threshold=0.7,
        )

        # Act
        result = service.should_trigger_violation(event)

        # Assert
        assert result is False

    def test_should_not_trigger_violation_for_non_actionable(
        self,
        mock_db,
        event_factory,
    ):
        """Returns False for non-actionable event type."""
        # Arrange
        event = event_factory(
            event_type=EventType.NO_FALL,  # Not actionable
            confidence=0.95,
        )

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            confidence_threshold=0.7,
        )

        # Act
        result = service.should_trigger_violation(event)

        # Assert
        assert result is False

    def test_is_above_threshold(self, mock_db):
        """Correctly checks confidence against threshold."""
        # Arrange
        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            confidence_threshold=0.7,
        )

        # Act & Assert
        assert service.is_above_threshold(0.8) is True
        assert service.is_above_threshold(0.7) is True  # Exact threshold
        assert service.is_above_threshold(0.69) is False
        assert service.is_above_threshold(0.0) is False


class TestDetectionClassMapping:
    """Tests for detection class to event type mapping."""

    def test_fall_detected_mapping(self):
        """fall_detected maps to FALL_DETECTED."""
        assert DETECTION_CLASS_TO_EVENT_TYPE["fall_detected"] == EventType.FALL_DETECTED
        assert DETECTION_CLASS_TO_EVENT_TYPE["fall"] == EventType.FALL_DETECTED

    def test_no_fall_mapping(self):
        """no_fall maps to NO_FALL."""
        assert DETECTION_CLASS_TO_EVENT_TYPE["no_fall"] == EventType.NO_FALL

    def test_person_detected_mapping(self):
        """person_detected maps to PERSON_DETECTED."""
        assert DETECTION_CLASS_TO_EVENT_TYPE["person_detected"] == EventType.PERSON_DETECTED
        assert DETECTION_CLASS_TO_EVENT_TYPE["person"] == EventType.PERSON_DETECTED


class TestActionableEventTypes:
    """Tests for actionable event type configuration."""

    def test_fall_detected_is_actionable(self):
        """FALL_DETECTED is actionable."""
        assert EventType.FALL_DETECTED in ACTIONABLE_EVENT_TYPES

    def test_no_fall_is_not_actionable(self):
        """NO_FALL is not actionable."""
        assert EventType.NO_FALL not in ACTIONABLE_EVENT_TYPES

    def test_person_detected_is_not_actionable(self):
        """PERSON_DETECTED is not actionable (informational only)."""
        assert EventType.PERSON_DETECTED not in ACTIONABLE_EVENT_TYPES


class TestViolationDelegation:
    """Tests for violation service delegation."""

    @pytest.mark.asyncio
    async def test_delegates_to_violation_service(
        self,
        mock_db,
        device_factory,
        stream_session_factory,
        inference_response_factory,
        detection_factory,
    ):
        """Delegates actionable events to violation service."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(device_id=device.id)

        detection = detection_factory(class_name="fall_detected", confidence=0.9)
        inference = inference_response_factory(
            device_id=device.id,
            detections=[detection],
        )

        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(return_value=device)

        mock_stream_service = MagicMock()
        mock_stream_service.get_active_session_for_device = AsyncMock(return_value=session)

        mock_violation_service = MagicMock()
        mock_violation_service.create_violation_from_event = AsyncMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            violation_service=mock_violation_service,
            confidence_threshold=0.7,
        )

        # Act
        await service.ingest_inference_result(inference)

        # Assert
        mock_violation_service.create_violation_from_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_delegate_below_threshold(
        self,
        mock_db,
        device_factory,
        stream_session_factory,
        inference_response_factory,
        detection_factory,
    ):
        """Does not delegate events below threshold."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(device_id=device.id)

        detection = detection_factory(class_name="fall_detected", confidence=0.5)  # Below threshold
        inference = inference_response_factory(
            device_id=device.id,
            detections=[detection],
        )

        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(return_value=device)

        mock_stream_service = MagicMock()
        mock_stream_service.get_active_session_for_device = AsyncMock(return_value=session)

        mock_violation_service = MagicMock()
        mock_violation_service.create_violation_from_event = AsyncMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            violation_service=mock_violation_service,
            confidence_threshold=0.7,
        )

        # Act
        await service.ingest_inference_result(inference)

        # Assert
        mock_violation_service.create_violation_from_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_on_violation_service_error(
        self,
        mock_db,
        device_factory,
        stream_session_factory,
        inference_response_factory,
        detection_factory,
    ):
        """Continues processing even if violation service fails."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(device_id=device.id)

        detection = detection_factory(class_name="fall_detected", confidence=0.9)
        inference = inference_response_factory(
            device_id=device.id,
            detections=[detection],
        )

        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(return_value=device)

        mock_stream_service = MagicMock()
        mock_stream_service.get_active_session_for_device = AsyncMock(return_value=session)

        mock_violation_service = MagicMock()
        mock_violation_service.create_violation_from_event = AsyncMock(
            side_effect=Exception("Violation service error")
        )

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            violation_service=mock_violation_service,
            confidence_threshold=0.7,
        )

        # Act - should not raise
        events = await service.ingest_inference_result(inference)

        # Assert - event should still be created
        assert len(events) == 1


class TestDirectEventPersistence:
    """Tests for persist_event method."""

    @pytest.mark.asyncio
    async def test_persist_event_directly(
        self,
        mock_db,
        device_factory,
    ):
        """Persists event directly without inference."""
        # Arrange
        device = device_factory()

        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(return_value=device)

        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act
        event = await service.persist_event(
            device_id=device.id,
            event_type=EventType.FALL_DETECTED,
            confidence=0.85,
            timestamp=datetime.now(timezone.utc),
            model_id="test_model",
        )

        # Assert
        assert event is not None
        assert event.device_id == device.id
        assert event.event_type == EventType.FALL_DETECTED
        assert event.confidence == 0.85

    @pytest.mark.asyncio
    async def test_persist_event_raises_on_unknown_device(
        self,
        mock_db,
    ):
        """Raises EventDeviceMissingError for unknown device."""
        # Arrange
        mock_device_service = MagicMock()
        mock_device_service.get_device_by_id = AsyncMock(
            side_effect=Exception("Device not found")
        )

        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act & Assert
        with pytest.raises(EventDeviceMissingError):
            await service.persist_event(
                device_id=uuid.uuid4(),
                event_type=EventType.FALL_DETECTED,
                confidence=0.85,
                timestamp=datetime.now(timezone.utc),
            )


class TestEventQueries:
    """Tests for event query methods."""

    @pytest.mark.asyncio
    async def test_get_event_by_id(
        self,
        mock_db,
        event_factory,
    ):
        """Retrieves event by ID."""
        # Arrange
        event = event_factory()

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = event
            return result

        mock_db.execute = mock_execute

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act
        result = await service.get_event_by_id(event.id)

        # Assert
        assert result == event

    @pytest.mark.asyncio
    async def test_get_event_by_id_returns_none_when_not_found(
        self,
        mock_db,
    ):
        """Returns None when event not found."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act
        result = await service.get_event_by_id(uuid.uuid4())

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_events_for_device(
        self,
        mock_db,
        event_factory,
    ):
        """Retrieves events for device."""
        # Arrange
        device_id = uuid.uuid4()
        events = [
            event_factory(device_id=device_id),
            event_factory(device_id=device_id),
        ]

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: events)
            return result

        mock_db.execute = mock_execute

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
        )

        # Act
        result = await service.get_events_for_device(device_id)

        # Assert
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_actionable_events_for_device(
        self,
        mock_db,
        event_factory,
    ):
        """Retrieves only actionable events for device."""
        # Arrange
        device_id = uuid.uuid4()
        actionable_event = event_factory(
            device_id=device_id,
            event_type=EventType.FALL_DETECTED,
            confidence=0.85,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [actionable_event])
            return result

        mock_db.execute = mock_execute

        mock_device_service = MagicMock()
        mock_stream_service = MagicMock()

        service = EventIngestionService(
            mock_device_service,
            mock_stream_service,
            mock_db,
            confidence_threshold=0.7,
        )

        # Act
        result = await service.get_actionable_events_for_device(device_id)

        # Assert
        assert len(result) == 1
        assert result[0].event_type == EventType.FALL_DETECTED

"""Unit tests for ViolationService.

Tests:
- Violation creation from events
- Event aggregation (multiple events to single violation)
- Idempotency (same event processed multiple times)
- Status transitions
- Terminal state enforcement
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Event, EventType, Violation, ViolationStatus, ViolationType
from app.services.violation_service import (
    ViolationService,
    VALID_STATUS_TRANSITIONS,
    TERMINAL_STATES,
    OPEN_STATES,
    EVENT_TYPE_TO_VIOLATION_TYPE,
)
from app.services.exceptions import (
    ViolationCreationError,
    ViolationNotFoundError,
    ViolationStateError,
    ViolationTerminalStateError,
)


class TestProcessEvent:
    """Tests for process_event method."""

    @pytest.mark.asyncio
    async def test_creates_new_violation_from_event(
        self,
        mock_db,
        event_factory,
        device_factory,
    ):
        """Creates new violation when no existing open violation."""
        # Arrange
        device = device_factory()
        event = event_factory(
            device_id=device.id,
            event_type=EventType.FALL_DETECTED,
            confidence=0.85,
        )
        event.device = device  # Set relationship for camera_name

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None  # No existing violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        violation = await service.process_event(event)

        # Assert
        assert violation is not None
        assert violation.device_id == device.id
        assert violation.type == ViolationType.FALL_DETECTED
        assert violation.status == ViolationStatus.OPEN
        assert violation.confidence == 0.85
        assert event.violation_id == violation.id

    @pytest.mark.asyncio
    async def test_returns_none_when_event_already_processed(
        self,
        mock_db,
        event_factory,
        violation_factory,
    ):
        """Returns None when event already has a violation."""
        # Arrange
        violation = violation_factory()
        event = event_factory(violation_id=violation.id)

        service = ViolationService(mock_db)

        # Act
        result = await service.process_event(event)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_mappable_event_type(
        self,
        mock_db,
        event_factory,
    ):
        """Returns None for event types that don't map to violations."""
        # Arrange
        event = event_factory(event_type=EventType.NO_FALL)

        service = ViolationService(mock_db)

        # Act
        result = await service.process_event(event)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_attaches_event_to_existing_open_violation(
        self,
        mock_db,
        event_factory,
        violation_factory,
        device_factory,
    ):
        """Attaches new event to existing open violation."""
        # Arrange
        device = device_factory()
        existing_violation = violation_factory(
            device_id=device.id,
            status=ViolationStatus.OPEN,
            confidence=0.7,
        )

        new_event = event_factory(
            device_id=device.id,
            event_type=EventType.FALL_DETECTED,
            confidence=0.9,  # Higher confidence
        )
        new_event.device = device

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                # First call returns existing violation
                result.scalar_one_or_none.return_value = existing_violation
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        violation = await service.process_event(new_event)

        # Assert
        assert violation == existing_violation
        assert new_event.violation_id == existing_violation.id
        # Confidence should be updated to higher value
        assert existing_violation.confidence == 0.9


class TestIdempotency:
    """Tests for idempotent violation creation."""

    @pytest.mark.asyncio
    async def test_same_event_processed_twice_no_duplicate(
        self,
        mock_db,
        event_factory,
        violation_factory,
    ):
        """Processing same event twice does not create duplicate."""
        # Arrange
        violation = violation_factory()
        event = event_factory(violation_id=violation.id)

        service = ViolationService(mock_db)

        # Act
        result1 = await service.process_event(event)
        result2 = await service.process_event(event)

        # Assert
        assert result1 is None
        assert result2 is None

    @pytest.mark.asyncio
    async def test_aggregation_links_multiple_events(
        self,
        mock_db,
        event_factory,
        violation_factory,
        device_factory,
    ):
        """Multiple events from same device/session aggregate to one violation."""
        # Arrange
        device = device_factory()
        session_id = uuid.uuid4()
        existing_violation = violation_factory(
            device_id=device.id,
            stream_session_id=session_id,
            status=ViolationStatus.OPEN,
        )

        event1 = event_factory(
            device_id=device.id,
            stream_session_id=session_id,
            event_type=EventType.FALL_DETECTED,
        )
        event1.device = device

        event2 = event_factory(
            device_id=device.id,
            stream_session_id=session_id,
            event_type=EventType.FALL_DETECTED,
        )
        event2.device = device

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing_violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        await service.process_event(event1)
        await service.process_event(event2)

        # Assert
        assert event1.violation_id == existing_violation.id
        assert event2.violation_id == existing_violation.id


class TestStatusTransitions:
    """Tests for violation status transitions."""

    def test_valid_transitions_from_open(self):
        """OPEN can transition to REVIEWED or DISMISSED."""
        valid = VALID_STATUS_TRANSITIONS[ViolationStatus.OPEN]
        assert ViolationStatus.REVIEWED in valid
        assert ViolationStatus.DISMISSED in valid
        assert ViolationStatus.RESOLVED not in valid

    def test_valid_transitions_from_reviewed(self):
        """REVIEWED can transition to DISMISSED or RESOLVED."""
        valid = VALID_STATUS_TRANSITIONS[ViolationStatus.REVIEWED]
        assert ViolationStatus.DISMISSED in valid
        assert ViolationStatus.RESOLVED in valid

    def test_valid_transitions_from_dismissed(self):
        """DISMISSED can transition to OPEN (re-open)."""
        valid = VALID_STATUS_TRANSITIONS[ViolationStatus.DISMISSED]
        assert ViolationStatus.OPEN in valid
        assert len(valid) == 1

    def test_resolved_is_terminal(self):
        """RESOLVED has no valid transitions."""
        valid = VALID_STATUS_TRANSITIONS[ViolationStatus.RESOLVED]
        assert len(valid) == 0
        assert ViolationStatus.RESOLVED in TERMINAL_STATES

    def test_open_states_include_open_and_reviewed(self):
        """OPEN_STATES includes OPEN and REVIEWED."""
        assert ViolationStatus.OPEN in OPEN_STATES
        assert ViolationStatus.REVIEWED in OPEN_STATES
        assert ViolationStatus.DISMISSED not in OPEN_STATES
        assert ViolationStatus.RESOLVED not in OPEN_STATES


class TestTransitionStatus:
    """Tests for transition_status method."""

    @pytest.mark.asyncio
    async def test_transitions_open_to_reviewed(
        self,
        mock_db,
        violation_factory,
    ):
        """Transitions violation from OPEN to REVIEWED."""
        # Arrange
        violation = violation_factory(status=ViolationStatus.OPEN)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.transition_status(
            violation.id,
            ViolationStatus.REVIEWED,
            reviewed_by="operator1",
        )

        # Assert
        assert result.status == ViolationStatus.REVIEWED
        assert result.reviewed_by == "operator1"
        assert result.reviewed_at is not None

    @pytest.mark.asyncio
    async def test_raises_on_invalid_transition(
        self,
        mock_db,
        violation_factory,
    ):
        """Raises ViolationStateError on invalid transition."""
        # Arrange
        violation = violation_factory(status=ViolationStatus.OPEN)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act & Assert
        with pytest.raises(ViolationStateError) as exc_info:
            await service.transition_status(
                violation.id,
                ViolationStatus.RESOLVED,  # Invalid from OPEN
            )

        assert "open" in str(exc_info.value).lower()
        assert "resolved" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_raises_on_terminal_state(
        self,
        mock_db,
        violation_factory,
    ):
        """Raises ViolationTerminalStateError when in terminal state."""
        # Arrange
        violation = violation_factory(status=ViolationStatus.RESOLVED)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act & Assert
        with pytest.raises(ViolationTerminalStateError):
            await service.transition_status(
                violation.id,
                ViolationStatus.OPEN,
            )

    @pytest.mark.asyncio
    async def test_raises_on_not_found(
        self,
        mock_db,
    ):
        """Raises ViolationNotFoundError when violation doesn't exist."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act & Assert
        with pytest.raises(ViolationNotFoundError):
            await service.transition_status(
                uuid.uuid4(),
                ViolationStatus.REVIEWED,
            )


class TestConvenienceMethods:
    """Tests for convenience transition methods."""

    @pytest.mark.asyncio
    async def test_mark_reviewed(
        self,
        mock_db,
        violation_factory,
    ):
        """mark_reviewed transitions to REVIEWED."""
        # Arrange
        violation = violation_factory(status=ViolationStatus.OPEN)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.mark_reviewed(violation.id, "operator1")

        # Assert
        assert result.status == ViolationStatus.REVIEWED
        assert result.reviewed_by == "operator1"

    @pytest.mark.asyncio
    async def test_dismiss(
        self,
        mock_db,
        violation_factory,
    ):
        """dismiss transitions to DISMISSED."""
        # Arrange
        violation = violation_factory(status=ViolationStatus.OPEN)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.dismiss(
            violation.id,
            "operator1",
            notes="False positive",
        )

        # Assert
        assert result.status == ViolationStatus.DISMISSED
        assert result.resolution_notes == "False positive"

    @pytest.mark.asyncio
    async def test_resolve(
        self,
        mock_db,
        violation_factory,
    ):
        """resolve transitions to RESOLVED (terminal)."""
        # Arrange
        violation = violation_factory(status=ViolationStatus.REVIEWED)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.resolve(
            violation.id,
            "operator1",
            "Patient assisted",
        )

        # Assert
        assert result.status == ViolationStatus.RESOLVED
        assert result.resolution_notes == "Patient assisted"

    @pytest.mark.asyncio
    async def test_reopen(
        self,
        mock_db,
        violation_factory,
    ):
        """reopen transitions DISMISSED back to OPEN."""
        # Arrange
        violation = violation_factory(status=ViolationStatus.DISMISSED)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.reopen(violation.id)

        # Assert
        assert result.status == ViolationStatus.OPEN


class TestViolationRetrieval:
    """Tests for violation retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_violation_by_id(
        self,
        mock_db,
        violation_factory,
    ):
        """Retrieves violation by ID."""
        # Arrange
        violation = violation_factory()

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.get_violation_by_id(violation.id)

        # Assert
        assert result == violation

    @pytest.mark.asyncio
    async def test_get_violation_by_id_raises_not_found(
        self,
        mock_db,
    ):
        """Raises ViolationNotFoundError when not found."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act & Assert
        with pytest.raises(ViolationNotFoundError):
            await service.get_violation_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_open_violation(
        self,
        mock_db,
        violation_factory,
    ):
        """Retrieves open violation for device/session/type."""
        # Arrange
        device_id = uuid.uuid4()
        session_id = uuid.uuid4()
        violation = violation_factory(
            device_id=device_id,
            stream_session_id=session_id,
            status=ViolationStatus.OPEN,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = violation
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.get_open_violation(
            device_id,
            session_id,
            ViolationType.FALL_DETECTED,
        )

        # Assert
        assert result == violation

    @pytest.mark.asyncio
    async def test_get_open_violation_returns_none_when_no_match(
        self,
        mock_db,
    ):
        """Returns None when no open violation matches."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.get_open_violation(
            uuid.uuid4(),
            uuid.uuid4(),
            ViolationType.FALL_DETECTED,
        )

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_violations_for_device(
        self,
        mock_db,
        violation_factory,
    ):
        """Retrieves violations for device."""
        # Arrange
        device_id = uuid.uuid4()
        violations = [
            violation_factory(device_id=device_id),
            violation_factory(device_id=device_id),
        ]

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: violations)
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.get_violations_for_device(device_id)

        # Assert
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_open_violations(
        self,
        mock_db,
        violation_factory,
    ):
        """Retrieves all open violations."""
        # Arrange
        violations = [
            violation_factory(status=ViolationStatus.OPEN),
            violation_factory(status=ViolationStatus.REVIEWED),
        ]

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: violations)
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.get_open_violations()

        # Assert
        assert len(result) == 2


class TestHelperMethods:
    """Tests for helper methods."""

    def test_map_event_to_violation_type_fall_detected(self, mock_db):
        """Maps FALL_DETECTED event to FALL_DETECTED violation."""
        service = ViolationService(mock_db)
        result = service._map_event_to_violation_type(EventType.FALL_DETECTED)
        assert result == ViolationType.FALL_DETECTED

    def test_map_event_to_violation_type_returns_none_for_no_fall(self, mock_db):
        """Returns None for NO_FALL event type."""
        service = ViolationService(mock_db)
        result = service._map_event_to_violation_type(EventType.NO_FALL)
        assert result is None

    def test_is_valid_transition_true(self, mock_db):
        """Returns True for valid transitions."""
        service = ViolationService(mock_db)
        assert service.is_valid_transition(
            ViolationStatus.OPEN,
            ViolationStatus.REVIEWED,
        ) is True

    def test_is_valid_transition_false_for_invalid(self, mock_db):
        """Returns False for invalid transitions."""
        service = ViolationService(mock_db)
        assert service.is_valid_transition(
            ViolationStatus.OPEN,
            ViolationStatus.RESOLVED,
        ) is False

    def test_is_valid_transition_false_for_terminal(self, mock_db):
        """Returns False for transitions from terminal state."""
        service = ViolationService(mock_db)
        assert service.is_valid_transition(
            ViolationStatus.RESOLVED,
            ViolationStatus.OPEN,
        ) is False


class TestEventQueries:
    """Tests for violation event query methods."""

    @pytest.mark.asyncio
    async def test_get_events_for_violation(
        self,
        mock_db,
        event_factory,
        violation_factory,
    ):
        """Retrieves events associated with violation."""
        # Arrange
        violation = violation_factory()
        events = [
            event_factory(violation_id=violation.id),
            event_factory(violation_id=violation.id),
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                # Violation lookup
                result.scalar_one_or_none.return_value = violation
            else:
                # Events query
                result.scalars.return_value = MagicMock(all=lambda: events)
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.get_events_for_violation(violation.id)

        # Assert
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_count_events_for_violation(
        self,
        mock_db,
        violation_factory,
    ):
        """Counts events for violation."""
        # Arrange
        violation = violation_factory()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = violation
            else:
                result.scalar_one.return_value = 5
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = ViolationService(mock_db)

        # Act
        result = await service.count_events_for_violation(violation.id)

        # Assert
        assert result == 5

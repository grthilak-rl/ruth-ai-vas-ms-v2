"""Unit tests for EvidenceService.

Tests:
- Snapshot creation via VAS
- Bookmark creation via VAS
- Idempotency (one evidence per violation/type)
- State transitions
- Terminal state enforcement
- Polling behavior
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.vas import (
    VASError,
    VASNotFoundError,
    VASStreamNotLiveError,
)
from app.models import (
    Evidence,
    EvidenceStatus,
    EvidenceType,
    StreamSession,
    StreamState,
    Violation,
    ViolationStatus,
    ViolationType,
)
from app.services.evidence_service import (
    EvidenceService,
    VALID_STATUS_TRANSITIONS,
    TERMINAL_STATES,
)
from app.services.exceptions import (
    EvidenceAlreadyExistsError,
    EvidenceCreationError,
    EvidenceNotFoundError,
    EvidencePollingTimeoutError,
    EvidenceStateError,
    EvidenceTerminalStateError,
    EvidenceVASError,
    NoActiveStreamError,
)


class TestCreateSnapshot:
    """Tests for create_snapshot method."""

    @pytest.mark.asyncio
    async def test_creates_snapshot_and_calls_vas(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        stream_session_factory,
    ):
        """Creates snapshot evidence and triggers VAS API."""
        # Arrange
        device_id = uuid.uuid4()
        session = stream_session_factory(
            device_id=device_id,
            state=StreamState.LIVE,
            vas_stream_id="vas-stream-123",
        )
        violation = violation_factory(
            device_id=device_id,
            stream_session_id=session.id,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                # Check existing evidence
                result.scalar_one_or_none.return_value = None
            else:
                # Stream session query
                result.scalar_one_or_none.return_value = session
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        evidence = await service.create_snapshot(violation)

        # Assert
        assert evidence is not None
        assert evidence.evidence_type == EvidenceType.SNAPSHOT
        assert evidence.status == EvidenceStatus.PROCESSING
        assert evidence.vas_snapshot_id is not None
        assert evidence.violation_id == violation.id

    @pytest.mark.asyncio
    async def test_returns_existing_snapshot_when_allow_existing(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        evidence_factory,
    ):
        """Returns existing snapshot when allow_existing is True."""
        # Arrange
        violation = violation_factory()
        existing = evidence_factory(
            violation_id=violation.id,
            evidence_type=EvidenceType.SNAPSHOT,
            status=EvidenceStatus.READY,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        evidence = await service.create_snapshot(violation, allow_existing=True)

        # Assert
        assert evidence == existing

    @pytest.mark.asyncio
    async def test_raises_already_exists_when_not_allowed(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        evidence_factory,
    ):
        """Raises EvidenceAlreadyExistsError when allow_existing is False."""
        # Arrange
        violation = violation_factory()
        existing = evidence_factory(
            violation_id=violation.id,
            evidence_type=EvidenceType.SNAPSHOT,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(EvidenceAlreadyExistsError) as exc_info:
            await service.create_snapshot(violation, allow_existing=False)

        assert exc_info.value.existing_evidence_id == existing.id

    @pytest.mark.asyncio
    async def test_raises_no_active_stream_on_stream_not_live(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        stream_session_factory,
    ):
        """Raises NoActiveStreamError when VAS stream not live."""
        # Arrange
        device_id = uuid.uuid4()
        session = stream_session_factory(
            device_id=device_id,
            vas_stream_id="vas-stream-123",
        )
        violation = violation_factory(
            device_id=device_id,
            stream_session_id=session.id,
        )

        mock_vas_client.set_failure(
            "create_snapshot",
            VASStreamNotLiveError("Stream not live"),
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = None
            else:
                result.scalar_one_or_none.return_value = session
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(NoActiveStreamError):
            await service.create_snapshot(violation)

    @pytest.mark.asyncio
    async def test_marks_evidence_failed_on_vas_error(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        stream_session_factory,
    ):
        """Marks evidence as FAILED on VAS error."""
        # Arrange
        device_id = uuid.uuid4()
        session = stream_session_factory(
            device_id=device_id,
            vas_stream_id="vas-stream-123",
        )
        violation = violation_factory(
            device_id=device_id,
            stream_session_id=session.id,
        )

        mock_vas_client.set_failure("create_snapshot", VASError("Server error"))

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = None
            else:
                result.scalar_one_or_none.return_value = session
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(EvidenceVASError):
            await service.create_snapshot(violation)

        # Evidence should be added with FAILED status
        added = mock_db.get_added_of_type(Evidence)
        assert len(added) == 1
        assert added[0].status == EvidenceStatus.FAILED


class TestCreateBookmark:
    """Tests for create_bookmark method."""

    @pytest.mark.asyncio
    async def test_creates_bookmark_and_calls_vas(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        stream_session_factory,
    ):
        """Creates bookmark evidence and triggers VAS API."""
        # Arrange
        device_id = uuid.uuid4()
        session = stream_session_factory(
            device_id=device_id,
            state=StreamState.LIVE,
            vas_stream_id="vas-stream-123",
        )
        violation = violation_factory(
            device_id=device_id,
            stream_session_id=session.id,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = None
            else:
                result.scalar_one_or_none.return_value = session
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        evidence = await service.create_bookmark(
            violation,
            before_seconds=5,
            after_seconds=10,
        )

        # Assert
        assert evidence is not None
        assert evidence.evidence_type == EvidenceType.BOOKMARK
        assert evidence.status == EvidenceStatus.PROCESSING
        assert evidence.vas_bookmark_id is not None
        assert evidence.bookmark_duration_seconds == 15  # 5 + 10

    @pytest.mark.asyncio
    async def test_returns_existing_bookmark_when_allow_existing(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        evidence_factory,
    ):
        """Returns existing bookmark when allow_existing is True."""
        # Arrange
        violation = violation_factory()
        existing = evidence_factory(
            violation_id=violation.id,
            evidence_type=EvidenceType.BOOKMARK,
            status=EvidenceStatus.READY,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        evidence = await service.create_bookmark(violation, allow_existing=True)

        # Assert
        assert evidence == existing


class TestStatusTransitions:
    """Tests for evidence status transitions."""

    def test_valid_transitions_from_pending(self):
        """PENDING can transition to PROCESSING or FAILED."""
        valid = VALID_STATUS_TRANSITIONS[EvidenceStatus.PENDING]
        assert EvidenceStatus.PROCESSING in valid
        assert EvidenceStatus.FAILED in valid
        assert EvidenceStatus.READY not in valid

    def test_valid_transitions_from_processing(self):
        """PROCESSING can transition to READY or FAILED."""
        valid = VALID_STATUS_TRANSITIONS[EvidenceStatus.PROCESSING]
        assert EvidenceStatus.READY in valid
        assert EvidenceStatus.FAILED in valid

    def test_ready_is_terminal(self):
        """READY has no valid transitions."""
        valid = VALID_STATUS_TRANSITIONS[EvidenceStatus.READY]
        assert len(valid) == 0
        assert EvidenceStatus.READY in TERMINAL_STATES

    def test_failed_is_terminal(self):
        """FAILED has no valid transitions."""
        valid = VALID_STATUS_TRANSITIONS[EvidenceStatus.FAILED]
        assert len(valid) == 0
        assert EvidenceStatus.FAILED in TERMINAL_STATES


class TestTransitionStatus:
    """Tests for transition_status method."""

    @pytest.mark.asyncio
    async def test_transitions_processing_to_ready(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Transitions evidence from PROCESSING to READY."""
        # Arrange
        evidence = evidence_factory(status=EvidenceStatus.PROCESSING)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = evidence
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        result = await service.transition_status(
            evidence.id,
            EvidenceStatus.READY,
        )

        # Assert
        assert result.status == EvidenceStatus.READY
        assert result.ready_at is not None

    @pytest.mark.asyncio
    async def test_transitions_to_failed_with_error_message(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Transitions to FAILED and sets error message."""
        # Arrange
        evidence = evidence_factory(status=EvidenceStatus.PROCESSING)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = evidence
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        result = await service.transition_status(
            evidence.id,
            EvidenceStatus.FAILED,
            error_message="VAS processing failed",
        )

        # Assert
        assert result.status == EvidenceStatus.FAILED
        assert result.error_message == "VAS processing failed"

    @pytest.mark.asyncio
    async def test_raises_on_invalid_transition(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Raises EvidenceStateError on invalid transition."""
        # Arrange
        evidence = evidence_factory(status=EvidenceStatus.PENDING)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = evidence
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(EvidenceStateError):
            await service.transition_status(
                evidence.id,
                EvidenceStatus.READY,  # Invalid from PENDING
            )

    @pytest.mark.asyncio
    async def test_raises_on_terminal_state(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Raises EvidenceTerminalStateError when in terminal state."""
        # Arrange
        evidence = evidence_factory(status=EvidenceStatus.READY)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = evidence
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(EvidenceTerminalStateError):
            await service.transition_status(
                evidence.id,
                EvidenceStatus.FAILED,
            )


class TestEvidenceRetrieval:
    """Tests for evidence retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_evidence_by_id(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Retrieves evidence by ID."""
        # Arrange
        evidence = evidence_factory()

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = evidence
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        result = await service.get_evidence_by_id(evidence.id)

        # Assert
        assert result == evidence

    @pytest.mark.asyncio
    async def test_get_evidence_by_id_raises_not_found(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Raises EvidenceNotFoundError when not found."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(EvidenceNotFoundError):
            await service.get_evidence_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_evidence_for_violation(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Retrieves all evidence for a violation."""
        # Arrange
        violation_id = uuid.uuid4()
        evidence_list = [
            evidence_factory(
                violation_id=violation_id,
                evidence_type=EvidenceType.SNAPSHOT,
            ),
            evidence_factory(
                violation_id=violation_id,
                evidence_type=EvidenceType.BOOKMARK,
            ),
        ]

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: evidence_list)
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        result = await service.get_evidence_for_violation(violation_id)

        # Assert
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_ready_evidence_for_violation(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Retrieves only ready evidence for violation."""
        # Arrange
        violation_id = uuid.uuid4()
        ready_evidence = evidence_factory(
            violation_id=violation_id,
            status=EvidenceStatus.READY,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [ready_evidence])
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        result = await service.get_ready_evidence_for_violation(violation_id)

        # Assert
        assert len(result) == 1
        assert result[0].status == EvidenceStatus.READY

    @pytest.mark.asyncio
    async def test_get_pending_evidence(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Retrieves pending/processing evidence."""
        # Arrange
        pending = evidence_factory(status=EvidenceStatus.PENDING)
        processing = evidence_factory(status=EvidenceStatus.PROCESSING)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [pending, processing])
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        result = await service.get_pending_evidence()

        # Assert
        assert len(result) == 2


class TestHelperMethods:
    """Tests for helper methods."""

    def test_is_valid_transition_true(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Returns True for valid transitions."""
        service = EvidenceService(mock_vas_client, mock_db)
        assert service.is_valid_transition(
            EvidenceStatus.PENDING,
            EvidenceStatus.PROCESSING,
        ) is True

    def test_is_valid_transition_false_for_invalid(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Returns False for invalid transitions."""
        service = EvidenceService(mock_vas_client, mock_db)
        assert service.is_valid_transition(
            EvidenceStatus.PENDING,
            EvidenceStatus.READY,
        ) is False

    def test_is_valid_transition_false_for_terminal(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Returns False for transitions from terminal state."""
        service = EvidenceService(mock_vas_client, mock_db)
        assert service.is_valid_transition(
            EvidenceStatus.READY,
            EvidenceStatus.FAILED,
        ) is False


class TestRetryFailedEvidence:
    """Tests for retry_failed_evidence method."""

    @pytest.mark.asyncio
    async def test_retries_failed_evidence(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
        violation_factory,
        stream_session_factory,
    ):
        """Retries failed evidence by re-triggering VAS."""
        # Arrange
        device_id = uuid.uuid4()
        session = stream_session_factory(
            device_id=device_id,
            vas_stream_id="vas-stream-123",
        )
        violation = violation_factory(
            device_id=device_id,
            stream_session_id=session.id,
        )
        evidence = evidence_factory(
            violation_id=violation.id,
            evidence_type=EvidenceType.SNAPSHOT,
            status=EvidenceStatus.FAILED,
            retry_count=0,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = evidence
            elif call_count == 1:
                result.scalar_one_or_none.return_value = violation
            else:
                result.scalar_one_or_none.return_value = session
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act
        result = await service.retry_failed_evidence(evidence.id)

        # Assert
        assert result.status == EvidenceStatus.PROCESSING
        assert result.retry_count == 1
        assert result.last_retry_at is not None
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_raises_when_not_failed(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Raises EvidenceCreationError when evidence is not failed."""
        # Arrange
        evidence = evidence_factory(status=EvidenceStatus.READY)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = evidence
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(EvidenceCreationError) as exc_info:
            await service.retry_failed_evidence(evidence.id)

        assert "failed evidence can be retried" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_raises_when_max_retries_exceeded(
        self,
        mock_db,
        mock_vas_client,
        evidence_factory,
    ):
        """Raises EvidenceCreationError when max retries exceeded."""
        # Arrange
        evidence = evidence_factory(
            status=EvidenceStatus.FAILED,
            retry_count=3,  # Already at max
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = evidence
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(EvidenceCreationError) as exc_info:
            await service.retry_failed_evidence(evidence.id, max_retries=3)

        assert "max retries" in str(exc_info.value).lower()


class TestIdempotency:
    """Tests for idempotent evidence creation."""

    @pytest.mark.asyncio
    async def test_only_one_snapshot_per_violation(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        evidence_factory,
    ):
        """Only one snapshot can exist per violation."""
        # Arrange
        violation = violation_factory()
        existing = evidence_factory(
            violation_id=violation.id,
            evidence_type=EvidenceType.SNAPSHOT,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act - should return existing, not create new
        result = await service.create_snapshot(violation, allow_existing=True)

        # Assert
        assert result == existing
        # No new evidence should be added
        assert len(mock_db.get_added_of_type(Evidence)) == 0

    @pytest.mark.asyncio
    async def test_only_one_bookmark_per_violation(
        self,
        mock_db,
        mock_vas_client,
        violation_factory,
        evidence_factory,
    ):
        """Only one bookmark can exist per violation."""
        # Arrange
        violation = violation_factory()
        existing = evidence_factory(
            violation_id=violation.id,
            evidence_type=EvidenceType.BOOKMARK,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing
            return result

        mock_db.execute = mock_execute

        service = EvidenceService(mock_vas_client, mock_db)

        # Act - should return existing, not create new
        result = await service.create_bookmark(violation, allow_existing=True)

        # Assert
        assert result == existing
        # No new evidence should be added
        assert len(mock_db.get_added_of_type(Evidence)) == 0

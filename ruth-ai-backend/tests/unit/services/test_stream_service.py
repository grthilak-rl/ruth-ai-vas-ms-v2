"""Unit tests for StreamService.

Tests:
- Stream lifecycle (start, stop)
- State transitions
- Session management
- Error conditions (VAS failures, invalid transitions)
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.vas import (
    VASError,
    VASNotFoundError,
    VASRTSPError,
)
from app.models import Device, StreamSession, StreamState
from app.services.stream_service import StreamService, VALID_TRANSITIONS
from app.services.exceptions import (
    DeviceNotFoundError,
    StreamAlreadyActiveError,
    StreamNotActiveError,
    StreamSessionNotFoundError,
    StreamStartError,
    StreamStateTransitionError,
    StreamStopError,
)


class TestStreamStart:
    """Tests for start_stream method."""

    @pytest.mark.asyncio
    async def test_start_creates_session_and_calls_vas(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Starting stream creates session and calls VAS."""
        # Arrange
        device = device_factory(vas_device_id="vas-cam-1")

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                # Device query
                result.scalar_one_or_none.return_value = device
            else:
                # Session query - no active session
                result.scalar_one_or_none.return_value = None
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        session = await service.start_stream(device.id)

        # Assert
        assert session is not None
        assert session.device_id == device.id
        assert session.state == StreamState.LIVE
        assert session.vas_stream_id is not None
        assert session.model_id == "fall_detection"

    @pytest.mark.asyncio
    async def test_start_uses_custom_parameters(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Start stream uses custom model parameters."""
        # Arrange
        device = device_factory()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = device
            else:
                result.scalar_one_or_none.return_value = None
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        session = await service.start_stream(
            device.id,
            model_id="custom_model",
            model_version="2.0.0",
            inference_fps=15,
            confidence_threshold=0.8,
        )

        # Assert
        assert session.model_id == "custom_model"
        assert session.model_version == "2.0.0"
        assert session.inference_fps == 15
        assert session.confidence_threshold == 0.8

    @pytest.mark.asyncio
    async def test_start_raises_when_device_not_found(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Raises DeviceNotFoundError when device doesn't exist."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act & Assert
        with pytest.raises(DeviceNotFoundError):
            await service.start_stream(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_start_raises_when_stream_already_active(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
        stream_session_factory,
    ):
        """Raises StreamAlreadyActiveError when stream is already active."""
        # Arrange
        device = device_factory()
        existing_session = stream_session_factory(
            device_id=device.id,
            state=StreamState.LIVE,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = device
            else:
                result.scalar_one_or_none.return_value = existing_session
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act & Assert
        with pytest.raises(StreamAlreadyActiveError) as exc_info:
            await service.start_stream(device.id)

        assert exc_info.value.session_id == existing_session.id

    @pytest.mark.asyncio
    async def test_start_marks_error_on_vas_rtsp_failure(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Marks session as ERROR on VAS RTSP failure."""
        # Arrange
        device = device_factory()
        mock_vas_client.set_failure("start_stream", VASRTSPError("RTSP connection failed"))

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = device
            else:
                result.scalar_one_or_none.return_value = None
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act & Assert
        with pytest.raises(StreamStartError) as exc_info:
            await service.start_stream(device.id)

        assert "RTSP" in str(exc_info.value)

        # Check session was created and marked as error
        added_sessions = mock_db.get_added_of_type(StreamSession)
        assert len(added_sessions) == 1
        assert added_sessions[0].state == StreamState.ERROR

    @pytest.mark.asyncio
    async def test_start_marks_error_on_vas_generic_failure(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Marks session as ERROR on generic VAS failure."""
        # Arrange
        device = device_factory()
        mock_vas_client.set_failure("start_stream", VASError("Server error"))

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = device
            else:
                result.scalar_one_or_none.return_value = None
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act & Assert
        with pytest.raises(StreamStartError):
            await service.start_stream(device.id)


class TestStreamStop:
    """Tests for stop_stream method."""

    @pytest.mark.asyncio
    async def test_stop_transitions_to_stopped(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
        stream_session_factory,
    ):
        """Stopping stream transitions to STOPPED state."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(
            device_id=device.id,
            state=StreamState.LIVE,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                # Active session query
                result.scalar_one_or_none.return_value = session
            else:
                # Device query
                result.scalar_one_or_none.return_value = device
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.stop_stream(device.id)

        # Assert
        assert result.state == StreamState.STOPPED
        assert result.stopped_at is not None

    @pytest.mark.asyncio
    async def test_stop_raises_when_no_active_stream(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Raises StreamNotActiveError when no active stream exists."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act & Assert
        with pytest.raises(StreamNotActiveError):
            await service.stop_stream(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_stop_succeeds_when_vas_stream_not_found(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
        stream_session_factory,
    ):
        """Stop succeeds even if VAS stream already gone."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(
            device_id=device.id,
            state=StreamState.LIVE,
        )
        mock_vas_client.set_failure("stop_stream", VASNotFoundError("Stream not found"))

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = session
            else:
                result.scalar_one_or_none.return_value = device
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.stop_stream(device.id)

        # Assert - should still succeed
        assert result.state == StreamState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_force_ignores_vas_errors(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
        stream_session_factory,
    ):
        """Force stop ignores VAS errors."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(
            device_id=device.id,
            state=StreamState.LIVE,
        )
        mock_vas_client.set_failure("stop_stream", VASError("Server error"))

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = session
            else:
                result.scalar_one_or_none.return_value = device
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.stop_stream(device.id, force=True)

        # Assert - should succeed despite VAS error
        assert result.state == StreamState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_raises_on_vas_error_without_force(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
        stream_session_factory,
    ):
        """Non-force stop raises on VAS error."""
        # Arrange
        device = device_factory()
        session = stream_session_factory(
            device_id=device.id,
            state=StreamState.LIVE,
        )
        mock_vas_client.set_failure("stop_stream", VASError("Server error"))

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = session
            else:
                result.scalar_one_or_none.return_value = device
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act & Assert
        with pytest.raises(StreamStopError):
            await service.stop_stream(device.id, force=False)


class TestStateTransitions:
    """Tests for state transition validation."""

    def test_valid_transitions_from_starting(self):
        """STARTING can transition to LIVE, ERROR, or STOPPED."""
        valid = VALID_TRANSITIONS[StreamState.STARTING]
        assert StreamState.LIVE in valid
        assert StreamState.ERROR in valid
        assert StreamState.STOPPED in valid

    def test_valid_transitions_from_live(self):
        """LIVE can transition to STOPPING or ERROR."""
        valid = VALID_TRANSITIONS[StreamState.LIVE]
        assert StreamState.STOPPING in valid
        assert StreamState.ERROR in valid
        assert StreamState.STOPPED not in valid

    def test_valid_transitions_from_stopping(self):
        """STOPPING can transition to STOPPED or ERROR."""
        valid = VALID_TRANSITIONS[StreamState.STOPPING]
        assert StreamState.STOPPED in valid
        assert StreamState.ERROR in valid

    def test_valid_transitions_from_stopped(self):
        """STOPPED can only transition to STARTING (restart)."""
        valid = VALID_TRANSITIONS[StreamState.STOPPED]
        assert StreamState.STARTING in valid
        assert len(valid) == 1

    def test_valid_transitions_from_error(self):
        """ERROR can transition to STARTING (retry) or STOPPED."""
        valid = VALID_TRANSITIONS[StreamState.ERROR]
        assert StreamState.STARTING in valid
        assert StreamState.STOPPED in valid


class TestSessionRetrieval:
    """Tests for session retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_stream_session_by_id(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Retrieves session by ID."""
        # Arrange
        session = stream_session_factory()

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = session
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.get_stream_session(session.id)

        # Assert
        assert result == session

    @pytest.mark.asyncio
    async def test_get_stream_session_raises_not_found(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Raises StreamSessionNotFoundError when not found."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act & Assert
        with pytest.raises(StreamSessionNotFoundError):
            await service.get_stream_session(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_active_session_for_device(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Retrieves active session for device."""
        # Arrange
        device_id = uuid.uuid4()
        session = stream_session_factory(device_id=device_id, state=StreamState.LIVE)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = session
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.get_active_session_for_device(device_id)

        # Assert
        assert result == session

    @pytest.mark.asyncio
    async def test_get_active_session_returns_none_when_no_active(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Returns None when no active session exists."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.get_active_session_for_device(uuid.uuid4())

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_streams(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Retrieves all active streams."""
        # Arrange
        active_sessions = [
            stream_session_factory(state=StreamState.LIVE),
            stream_session_factory(state=StreamState.STARTING),
        ]

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: active_sessions)
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.get_active_streams()

        # Assert
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_live_streams(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Retrieves only LIVE streams."""
        # Arrange
        live_session = stream_session_factory(state=StreamState.LIVE)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [live_session])
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.get_live_streams()

        # Assert
        assert len(result) == 1
        assert result[0].state == StreamState.LIVE


class TestStreamStatus:
    """Tests for stream status methods."""

    @pytest.mark.asyncio
    async def test_is_stream_active_returns_true(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Returns True when stream is active."""
        # Arrange
        session = stream_session_factory(state=StreamState.LIVE)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = session
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.is_stream_active(session.device_id)

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_is_stream_active_returns_false(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Returns False when no active stream."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.is_stream_active(uuid.uuid4())

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_get_stream_status_active(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Returns status dict for active stream."""
        # Arrange
        session = stream_session_factory(state=StreamState.LIVE)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = session
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        status = await service.get_stream_status(session.device_id)

        # Assert
        assert status["active"] is True
        assert status["session_id"] == str(session.id)
        assert status["state"] == "live"
        assert status["model_id"] == session.model_id

    @pytest.mark.asyncio
    async def test_get_stream_status_inactive(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Returns status dict for inactive device."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        status = await service.get_stream_status(uuid.uuid4())

        # Assert
        assert status["active"] is False
        assert status["session_id"] is None
        assert status["state"] is None


class TestMarkStreamError:
    """Tests for mark_stream_error method."""

    @pytest.mark.asyncio
    async def test_marks_stream_as_error(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Marks active stream as error."""
        # Arrange
        session = stream_session_factory(state=StreamState.LIVE)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = session
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.mark_stream_error(
            session.device_id,
            "Connection lost",
        )

        # Assert
        assert result.state == StreamState.ERROR
        assert "Connection lost" in result.error_message

    @pytest.mark.asyncio
    async def test_mark_error_raises_when_no_active(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Raises StreamNotActiveError when no active stream."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act & Assert
        with pytest.raises(StreamNotActiveError):
            await service.mark_stream_error(uuid.uuid4(), "Error")


class TestRecoverStuckSessions:
    """Tests for recover_stuck_sessions method."""

    @pytest.mark.asyncio
    async def test_recovers_stuck_starting_sessions(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Marks sessions stuck in STARTING as ERROR."""
        # Arrange
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        stuck_session = stream_session_factory(state=StreamState.STARTING)
        stuck_session.updated_at = old_time

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [stuck_session])
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.recover_stuck_sessions()

        # Assert
        assert len(result) == 1
        assert result[0].state == StreamState.ERROR
        assert "stuck" in result[0].error_message.lower()

    @pytest.mark.asyncio
    async def test_recovers_stuck_stopping_sessions(
        self,
        mock_db,
        mock_vas_client,
        stream_session_factory,
    ):
        """Marks sessions stuck in STOPPING as ERROR."""
        # Arrange
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        stuck_session = stream_session_factory(state=StreamState.STOPPING)
        stuck_session.updated_at = old_time

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [stuck_session])
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.recover_stuck_sessions()

        # Assert
        assert len(result) == 1
        assert result[0].state == StreamState.ERROR

    @pytest.mark.asyncio
    async def test_no_recovery_when_no_stuck_sessions(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Returns empty list when no stuck sessions."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [])
            return result

        mock_db.execute = mock_execute

        service = StreamService(mock_vas_client, None, mock_db)

        # Act
        result = await service.recover_stuck_sessions()

        # Assert
        assert result == []

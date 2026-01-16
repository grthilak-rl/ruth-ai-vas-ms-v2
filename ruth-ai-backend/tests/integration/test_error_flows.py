"""Integration tests for Error Flows.

Tests:
- VAS client failures (connection, timeout, etc.)
- Database transaction rollback on failure
- Error response format consistency
- Invalid state transitions
- Resource not found handling
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.integrations.vas import (
    VASAuthenticationError,
    VASConnectionError,
    VASError,
    VASNotFoundError,
    VASRTSPError,
    VASTimeoutError,
)
from app.models import Device, StreamSession, StreamState, Violation, ViolationStatus
from tests.integration.conftest import MockVASClient


class TestVASClientFailures:
    """Tests for VAS client failure handling."""

    @pytest.mark.asyncio
    async def test_vas_connection_error_on_stream_start(
        self,
        client: AsyncClient,
        seeded_device: dict,
        mock_vas_client: MockVASClient,
    ):
        """VAS connection error returns appropriate error response."""
        device_id = seeded_device["id"]
        mock_vas_client.set_failure(
            "start_stream",
            VASConnectionError("Cannot connect to VAS"),
        )

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")

        assert response.status_code == 502
        data = response.json()
        assert data["detail"]["error"] == "stream_start_failed"

    @pytest.mark.asyncio
    async def test_vas_timeout_on_stream_start(
        self,
        client: AsyncClient,
        seeded_device: dict,
        mock_vas_client: MockVASClient,
    ):
        """VAS timeout returns appropriate error response."""
        device_id = seeded_device["id"]
        mock_vas_client.set_failure(
            "start_stream",
            VASTimeoutError("Request timed out"),
        )

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")

        assert response.status_code == 502
        data = response.json()
        assert "error" in data["detail"]

    @pytest.mark.asyncio
    async def test_vas_rtsp_error_on_stream_start(
        self,
        client: AsyncClient,
        seeded_device: dict,
        mock_vas_client: MockVASClient,
    ):
        """VAS RTSP connection error returns 502."""
        device_id = seeded_device["id"]
        mock_vas_client.set_failure(
            "start_stream",
            VASRTSPError("RTSP connection failed", status_code=502),
        )

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")

        assert response.status_code == 502
        data = response.json()
        assert data["detail"]["error"] == "stream_start_failed"

    @pytest.mark.asyncio
    async def test_vas_auth_error_handled(
        self,
        client: AsyncClient,
        seeded_device: dict,
        mock_vas_client: MockVASClient,
    ):
        """VAS authentication error returns appropriate status."""
        device_id = seeded_device["id"]
        mock_vas_client.set_failure(
            "start_stream",
            VASAuthenticationError("Authentication failed"),
        )

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")

        # Internal auth errors manifest as 502 (bad gateway to upstream)
        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_vas_failure_clears_after_retry(
        self,
        client: AsyncClient,
        seeded_device: dict,
        mock_vas_client: MockVASClient,
    ):
        """Clearing VAS failure allows subsequent success."""
        device_id = seeded_device["id"]

        # First call fails
        mock_vas_client.set_failure("start_stream", VASError("Transient error", status_code=500))
        response1 = await client.post(f"/api/v1/devices/{device_id}/start-inference")
        assert response1.status_code == 502

        # Clear failure - should work now
        mock_vas_client.clear_failure("start_stream")
        response2 = await client.post(f"/api/v1/devices/{device_id}/start-inference")
        assert response2.status_code == 200


class TestResourceNotFound:
    """Tests for resource not found error handling."""

    @pytest.mark.asyncio
    async def test_device_not_found(self, client: AsyncClient):
        """Non-existent device returns 404."""
        fake_id = uuid.uuid4()

        response = await client.get(f"/api/v1/devices/{fake_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "device_not_found"

    @pytest.mark.asyncio
    async def test_violation_not_found(self, client: AsyncClient):
        """Non-existent violation returns 404."""
        fake_id = uuid.uuid4()

        response = await client.get(f"/api/v1/violations/{fake_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "violation_not_found"

    @pytest.mark.asyncio
    async def test_start_inference_device_not_found(self, client: AsyncClient):
        """Start inference on non-existent device returns 404."""
        fake_id = uuid.uuid4()

        response = await client.post(f"/api/v1/devices/{fake_id}/start-inference")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "device_not_found"

    @pytest.mark.asyncio
    async def test_stop_inference_device_not_found(self, client: AsyncClient):
        """Stop inference on non-existent device returns 404."""
        fake_id = uuid.uuid4()

        response = await client.post(f"/api/v1/devices/{fake_id}/stop-inference")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "device_not_found"

    @pytest.mark.asyncio
    async def test_snapshot_violation_not_found(self, client: AsyncClient):
        """Snapshot for non-existent violation returns 404."""
        fake_id = uuid.uuid4()

        response = await client.post(f"/api/v1/violations/{fake_id}/snapshot")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "violation_not_found"


class TestInvalidInput:
    """Tests for invalid input handling."""

    @pytest.mark.asyncio
    async def test_invalid_uuid_device(self, client: AsyncClient):
        """Invalid UUID format returns 422."""
        response = await client.get("/api/v1/devices/not-a-uuid")

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_uuid_violation(self, client: AsyncClient):
        """Invalid UUID format for violation returns 422."""
        response = await client.get("/api/v1/violations/not-a-uuid")

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_event_type(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Invalid event type returns 400."""
        payload = event_payload_factory(event_type="invalid_type_here")

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 400
        assert "Invalid event_type" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_required_fields_event(self, client: AsyncClient):
        """Missing required fields returns 422."""
        response = await client.post(
            "/internal/events",
            json={"device_id": str(uuid.uuid4())},  # Missing required fields
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_pagination_params(self, client: AsyncClient):
        """Invalid pagination parameters return 422."""
        response = await client.get("/api/v1/violations?offset=-1")

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_limit_too_large(self, client: AsyncClient):
        """Limit exceeding maximum returns 422."""
        response = await client.get("/api/v1/violations?limit=10000")

        assert response.status_code == 422


class TestErrorResponseFormat:
    """Tests for consistent error response format."""

    @pytest.mark.asyncio
    async def test_404_error_format(self, client: AsyncClient):
        """404 errors have consistent format."""
        fake_id = uuid.uuid4()

        response = await client.get(f"/api/v1/devices/{fake_id}")

        assert response.status_code == 404
        data = response.json()

        # Verify error structure
        assert "detail" in data
        assert "error" in data["detail"]
        assert "message" in data["detail"]

    @pytest.mark.asyncio
    async def test_422_error_format(self, client: AsyncClient):
        """422 errors have consistent format."""
        response = await client.get("/api/v1/devices/not-a-uuid")

        assert response.status_code == 422
        data = response.json()

        # FastAPI validation error format
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_502_error_format(
        self,
        client: AsyncClient,
        seeded_device: dict,
        mock_vas_client: MockVASClient,
    ):
        """502 errors have consistent format."""
        device_id = seeded_device["id"]
        mock_vas_client.set_failure("start_stream", VASError("VAS failed", status_code=500))

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")

        assert response.status_code == 502
        data = response.json()

        # Verify error structure
        assert "detail" in data
        assert "error" in data["detail"]


class TestIdempotentOperations:
    """Tests for idempotent operation behavior."""

    @pytest.mark.asyncio
    async def test_stop_inference_idempotent_no_active(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Stop inference when not active is idempotent (returns 200)."""
        device_id = seeded_device["id"]

        # No active stream - should still return 200
        response = await client.post(f"/api/v1/devices/{device_id}/stop-inference")

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "stopped"
        assert data["session_id"] is None

    @pytest.mark.asyncio
    async def test_stop_inference_idempotent_double_stop(
        self,
        client: AsyncClient,
        seeded_device: dict,
        seeded_stream_session: dict,
    ):
        """Stopping twice is idempotent."""
        device_id = seeded_device["id"]

        # First stop
        response1 = await client.post(f"/api/v1/devices/{device_id}/stop-inference")
        assert response1.status_code == 200

        # Second stop - still succeeds
        response2 = await client.post(f"/api/v1/devices/{device_id}/stop-inference")
        assert response2.status_code == 200
        assert response2.json()["state"] == "stopped"

    @pytest.mark.asyncio
    async def test_start_inference_idempotent(
        self,
        client: AsyncClient,
        seeded_device: dict,
        seeded_stream_session: dict,
    ):
        """Starting inference when already active returns existing session."""
        device_id = seeded_device["id"]
        existing_session_id = seeded_stream_session["id"]

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")

        assert response.status_code == 200
        data = response.json()
        # Returns existing session, not new one
        assert data["session_id"] == str(existing_session_id)


class TestStreamStateTransitions:
    """Tests for stream state transition handling."""

    @pytest.mark.asyncio
    async def test_start_creates_live_session(
        self,
        client: AsyncClient,
        seeded_device: dict,
        test_engine: AsyncEngine,
    ):
        """Starting stream creates session in LIVE state."""
        device_id = seeded_device["id"]

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")
        assert response.status_code == 200
        session_id = response.json()["session_id"]

        # Verify state in database
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            result = await db.execute(
                select(StreamSession).where(StreamSession.id == uuid.UUID(session_id))
            )
            session = result.scalar_one_or_none()
            assert session is not None
            assert session.state == StreamState.LIVE

    @pytest.mark.asyncio
    async def test_stop_transitions_to_stopped(
        self,
        client: AsyncClient,
        seeded_device: dict,
        seeded_stream_session: dict,
        test_engine: AsyncEngine,
    ):
        """Stopping stream transitions to STOPPED state."""
        device_id = seeded_device["id"]
        session_id = seeded_stream_session["id"]

        response = await client.post(f"/api/v1/devices/{device_id}/stop-inference")
        assert response.status_code == 200

        # Verify state in database
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            result = await db.execute(
                select(StreamSession).where(StreamSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            assert session is not None
            assert session.state == StreamState.STOPPED

    @pytest.mark.asyncio
    async def test_restart_after_stop_creates_new_session(
        self,
        client: AsyncClient,
        seeded_device: dict,
        seeded_stream_session: dict,
    ):
        """Restarting after stop creates new session."""
        device_id = seeded_device["id"]
        old_session_id = seeded_stream_session["id"]

        # Stop
        await client.post(f"/api/v1/devices/{device_id}/stop-inference")

        # Restart
        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")
        assert response.status_code == 200

        new_session_id = response.json()["session_id"]
        assert new_session_id != str(old_session_id)


class TestDatabaseRollback:
    """Tests for database transaction rollback on failure."""

    @pytest.mark.asyncio
    async def test_vas_failure_rolls_back_session(
        self,
        client: AsyncClient,
        seeded_device: dict,
        mock_vas_client: MockVASClient,
        test_engine: AsyncEngine,
    ):
        """VAS failure during stream start doesn't leave orphan session."""
        device_id = seeded_device["id"]
        mock_vas_client.set_failure("start_stream", VASError("VAS failed", status_code=500))

        # Count sessions before
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            before_result = await db.execute(
                select(StreamSession).where(StreamSession.device_id == device_id)
            )
            sessions_before = len(list(before_result.scalars().all()))

        # Attempt to start (will fail)
        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")
        assert response.status_code == 502

        # Count sessions after - should be same
        async with session_factory() as db:
            after_result = await db.execute(
                select(StreamSession).where(StreamSession.device_id == device_id)
            )
            sessions_after = len(list(after_result.scalars().all()))

        assert sessions_after == sessions_before


class TestHealthCheck:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_200(self, client: AsyncClient):
        """Health endpoint returns 200 OK."""
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_endpoint_shows_service_name(self, client: AsyncClient):
        """Health endpoint includes service name."""
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert "service" in data

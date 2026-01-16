"""Integration tests for Stream Lifecycle API.

Tests:
- POST /api/v1/devices/{id}/start-inference
- POST /api/v1/devices/{id}/stop-inference
- Stream session creation and persistence
- Idempotent behavior
- VAS error handling
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.integrations.vas import VASError, VASRTSPError
from app.models import StreamSession, StreamState
from tests.integration.conftest import MockVASClient


class TestStartInference:
    """Tests for POST /api/v1/devices/{id}/start-inference."""

    @pytest.mark.asyncio
    async def test_start_inference_creates_session(
        self,
        client: AsyncClient,
        seeded_device: dict,
        test_engine: AsyncEngine,
    ):
        """Starting inference creates a stream session."""
        device_id = seeded_device["id"]

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")

        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == str(device_id)
        assert data["state"] == "live"
        assert data["session_id"] is not None
        assert data["vas_stream_id"] is not None

        # Verify session was persisted
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            result = await db.execute(
                select(StreamSession).where(StreamSession.id == uuid.UUID(data["session_id"]))
            )
            session = result.scalar_one_or_none()
            assert session is not None
            assert session.state == StreamState.LIVE

    @pytest.mark.asyncio
    async def test_start_inference_with_custom_params(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Starting inference with custom parameters."""
        device_id = seeded_device["id"]

        response = await client.post(
            f"/api/v1/devices/{device_id}/start-inference",
            json={
                "model_id": "custom_model",
                "model_version": "2.0.0",
                "inference_fps": 15,
                "confidence_threshold": 0.8,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["model_id"] == "custom_model"

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
        # Should return existing session, not create new one
        assert data["session_id"] == str(existing_session_id)

    @pytest.mark.asyncio
    async def test_start_inference_device_not_found(self, client: AsyncClient):
        """Starting inference on non-existent device returns 404."""
        fake_id = uuid.uuid4()

        response = await client.post(f"/api/v1/devices/{fake_id}/start-inference")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "device_not_found"

    @pytest.mark.asyncio
    async def test_start_inference_vas_failure(
        self,
        client: AsyncClient,
        seeded_device: dict,
        mock_vas_client: MockVASClient,
    ):
        """VAS failure during stream start returns 502."""
        device_id = seeded_device["id"]
        mock_vas_client.set_failure("start_stream", VASRTSPError("RTSP connection failed", status_code=502))

        response = await client.post(f"/api/v1/devices/{device_id}/start-inference")

        assert response.status_code == 502
        data = response.json()
        assert data["detail"]["error"] == "stream_start_failed"


class TestStopInference:
    """Tests for POST /api/v1/devices/{id}/stop-inference."""

    @pytest.mark.asyncio
    async def test_stop_inference_stops_session(
        self,
        client: AsyncClient,
        seeded_device: dict,
        seeded_stream_session: dict,
        test_engine: AsyncEngine,
    ):
        """Stopping inference transitions session to stopped."""
        device_id = seeded_device["id"]
        session_id = seeded_stream_session["id"]

        response = await client.post(f"/api/v1/devices/{device_id}/stop-inference")

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "stopped"
        assert data["session_id"] == str(session_id)

        # Verify session was updated in DB
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
            assert session.stopped_at is not None

    @pytest.mark.asyncio
    async def test_stop_inference_idempotent_no_active_session(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Stopping inference when not active is idempotent success."""
        device_id = seeded_device["id"]

        response = await client.post(f"/api/v1/devices/{device_id}/stop-inference")

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "stopped"
        # No session ID when nothing was active
        assert data["session_id"] is None

    @pytest.mark.asyncio
    async def test_stop_inference_idempotent_double_stop(
        self,
        client: AsyncClient,
        seeded_device: dict,
        seeded_stream_session: dict,
    ):
        """Stopping inference twice is idempotent."""
        device_id = seeded_device["id"]

        # First stop
        response1 = await client.post(f"/api/v1/devices/{device_id}/stop-inference")
        assert response1.status_code == 200

        # Second stop (should still succeed)
        response2 = await client.post(f"/api/v1/devices/{device_id}/stop-inference")
        assert response2.status_code == 200
        data = response2.json()
        assert data["state"] == "stopped"


class TestStreamSessionPersistence:
    """Tests for stream session database persistence."""

    @pytest.mark.asyncio
    async def test_stream_session_has_model_info(
        self,
        client: AsyncClient,
        seeded_device: dict,
        test_engine: AsyncEngine,
    ):
        """Stream session stores model configuration."""
        device_id = seeded_device["id"]

        response = await client.post(
            f"/api/v1/devices/{device_id}/start-inference",
            json={
                "model_id": "test_model",
                "model_version": "3.0.0",
                "inference_fps": 20,
                "confidence_threshold": 0.9,
            },
        )
        assert response.status_code == 200
        session_id = response.json()["session_id"]

        # Verify in database
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
            assert session.model_id == "test_model"
            assert session.model_version == "3.0.0"
            assert session.inference_fps == 20
            assert session.confidence_threshold == 0.9

    @pytest.mark.asyncio
    async def test_stream_session_tracks_timestamps(
        self,
        client: AsyncClient,
        seeded_device: dict,
        test_engine: AsyncEngine,
    ):
        """Stream session tracks start and stop timestamps."""
        device_id = seeded_device["id"]

        # Start stream
        start_response = await client.post(f"/api/v1/devices/{device_id}/start-inference")
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        # Stop stream
        stop_response = await client.post(f"/api/v1/devices/{device_id}/stop-inference")
        assert stop_response.status_code == 200

        # Verify timestamps in database
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
            assert session.started_at is not None
            assert session.stopped_at is not None
            assert session.stopped_at > session.started_at


class TestStreamLifecycleFlow:
    """Tests for complete stream lifecycle."""

    @pytest.mark.asyncio
    async def test_full_stream_lifecycle(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Complete start → stop → restart lifecycle."""
        device_id = seeded_device["id"]

        # Start stream
        start1 = await client.post(f"/api/v1/devices/{device_id}/start-inference")
        assert start1.status_code == 200
        session1_id = start1.json()["session_id"]

        # Stop stream
        stop1 = await client.post(f"/api/v1/devices/{device_id}/stop-inference")
        assert stop1.status_code == 200
        assert stop1.json()["session_id"] == session1_id

        # Restart stream (should create new session)
        start2 = await client.post(f"/api/v1/devices/{device_id}/start-inference")
        assert start2.status_code == 200
        session2_id = start2.json()["session_id"]

        # New session should have different ID
        assert session2_id != session1_id

    @pytest.mark.asyncio
    async def test_stream_status_reflects_state(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Device detail reflects current stream status."""
        device_id = seeded_device["id"]

        # Check status before start
        before = await client.get(f"/api/v1/devices/{device_id}")
        assert before.json()["stream_status"]["active"] is False

        # Start stream
        await client.post(f"/api/v1/devices/{device_id}/start-inference")

        # Check status after start
        during = await client.get(f"/api/v1/devices/{device_id}")
        assert during.json()["stream_status"]["active"] is True
        assert during.json()["stream_status"]["state"] == "live"

        # Stop stream
        await client.post(f"/api/v1/devices/{device_id}/stop-inference")

        # Check status after stop
        after = await client.get(f"/api/v1/devices/{device_id}")
        assert after.json()["stream_status"]["active"] is False

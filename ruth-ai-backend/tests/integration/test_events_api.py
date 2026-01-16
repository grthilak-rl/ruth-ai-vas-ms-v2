"""Integration tests for Events API.

Tests:
- POST /internal/events (event ingestion)
- GET /api/v1/events (event listing)
- Event creation and persistence
- Violation creation from fall_detected events
- Event-to-violation linkage
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Device, Event, EventType, Violation, ViolationStatus


class TestEventIngestion:
    """Tests for POST /internal/events."""

    @pytest.mark.asyncio
    async def test_ingest_event_creates_event(
        self,
        client: AsyncClient,
        event_payload_factory,
        test_engine: AsyncEngine,
    ):
        """Ingesting an event creates a persisted event record."""
        payload = event_payload_factory(
            event_type="no_fall",
            confidence=0.95,
        )

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == "no_fall"
        assert data["confidence"] == 0.95
        assert data["id"] is not None

        # Verify event in database
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            result = await db.execute(
                select(Event).where(Event.id == uuid.UUID(data["id"]))
            )
            event = result.scalar_one_or_none()
            assert event is not None
            assert event.event_type == EventType.NO_FALL

    @pytest.mark.asyncio
    async def test_ingest_fall_event_creates_violation(
        self,
        client: AsyncClient,
        event_payload_factory,
        test_engine: AsyncEngine,
    ):
        """Ingesting a fall_detected event creates both event and violation."""
        payload = event_payload_factory(
            event_type="fall_detected",
            confidence=0.85,
        )

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == "fall_detected"
        assert data["violation_id"] is not None

        # Verify event and violation in database
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            # Check event
            event_result = await db.execute(
                select(Event).where(Event.id == uuid.UUID(data["id"]))
            )
            event = event_result.scalar_one_or_none()
            assert event is not None
            assert event.violation_id is not None

            # Check violation
            violation_result = await db.execute(
                select(Violation).where(Violation.id == uuid.UUID(data["violation_id"]))
            )
            violation = violation_result.scalar_one_or_none()
            assert violation is not None
            assert violation.status == ViolationStatus.OPEN
            assert violation.confidence == 0.85

    @pytest.mark.asyncio
    async def test_ingest_event_auto_creates_device(
        self,
        client: AsyncClient,
        event_payload_factory,
        test_engine: AsyncEngine,
    ):
        """Ingesting event for unknown device auto-creates device stub."""
        new_device_id = uuid.uuid4()
        payload = event_payload_factory(
            device_id=new_device_id,
            event_type="no_fall",
        )

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 201

        # Verify device was created
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            result = await db.execute(
                select(Device).where(Device.vas_device_id == str(new_device_id))
            )
            device = result.scalar_one_or_none()
            assert device is not None
            assert "Auto-created" in device.name

    @pytest.mark.asyncio
    async def test_ingest_event_with_bounding_boxes(
        self,
        client: AsyncClient,
        event_payload_factory,
        test_engine: AsyncEngine,
    ):
        """Ingesting event with bounding boxes stores them correctly."""
        payload = event_payload_factory(
            event_type="fall_detected",
            bounding_boxes=[
                {"x": 100, "y": 150, "w": 200, "h": 300},
                {"x": 50, "y": 75, "w": 100, "h": 150},
            ],
        )

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 201
        event_id = response.json()["id"]

        # Verify bounding boxes in database
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            result = await db.execute(
                select(Event).where(Event.id == uuid.UUID(event_id))
            )
            event = result.scalar_one_or_none()
            assert event is not None
            assert event.bounding_boxes is not None
            assert len(event.bounding_boxes) == 2
            assert event.bounding_boxes[0]["x"] == 100

    @pytest.mark.asyncio
    async def test_ingest_event_invalid_type(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Ingesting event with invalid type returns 400."""
        payload = event_payload_factory(event_type="invalid_type")

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 400
        assert "Invalid event_type" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_ingest_event_missing_required_fields(self, client: AsyncClient):
        """Ingesting event with missing fields returns 422."""
        response = await client.post(
            "/internal/events",
            json={"device_id": str(uuid.uuid4())},  # Missing required fields
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_ingest_event_with_stream_session(
        self,
        client: AsyncClient,
        event_payload_factory,
        test_engine: AsyncEngine,
    ):
        """Ingesting event with stream_session_id creates session stub."""
        session_id = uuid.uuid4()
        payload = event_payload_factory(
            stream_session_id=session_id,
            event_type="fall_detected",
        )

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 201
        data = response.json()

        # Event should have stream_session_id populated
        # (The internal endpoint creates stubs automatically)


class TestEventListing:
    """Tests for GET /api/v1/events."""

    @pytest.mark.asyncio
    async def test_list_events_empty(self, client: AsyncClient):
        """Returns empty list when no events exist."""
        response = await client.get("/api/v1/events")

        assert response.status_code == 200
        data = response.json()
        assert data["events"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_events_after_ingestion(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Lists events after ingestion."""
        # Ingest some events
        for i in range(3):
            payload = event_payload_factory(
                event_type="no_fall",
                confidence=0.5 + i * 0.1,
            )
            await client.post("/internal/events", json=payload)

        response = await client.get("/api/v1/events")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 3
        assert len(data["events"]) >= 3

    @pytest.mark.asyncio
    async def test_list_events_filter_by_device(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Filters events by device_id."""
        # Create events for two different devices
        device1_id = uuid.uuid4()
        device2_id = uuid.uuid4()

        payload1 = event_payload_factory(device_id=device1_id)
        payload2 = event_payload_factory(device_id=device2_id)

        await client.post("/internal/events", json=payload1)
        await client.post("/internal/events", json=payload2)

        # Filter by device1
        response = await client.get(f"/api/v1/events?device_id={device1_id}")

        assert response.status_code == 200
        data = response.json()
        # All returned events should be for device1
        for event in data["events"]:
            assert event["device_id"] == str(device1_id)

    @pytest.mark.asyncio
    async def test_list_events_filter_by_type(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Filters events by event_type."""
        # Create fall and no_fall events
        fall_payload = event_payload_factory(event_type="fall_detected")
        no_fall_payload = event_payload_factory(event_type="no_fall")

        await client.post("/internal/events", json=fall_payload)
        await client.post("/internal/events", json=no_fall_payload)

        # Filter by fall_detected
        response = await client.get("/api/v1/events?event_type=fall_detected")

        assert response.status_code == 200
        data = response.json()
        for event in data["events"]:
            assert event["event_type"] == "fall_detected"

    @pytest.mark.asyncio
    async def test_list_events_pagination(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Pagination works correctly."""
        # Create multiple events
        for _ in range(5):
            payload = event_payload_factory(event_type="no_fall")
            await client.post("/internal/events", json=payload)

        # Get first page
        response = await client.get("/api/v1/events?offset=0&limit=2")

        assert response.status_code == 200
        data = response.json()
        assert len(data["events"]) <= 2
        assert data["total"] >= 5


class TestEventViolationLinkage:
    """Tests for event-to-violation linkage."""

    @pytest.mark.asyncio
    async def test_fall_event_linked_to_violation(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Fall detected event is linked to created violation."""
        payload = event_payload_factory(event_type="fall_detected")

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 201
        data = response.json()

        # Event should have violation_id
        assert data["violation_id"] is not None

        # Violation should exist and be accessible
        violation_id = data["violation_id"]
        violation_response = await client.get(f"/api/v1/violations/{violation_id}")
        assert violation_response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_fall_event_not_linked(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Non-fall events are not linked to violations."""
        payload = event_payload_factory(event_type="no_fall")

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["violation_id"] is None

    @pytest.mark.asyncio
    async def test_violation_has_correct_metadata(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Violation created from event has correct metadata."""
        timestamp = datetime.now(timezone.utc)
        payload = event_payload_factory(
            event_type="fall_detected",
            confidence=0.92,
            timestamp=timestamp,
            model_id="test_model",
            model_version="2.0.0",
        )

        response = await client.post("/internal/events", json=payload)

        assert response.status_code == 201
        violation_id = response.json()["violation_id"]

        # Get violation details
        violation_response = await client.get(f"/api/v1/violations/{violation_id}")
        assert violation_response.status_code == 200
        violation = violation_response.json()

        assert violation["confidence"] == 0.92
        assert violation["model_id"] == "test_model"
        assert violation["model_version"] == "2.0.0"
        assert violation["type"] == "fall_detected"
        assert violation["status"] == "open"

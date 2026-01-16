"""Integration tests for Violations API.

Tests:
- GET /api/v1/violations
- GET /api/v1/violations/{id}
- Violation listing with filtering
- Violation detail with evidence
- Not found handling
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import (
    Evidence,
    EvidenceStatus,
    EvidenceType,
    Violation,
    ViolationStatus,
    ViolationType,
)


class TestListViolations:
    """Tests for GET /api/v1/violations."""

    @pytest.mark.asyncio
    async def test_list_violations_empty(self, client: AsyncClient):
        """Returns empty list when no violations exist."""
        response = await client.get("/api/v1/violations")

        assert response.status_code == 200
        data = response.json()
        assert data["violations"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_violations_returns_seeded(
        self,
        client: AsyncClient,
        seeded_violation: dict,
    ):
        """Returns seeded violation in list."""
        response = await client.get("/api/v1/violations")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

        # Find our seeded violation
        violation_ids = [v["id"] for v in data["violations"]]
        assert str(seeded_violation["id"]) in violation_ids

    @pytest.mark.asyncio
    async def test_list_violations_filter_by_status(
        self,
        client: AsyncClient,
        seeded_device: dict,
        test_engine: AsyncEngine,
    ):
        """Filters violations by status."""
        # Create violations with different statuses
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as db:
            open_violation = Violation(
                device_id=seeded_device["id"],
                type=ViolationType.FALL_DETECTED,
                status=ViolationStatus.OPEN,
                confidence=0.8,
                timestamp=datetime.now(timezone.utc),
                camera_name="Test",
                model_id="test",
                model_version="1.0",
            )
            reviewed_violation = Violation(
                device_id=seeded_device["id"],
                type=ViolationType.FALL_DETECTED,
                status=ViolationStatus.REVIEWED,
                confidence=0.9,
                timestamp=datetime.now(timezone.utc),
                camera_name="Test",
                model_id="test",
                model_version="1.0",
            )
            db.add(open_violation)
            db.add(reviewed_violation)
            await db.commit()

        # Filter by open status
        response = await client.get("/api/v1/violations?status=open")

        assert response.status_code == 200
        data = response.json()
        for violation in data["violations"]:
            assert violation["status"] == "open"

    @pytest.mark.asyncio
    async def test_list_violations_filter_by_device(
        self,
        client: AsyncClient,
        seeded_device: dict,
        test_engine: AsyncEngine,
    ):
        """Filters violations by device_id."""
        device_id = seeded_device["id"]

        # Create a violation for the device
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as db:
            violation = Violation(
                device_id=device_id,
                type=ViolationType.FALL_DETECTED,
                status=ViolationStatus.OPEN,
                confidence=0.85,
                timestamp=datetime.now(timezone.utc),
                camera_name="Test",
                model_id="test",
                model_version="1.0",
            )
            db.add(violation)
            await db.commit()

        # Filter by device
        response = await client.get(f"/api/v1/violations?device_id={device_id}")

        assert response.status_code == 200
        data = response.json()
        for violation in data["violations"]:
            assert violation["camera_id"] == str(device_id)

    @pytest.mark.asyncio
    async def test_list_violations_filter_by_since(
        self,
        client: AsyncClient,
        seeded_device: dict,
        test_engine: AsyncEngine,
    ):
        """Filters violations by timestamp (since)."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(hours=2)
        recent_time = now - timedelta(minutes=30)

        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as db:
            old_violation = Violation(
                device_id=seeded_device["id"],
                type=ViolationType.FALL_DETECTED,
                status=ViolationStatus.OPEN,
                confidence=0.8,
                timestamp=old_time,
                camera_name="Test",
                model_id="test",
                model_version="1.0",
            )
            recent_violation = Violation(
                device_id=seeded_device["id"],
                type=ViolationType.FALL_DETECTED,
                status=ViolationStatus.OPEN,
                confidence=0.9,
                timestamp=recent_time,
                camera_name="Test",
                model_id="test",
                model_version="1.0",
            )
            db.add(old_violation)
            db.add(recent_violation)
            await db.commit()

        # Filter since 1 hour ago
        since = (now - timedelta(hours=1)).isoformat()
        response = await client.get(f"/api/v1/violations?since={since}")

        assert response.status_code == 200
        data = response.json()
        # All returned violations should be after 'since'
        since_dt = now - timedelta(hours=1)
        for violation in data["violations"]:
            ts = datetime.fromisoformat(violation["timestamp"].replace("Z", "+00:00"))
            assert ts >= since_dt

    @pytest.mark.asyncio
    async def test_list_violations_pagination(
        self,
        client: AsyncClient,
        seeded_device: dict,
        test_engine: AsyncEngine,
    ):
        """Pagination works correctly."""
        # Create multiple violations
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as db:
            for i in range(5):
                violation = Violation(
                    device_id=seeded_device["id"],
                    type=ViolationType.FALL_DETECTED,
                    status=ViolationStatus.OPEN,
                    confidence=0.5 + i * 0.1,
                    timestamp=datetime.now(timezone.utc),
                    camera_name="Test",
                    model_id="test",
                    model_version="1.0",
                )
                db.add(violation)
            await db.commit()

        # Get first page
        response = await client.get("/api/v1/violations?offset=0&limit=2")

        assert response.status_code == 200
        data = response.json()
        assert len(data["violations"]) <= 2
        assert data["total"] >= 5


class TestGetViolation:
    """Tests for GET /api/v1/violations/{id}."""

    @pytest.mark.asyncio
    async def test_get_violation_by_id(
        self,
        client: AsyncClient,
        seeded_violation: dict,
    ):
        """Returns violation details."""
        violation_id = seeded_violation["id"]

        response = await client.get(f"/api/v1/violations/{violation_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(violation_id)
        assert data["type"] == "fall_detected"
        assert data["status"] == "open"

    @pytest.mark.asyncio
    async def test_get_violation_includes_evidence(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        test_engine: AsyncEngine,
    ):
        """Violation detail includes associated evidence."""
        violation_id = seeded_violation["id"]

        # Create evidence for the violation
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as db:
            evidence = Evidence(
                violation_id=violation_id,
                evidence_type=EvidenceType.SNAPSHOT,
                status=EvidenceStatus.READY,
                vas_snapshot_id="vas-snap-123",
                requested_at=datetime.now(timezone.utc),
                ready_at=datetime.now(timezone.utc),
            )
            db.add(evidence)
            await db.commit()

        response = await client.get(f"/api/v1/violations/{violation_id}")

        assert response.status_code == 200
        data = response.json()
        assert "evidence" in data
        assert len(data["evidence"]) >= 1
        assert data["evidence"][0]["evidence_type"] == "snapshot"

    @pytest.mark.asyncio
    async def test_get_violation_includes_event_count(
        self,
        client: AsyncClient,
        seeded_violation: dict,
    ):
        """Violation detail includes event count."""
        violation_id = seeded_violation["id"]

        response = await client.get(f"/api/v1/violations/{violation_id}")

        assert response.status_code == 200
        data = response.json()
        assert "event_count" in data

    @pytest.mark.asyncio
    async def test_get_violation_not_found(self, client: AsyncClient):
        """Returns 404 for non-existent violation."""
        fake_id = uuid.uuid4()

        response = await client.get(f"/api/v1/violations/{fake_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "violation_not_found"

    @pytest.mark.asyncio
    async def test_get_violation_invalid_uuid(self, client: AsyncClient):
        """Returns 422 for invalid UUID format."""
        response = await client.get("/api/v1/violations/not-a-uuid")

        assert response.status_code == 422


class TestViolationAttributes:
    """Tests for violation attribute handling."""

    @pytest.mark.asyncio
    async def test_violation_has_all_expected_fields(
        self,
        client: AsyncClient,
        seeded_violation: dict,
    ):
        """Violation detail has all expected fields."""
        violation_id = seeded_violation["id"]

        response = await client.get(f"/api/v1/violations/{violation_id}")

        assert response.status_code == 200
        data = response.json()

        expected_fields = [
            "id",
            "type",
            "status",
            "camera_id",
            "camera_name",
            "confidence",
            "timestamp",
            "model_id",
            "model_version",
            "evidence",
            "event_count",
            "created_at",
            "updated_at",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_violation_list_has_correct_fields(
        self,
        client: AsyncClient,
        seeded_violation: dict,
    ):
        """Violation list items have correct fields."""
        response = await client.get("/api/v1/violations")

        assert response.status_code == 200
        data = response.json()
        assert len(data["violations"]) > 0

        violation = data["violations"][0]
        expected_fields = [
            "id",
            "type",
            "status",
            "camera_id",
            "confidence",
            "timestamp",
        ]
        for field in expected_fields:
            assert field in violation, f"Missing field: {field}"


class TestViolationFromEvent:
    """Tests for violations created from events."""

    @pytest.mark.asyncio
    async def test_violation_created_from_event_accessible(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Violation created from fall event is accessible via API."""
        payload = event_payload_factory(
            event_type="fall_detected",
            confidence=0.88,
        )

        # Create event (and violation)
        event_response = await client.post("/internal/events", json=payload)
        assert event_response.status_code == 201
        violation_id = event_response.json()["violation_id"]

        # Access violation
        response = await client.get(f"/api/v1/violations/{violation_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["confidence"] == 0.88
        assert data["type"] == "fall_detected"
        assert data["status"] == "open"

    @pytest.mark.asyncio
    async def test_violation_appears_in_list(
        self,
        client: AsyncClient,
        event_payload_factory,
    ):
        """Violation created from event appears in violation list."""
        payload = event_payload_factory(event_type="fall_detected")

        # Create event (and violation)
        event_response = await client.post("/internal/events", json=payload)
        violation_id = event_response.json()["violation_id"]

        # Check list
        list_response = await client.get("/api/v1/violations")

        assert list_response.status_code == 200
        data = list_response.json()
        violation_ids = [v["id"] for v in data["violations"]]
        assert violation_id in violation_ids

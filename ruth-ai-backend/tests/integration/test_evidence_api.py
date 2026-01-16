"""Integration tests for Evidence API.

Tests:
- POST /api/v1/violations/{id}/snapshot
- GET /api/v1/violations/{id}/video
- Snapshot creation and idempotency
- Video evidence creation and idempotency
- VAS mocking for evidence creation
- Error handling (no stream, VAS failure)
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.integrations.vas import VASError, VASStreamNotLiveError
from app.models import Evidence, EvidenceStatus, EvidenceType, StreamSession, StreamState
from tests.integration.conftest import MockVASClient


class TestCreateSnapshot:
    """Tests for POST /api/v1/violations/{id}/snapshot."""

    @pytest.mark.asyncio
    async def test_create_snapshot_success(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
        test_engine: AsyncEngine,
    ):
        """Creating snapshot returns evidence info."""
        violation_id = seeded_violation["id"]

        response = await client.post(f"/api/v1/violations/{violation_id}/snapshot")

        assert response.status_code == 201
        data = response.json()
        assert data["violation_id"] == str(violation_id)
        assert data["status"] in ["pending", "processing"]
        assert data["evidence_id"] is not None
        assert data["vas_snapshot_id"] is not None

    @pytest.mark.asyncio
    async def test_create_snapshot_idempotent(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
    ):
        """Creating snapshot twice returns same evidence."""
        violation_id = seeded_violation["id"]

        # First creation
        response1 = await client.post(f"/api/v1/violations/{violation_id}/snapshot")
        assert response1.status_code == 201
        evidence_id1 = response1.json()["evidence_id"]

        # Second creation (should return existing)
        response2 = await client.post(f"/api/v1/violations/{violation_id}/snapshot")
        assert response2.status_code == 201
        evidence_id2 = response2.json()["evidence_id"]

        # Same evidence returned
        assert evidence_id1 == evidence_id2

    @pytest.mark.asyncio
    async def test_create_snapshot_violation_not_found(self, client: AsyncClient):
        """Creating snapshot for non-existent violation returns 404."""
        fake_id = uuid.uuid4()

        response = await client.post(f"/api/v1/violations/{fake_id}/snapshot")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "violation_not_found"

    @pytest.mark.asyncio
    async def test_create_snapshot_no_active_stream(
        self,
        client: AsyncClient,
        seeded_violation: dict,
    ):
        """Creating snapshot without active stream returns 503."""
        violation_id = seeded_violation["id"]
        # No seeded_stream_session fixture - no active stream

        response = await client.post(f"/api/v1/violations/{violation_id}/snapshot")

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["error"] == "no_active_stream"

    @pytest.mark.asyncio
    async def test_create_snapshot_vas_failure(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
        mock_vas_client: MockVASClient,
    ):
        """VAS failure during snapshot creation returns 502."""
        violation_id = seeded_violation["id"]
        mock_vas_client.set_failure("create_snapshot", VASError("VAS unavailable", status_code=500))

        response = await client.post(f"/api/v1/violations/{violation_id}/snapshot")

        assert response.status_code == 502
        data = response.json()
        assert data["detail"]["error"] == "vas_error"

    @pytest.mark.asyncio
    async def test_create_snapshot_persisted_in_database(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
        test_engine: AsyncEngine,
    ):
        """Created snapshot is persisted in database."""
        violation_id = seeded_violation["id"]

        response = await client.post(f"/api/v1/violations/{violation_id}/snapshot")
        assert response.status_code == 201
        evidence_id = response.json()["evidence_id"]

        # Verify in database
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as db:
            result = await db.execute(
                select(Evidence).where(Evidence.id == uuid.UUID(evidence_id))
            )
            evidence = result.scalar_one_or_none()
            assert evidence is not None
            assert evidence.evidence_type == EvidenceType.SNAPSHOT
            assert evidence.violation_id == violation_id


class TestGetVideoEvidence:
    """Tests for GET /api/v1/violations/{id}/video."""

    @pytest.mark.asyncio
    async def test_get_video_creates_bookmark(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
        test_engine: AsyncEngine,
    ):
        """Getting video evidence creates a bookmark."""
        violation_id = seeded_violation["id"]

        response = await client.get(f"/api/v1/violations/{violation_id}/video")

        assert response.status_code == 200
        data = response.json()
        assert data["violation_id"] == str(violation_id)
        assert data["status"] in ["pending", "processing"]
        assert data["evidence_id"] is not None
        assert data["vas_bookmark_id"] is not None

    @pytest.mark.asyncio
    async def test_get_video_idempotent(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
    ):
        """Getting video evidence twice returns same evidence."""
        violation_id = seeded_violation["id"]

        # First call
        response1 = await client.get(f"/api/v1/violations/{violation_id}/video")
        assert response1.status_code == 200
        evidence_id1 = response1.json()["evidence_id"]

        # Second call (should return existing)
        response2 = await client.get(f"/api/v1/violations/{violation_id}/video")
        assert response2.status_code == 200
        evidence_id2 = response2.json()["evidence_id"]

        # Same evidence returned
        assert evidence_id1 == evidence_id2

    @pytest.mark.asyncio
    async def test_get_video_returns_existing_bookmark(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
        test_engine: AsyncEngine,
    ):
        """Getting video returns existing bookmark evidence."""
        violation_id = seeded_violation["id"]

        # Create bookmark evidence manually
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as db:
            evidence = Evidence(
                violation_id=violation_id,
                evidence_type=EvidenceType.BOOKMARK,
                status=EvidenceStatus.PROCESSING,
                vas_bookmark_id="existing-bookmark-123",
                requested_at=datetime.now(timezone.utc),
                bookmark_duration_seconds=15,
            )
            db.add(evidence)
            await db.commit()
            existing_evidence_id = evidence.id

        # Get video - should return existing
        response = await client.get(f"/api/v1/violations/{violation_id}/video")

        assert response.status_code == 200
        data = response.json()
        assert data["evidence_id"] == str(existing_evidence_id)
        assert data["vas_bookmark_id"] == "existing-bookmark-123"

    @pytest.mark.asyncio
    async def test_get_video_violation_not_found(self, client: AsyncClient):
        """Getting video for non-existent violation returns 404."""
        fake_id = uuid.uuid4()

        response = await client.get(f"/api/v1/violations/{fake_id}/video")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "violation_not_found"

    @pytest.mark.asyncio
    async def test_get_video_no_active_stream(
        self,
        client: AsyncClient,
        seeded_violation: dict,
    ):
        """Getting video without active stream returns 503."""
        violation_id = seeded_violation["id"]
        # No seeded_stream_session fixture - no active stream

        response = await client.get(f"/api/v1/violations/{violation_id}/video")

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["error"] == "no_active_stream"

    @pytest.mark.asyncio
    async def test_get_video_vas_failure(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
        mock_vas_client: MockVASClient,
    ):
        """VAS failure during bookmark creation returns 502."""
        violation_id = seeded_violation["id"]
        mock_vas_client.set_failure("create_bookmark", VASError("VAS unavailable", status_code=500))

        response = await client.get(f"/api/v1/violations/{violation_id}/video")

        assert response.status_code == 502
        data = response.json()
        assert data["detail"]["error"] == "vas_error"

    @pytest.mark.asyncio
    async def test_get_video_includes_duration(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
    ):
        """Video evidence includes duration_seconds."""
        violation_id = seeded_violation["id"]

        response = await client.get(f"/api/v1/violations/{violation_id}/video")

        assert response.status_code == 200
        data = response.json()
        assert "duration_seconds" in data
        assert data["duration_seconds"] == 15  # default: 5 before + 10 after


class TestEvidenceInViolationDetail:
    """Tests for evidence in violation detail response."""

    @pytest.mark.asyncio
    async def test_violation_detail_includes_evidence(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
    ):
        """Violation detail includes created evidence."""
        violation_id = seeded_violation["id"]

        # Create snapshot evidence
        await client.post(f"/api/v1/violations/{violation_id}/snapshot")

        # Get violation detail
        response = await client.get(f"/api/v1/violations/{violation_id}")

        assert response.status_code == 200
        data = response.json()
        assert "evidence" in data
        assert len(data["evidence"]) >= 1

        # Find snapshot evidence
        snapshot_evidence = [e for e in data["evidence"] if e["evidence_type"] == "snapshot"]
        assert len(snapshot_evidence) == 1

    @pytest.mark.asyncio
    async def test_violation_detail_shows_evidence_status(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
        test_engine: AsyncEngine,
    ):
        """Violation detail shows evidence with different statuses."""
        violation_id = seeded_violation["id"]

        # Create evidence with different statuses
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as db:
            pending_evidence = Evidence(
                violation_id=violation_id,
                evidence_type=EvidenceType.SNAPSHOT,
                status=EvidenceStatus.PENDING,
                requested_at=datetime.now(timezone.utc),
            )
            ready_evidence = Evidence(
                violation_id=violation_id,
                evidence_type=EvidenceType.BOOKMARK,
                status=EvidenceStatus.READY,
                vas_bookmark_id="ready-bookmark-123",
                requested_at=datetime.now(timezone.utc),
                ready_at=datetime.now(timezone.utc),
                bookmark_duration_seconds=15,
            )
            db.add(pending_evidence)
            db.add(ready_evidence)
            await db.commit()

        # Get violation detail
        response = await client.get(f"/api/v1/violations/{violation_id}")

        assert response.status_code == 200
        data = response.json()

        # Should have both evidence records
        statuses = {e["status"] for e in data["evidence"]}
        assert "pending" in statuses
        assert "ready" in statuses


class TestEvidenceAttributes:
    """Tests for evidence attribute handling."""

    @pytest.mark.asyncio
    async def test_snapshot_response_has_expected_fields(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
    ):
        """Snapshot response has all expected fields."""
        violation_id = seeded_violation["id"]

        response = await client.post(f"/api/v1/violations/{violation_id}/snapshot")

        assert response.status_code == 201
        data = response.json()

        expected_fields = [
            "evidence_id",
            "violation_id",
            "status",
            "vas_snapshot_id",
            "requested_at",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_video_response_has_expected_fields(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
    ):
        """Video evidence response has all expected fields."""
        violation_id = seeded_violation["id"]

        response = await client.get(f"/api/v1/violations/{violation_id}/video")

        assert response.status_code == 200
        data = response.json()

        expected_fields = [
            "evidence_id",
            "violation_id",
            "status",
            "vas_bookmark_id",
            "duration_seconds",
            "requested_at",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_evidence_in_violation_has_expected_fields(
        self,
        client: AsyncClient,
        seeded_violation: dict,
        seeded_stream_session: dict,
    ):
        """Evidence in violation detail has expected fields."""
        violation_id = seeded_violation["id"]

        # Create evidence
        await client.post(f"/api/v1/violations/{violation_id}/snapshot")

        # Get violation detail
        response = await client.get(f"/api/v1/violations/{violation_id}")

        assert response.status_code == 200
        data = response.json()
        assert len(data["evidence"]) >= 1

        evidence = data["evidence"][0]
        expected_fields = [
            "id",
            "violation_id",
            "evidence_type",
            "status",
            "requested_at",
            "created_at",
        ]
        for field in expected_fields:
            assert field in evidence, f"Missing field: {field}"

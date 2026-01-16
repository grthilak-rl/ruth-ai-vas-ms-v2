"""Integration tests for Devices API.

Tests:
- GET /api/v1/devices
- GET /api/v1/devices/{id}
- Device listing with stream status
- Not found handling
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Device, StreamSession, StreamState


class TestListDevices:
    """Tests for GET /api/v1/devices."""

    @pytest.mark.asyncio
    async def test_list_devices_empty(self, client: AsyncClient):
        """Returns empty list when no devices exist."""
        response = await client.get("/api/v1/devices")

        assert response.status_code == 200
        data = response.json()
        assert data["devices"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_devices_returns_seeded_device(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Returns seeded device in list."""
        response = await client.get("/api/v1/devices")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

        # Find our seeded device
        device_ids = [d["id"] for d in data["devices"]]
        assert str(seeded_device["id"]) in device_ids

    @pytest.mark.asyncio
    async def test_list_devices_filters_active_only(
        self,
        client: AsyncClient,
        test_engine: AsyncEngine,
    ):
        """Filters to active devices only by default."""
        # Create one active and one inactive device
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            active_device = Device(
                vas_device_id=f"vas-active-{uuid.uuid4()}",
                name="Active Device",
                is_active=True,
            )
            inactive_device = Device(
                vas_device_id=f"vas-inactive-{uuid.uuid4()}",
                name="Inactive Device",
                is_active=False,
            )
            session.add(active_device)
            session.add(inactive_device)
            await session.commit()

        # Query active only (default)
        response = await client.get("/api/v1/devices?active_only=true")
        assert response.status_code == 200
        data = response.json()

        # Should only contain active devices
        for device in data["devices"]:
            assert device["is_active"] is True

    @pytest.mark.asyncio
    async def test_list_devices_pagination(
        self,
        client: AsyncClient,
        test_engine: AsyncEngine,
    ):
        """Pagination works correctly."""
        # Create multiple devices
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            for i in range(5):
                device = Device(
                    vas_device_id=f"vas-page-{uuid.uuid4()}",
                    name=f"Page Device {i}",
                    is_active=True,
                )
                session.add(device)
            await session.commit()

        # Get first page
        response = await client.get("/api/v1/devices?skip=0&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["devices"]) <= 2
        assert data["total"] >= 5


class TestGetDevice:
    """Tests for GET /api/v1/devices/{id}."""

    @pytest.mark.asyncio
    async def test_get_device_by_id(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Returns device details with stream status."""
        device_id = seeded_device["id"]
        response = await client.get(f"/api/v1/devices/{device_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(device_id)
        assert data["name"] == seeded_device["name"]
        assert "stream_status" in data
        assert data["stream_status"]["active"] is False

    @pytest.mark.asyncio
    async def test_get_device_with_active_stream(
        self,
        client: AsyncClient,
        seeded_device: dict,
        seeded_stream_session: dict,
    ):
        """Returns device with active stream status."""
        device_id = seeded_device["id"]
        response = await client.get(f"/api/v1/devices/{device_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["stream_status"]["active"] is True
        assert data["stream_status"]["state"] == "live"
        assert data["stream_status"]["session_id"] == str(seeded_stream_session["id"])

    @pytest.mark.asyncio
    async def test_get_device_not_found(self, client: AsyncClient):
        """Returns 404 for non-existent device."""
        fake_id = uuid.uuid4()
        response = await client.get(f"/api/v1/devices/{fake_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "device_not_found"

    @pytest.mark.asyncio
    async def test_get_device_invalid_uuid(self, client: AsyncClient):
        """Returns 422 for invalid UUID format."""
        response = await client.get("/api/v1/devices/not-a-uuid")

        assert response.status_code == 422


class TestDeviceVasDeviceId:
    """Tests for device VAS ID handling."""

    @pytest.mark.asyncio
    async def test_device_has_vas_device_id(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Device response includes VAS device ID."""
        device_id = seeded_device["id"]
        response = await client.get(f"/api/v1/devices/{device_id}")

        assert response.status_code == 200
        data = response.json()
        assert "vas_device_id" in data
        assert data["vas_device_id"] == seeded_device["vas_device_id"]


class TestDeviceAttributes:
    """Tests for device attribute handling."""

    @pytest.mark.asyncio
    async def test_device_has_all_expected_fields(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Device response has all expected fields."""
        device_id = seeded_device["id"]
        response = await client.get(f"/api/v1/devices/{device_id}")

        assert response.status_code == 200
        data = response.json()

        expected_fields = [
            "id",
            "vas_device_id",
            "name",
            "description",
            "location",
            "is_active",
            "last_synced_at",
            "stream_status",
            "created_at",
            "updated_at",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_device_list_has_correct_fields(
        self,
        client: AsyncClient,
        seeded_device: dict,
    ):
        """Device list items have correct fields."""
        response = await client.get("/api/v1/devices")

        assert response.status_code == 200
        data = response.json()
        assert len(data["devices"]) > 0

        device = data["devices"][0]
        expected_fields = [
            "id",
            "vas_device_id",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        for field in expected_fields:
            assert field in device, f"Missing field: {field}"

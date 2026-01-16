"""Unit tests for DeviceService.

Tests:
- Device sync from VAS (idempotent)
- Device retrieval by ID and VAS ID
- Active/inactive device handling
- Error conditions (VAS failures, not found)
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.vas import (
    VASConnectionError,
    VASError,
    VASNotFoundError,
)
from app.integrations.vas import Device as VASDevice, DeviceStatus
from app.models import Device
from app.services.device_service import DeviceService
from app.services.exceptions import (
    DeviceInactiveError,
    DeviceNotFoundError,
    DeviceSyncError,
)


class TestDeviceSyncFromVAS:
    """Tests for sync_devices_from_vas method."""

    @pytest.mark.asyncio
    async def test_sync_creates_new_devices(
        self,
        mock_db,
        mock_vas_client,
        vas_device_factory,
    ):
        """New VAS devices are created in local database."""
        # Arrange
        vas_devices = [
            vas_device_factory(id="vas-001", name="Camera 1"),
            vas_device_factory(id="vas-002", name="Camera 2"),
        ]
        mock_vas_client.set_devices(vas_devices)

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.sync_devices_from_vas()

        # Assert
        assert len(result) == 2
        added_devices = mock_db.get_added_of_type(Device)
        assert len(added_devices) == 2
        assert added_devices[0].vas_device_id == "vas-001"
        assert added_devices[1].vas_device_id == "vas-002"

    @pytest.mark.asyncio
    async def test_sync_is_idempotent(
        self,
        mock_db,
        mock_vas_client,
        vas_device_factory,
        device_factory,
    ):
        """Syncing same device twice does not create duplicates."""
        # Arrange
        vas_device = vas_device_factory(id="vas-001", name="Camera 1")
        mock_vas_client.set_devices([vas_device])

        # Existing device in DB
        existing = device_factory(vas_device_id="vas-001", name="Old Name")

        # Mock the execute to return existing device
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing
            result.scalars.return_value = MagicMock(all=lambda: [existing])
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.sync_devices_from_vas()

        # Assert
        assert len(result) == 1
        # Device name should be updated
        assert existing.name == "Camera 1"

    @pytest.mark.asyncio
    async def test_sync_marks_missing_devices_inactive(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Devices not in VAS are marked inactive."""
        # Arrange
        mock_vas_client.set_devices([])  # Empty VAS

        existing = device_factory(vas_device_id="vas-orphan", is_active=True)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value = MagicMock(all=lambda: [existing])
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        await service.sync_devices_from_vas()

        # Assert
        assert existing.is_active is False

    @pytest.mark.asyncio
    async def test_sync_raises_on_vas_connection_error(
        self,
        mock_db,
        mock_vas_client,
    ):
        """VAS connection failure raises DeviceSyncError."""
        # Arrange
        mock_vas_client.set_failure(
            "get_devices",
            VASConnectionError("Connection refused"),
        )

        service = DeviceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(DeviceSyncError) as exc_info:
            await service.sync_devices_from_vas()

        assert "Cannot connect to VAS" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_sync_raises_on_vas_error(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Generic VAS error raises DeviceSyncError."""
        # Arrange
        mock_vas_client.set_failure(
            "get_devices",
            VASError("Server error"),
        )

        service = DeviceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(DeviceSyncError) as exc_info:
            await service.sync_devices_from_vas()

        assert "VAS error during device sync" in str(exc_info.value)


class TestGetDeviceById:
    """Tests for get_device_by_id method."""

    @pytest.mark.asyncio
    async def test_returns_device_when_found(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Returns device when it exists."""
        # Arrange
        device = device_factory(name="Test Camera")
        device_id = device.id

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = device
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.get_device_by_id(device_id)

        # Assert
        assert result == device

    @pytest.mark.asyncio
    async def test_raises_not_found_when_missing(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Raises DeviceNotFoundError when device does not exist."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)
        device_id = uuid.uuid4()

        # Act & Assert
        with pytest.raises(DeviceNotFoundError) as exc_info:
            await service.get_device_by_id(device_id)

        assert str(device_id) in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_inactive_error_when_require_active(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Raises DeviceInactiveError when device is inactive and required active."""
        # Arrange
        device = device_factory(is_active=False)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = device
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(DeviceInactiveError):
            await service.get_device_by_id(device.id, require_active=True)

    @pytest.mark.asyncio
    async def test_returns_inactive_device_when_not_required(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Returns inactive device when require_active is False."""
        # Arrange
        device = device_factory(is_active=False)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = device
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.get_device_by_id(device.id, require_active=False)

        # Assert
        assert result == device
        assert result.is_active is False


class TestGetDeviceByVasId:
    """Tests for get_device_by_vas_id method."""

    @pytest.mark.asyncio
    async def test_returns_device_by_vas_id(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Returns device by VAS device ID."""
        # Arrange
        device = device_factory(vas_device_id="vas-test-123")

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = device
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.get_device_by_vas_id("vas-test-123")

        # Assert
        assert result == device
        assert result.vas_device_id == "vas-test-123"

    @pytest.mark.asyncio
    async def test_raises_not_found_for_unknown_vas_id(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Raises DeviceNotFoundError for unknown VAS ID."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(DeviceNotFoundError) as exc_info:
            await service.get_device_by_vas_id("unknown-vas-id")

        assert "unknown-vas-id" in str(exc_info.value)


class TestEnsureDeviceExists:
    """Tests for ensure_device_exists method."""

    @pytest.mark.asyncio
    async def test_returns_existing_device(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Returns existing device without VAS call."""
        # Arrange
        device = device_factory(vas_device_id="vas-existing")

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = device
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.ensure_device_exists("vas-existing")

        # Assert
        assert result == device

    @pytest.mark.asyncio
    async def test_fetches_from_vas_when_not_local(
        self,
        mock_db,
        mock_vas_client,
        vas_device_factory,
    ):
        """Fetches from VAS and creates local record when not found locally."""
        # Arrange
        vas_device = vas_device_factory(id="vas-new", name="New Camera")
        mock_vas_client.set_devices([vas_device])

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                # First call - device not found locally
                result.scalar_one_or_none.return_value = None
            else:
                # Subsequent calls return the device
                result.scalar_one_or_none.return_value = None
            result.scalars.return_value = MagicMock(all=lambda: [])
            call_count += 1
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.ensure_device_exists("vas-new")

        # Assert
        assert result is not None
        assert result.vas_device_id == "vas-new"
        assert result.name == "New Camera"

    @pytest.mark.asyncio
    async def test_raises_not_found_when_vas_missing(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Raises DeviceNotFoundError when device not in VAS."""
        # Arrange
        mock_vas_client.set_devices([])  # Empty VAS

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(DeviceNotFoundError):
            await service.ensure_device_exists("vas-nonexistent")


class TestListDevices:
    """Tests for list_devices method."""

    @pytest.mark.asyncio
    async def test_lists_active_devices_by_default(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Lists only active devices by default."""
        # Arrange
        active_device = device_factory(is_active=True)
        inactive_device = device_factory(is_active=False)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [active_device])
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.list_devices()

        # Assert
        assert len(result) == 1
        assert result[0].is_active is True

    @pytest.mark.asyncio
    async def test_lists_all_devices_when_not_active_only(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Lists all devices when active_only is False."""
        # Arrange
        active = device_factory(is_active=True)
        inactive = device_factory(is_active=False)

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: [active, inactive])
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.list_devices(active_only=False)

        # Assert
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_respects_pagination(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Respects skip and limit pagination parameters."""
        # Arrange
        devices = [device_factory() for _ in range(10)]

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value = MagicMock(all=lambda: devices[5:8])
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.list_devices(skip=5, limit=3)

        # Assert
        assert len(result) == 3


class TestCountDevices:
    """Tests for count_devices method."""

    @pytest.mark.asyncio
    async def test_counts_active_devices(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Counts active devices by default."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one.return_value = 5
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.count_devices()

        # Assert
        assert result == 5

    @pytest.mark.asyncio
    async def test_counts_all_devices_when_not_active_only(
        self,
        mock_db,
        mock_vas_client,
    ):
        """Counts all devices when active_only is False."""
        # Arrange
        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one.return_value = 10
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.count_devices(active_only=False)

        # Assert
        assert result == 10


class TestRefreshDeviceStatus:
    """Tests for refresh_device_status method."""

    @pytest.mark.asyncio
    async def test_updates_device_from_vas(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
        vas_device_factory,
    ):
        """Refreshes device status from VAS."""
        # Arrange
        device = device_factory(
            vas_device_id="vas-refresh",
            name="Old Name",
        )
        vas_device = vas_device_factory(
            id="vas-refresh",
            name="Updated Name",
            location="New Location",
        )
        mock_vas_client.set_devices([vas_device])

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = device
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.refresh_device_status(device.id)

        # Assert
        assert result.name == "Updated Name"
        assert result.location == "New Location"
        assert result.last_synced_at is not None

    @pytest.mark.asyncio
    async def test_marks_inactive_when_vas_not_found(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Marks device inactive when removed from VAS."""
        # Arrange
        device = device_factory(
            vas_device_id="vas-deleted",
            is_active=True,
        )
        mock_vas_client.set_devices([])  # Device not in VAS

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = device
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act
        result = await service.refresh_device_status(device.id)

        # Assert
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_raises_sync_error_on_vas_failure(
        self,
        mock_db,
        mock_vas_client,
        device_factory,
    ):
        """Raises DeviceSyncError on VAS failure."""
        # Arrange
        device = device_factory(vas_device_id="vas-error")
        mock_vas_client.set_failure("get_device", VASError("Server error"))

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = device
            return result

        mock_db.execute = mock_execute

        service = DeviceService(mock_vas_client, mock_db)

        # Act & Assert
        with pytest.raises(DeviceSyncError):
            await service.refresh_device_status(device.id)

"""
VAS-MS-V2 Device Management Integration Tests

Tests cover:
- Device listing
- Device details
- RTSP URL validation
- Device status
"""

import pytest
from vas_client import VASClient, VASError, Device


@pytest.mark.device
class TestDeviceListing:
    """Device listing tests"""

    def test_list_devices(self, authenticated_client: VASClient):
        """
        Test: GET /api/v1/devices
        Expected: 200 OK with list of devices
        """
        devices = authenticated_client.list_devices()

        assert isinstance(devices, list)
        # May be empty list if no devices configured
        for device in devices:
            assert isinstance(device, Device)
            assert device.id is not None
            assert device.name is not None
            assert device.rtsp_url is not None

    def test_list_devices_with_pagination(self, authenticated_client: VASClient):
        """
        Test: GET /api/v1/devices with skip and limit
        Expected: 200 OK with paginated results
        """
        # Get first page
        page1 = authenticated_client.list_devices(skip=0, limit=2)
        assert isinstance(page1, list)
        assert len(page1) <= 2

        # Get second page
        page2 = authenticated_client.list_devices(skip=2, limit=2)
        assert isinstance(page2, list)

        # If we have enough devices, pages should be different
        if len(page1) == 2 and len(page2) > 0:
            page1_ids = {d.id for d in page1}
            page2_ids = {d.id for d in page2}
            assert page1_ids.isdisjoint(page2_ids), "Pagination should return different devices"


@pytest.mark.device
class TestDeviceDetails:
    """Device details tests"""

    def test_get_device_by_id(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: GET /api/v1/devices/{device_id}
        Expected: 200 OK with device details
        """
        if not test_device_id:
            pytest.skip("No test device available")

        device = authenticated_client.get_device(test_device_id)

        assert device is not None
        assert isinstance(device, Device)
        assert device.id == test_device_id
        assert device.name is not None
        assert device.rtsp_url is not None
        assert device.created_at is not None

    def test_get_device_not_found(self, authenticated_client: VASClient):
        """
        Test: GET /api/v1/devices/{invalid_id}
        Expected: 404 Not Found
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.get_device("00000000-0000-0000-0000-000000000000")

        assert exc_info.value.status_code == 404

    def test_device_status(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: GET /api/v1/devices/{device_id}/status
        Expected: 200 OK with device status including streaming info
        """
        if not test_device_id:
            pytest.skip("No test device available")

        status = authenticated_client.get_device_status(test_device_id)

        assert status is not None
        assert "device_id" in status
        assert status["device_id"] == test_device_id
        # Streaming info should be present
        assert "streaming" in status or "is_active" in status


@pytest.mark.device
class TestDeviceValidation:
    """RTSP URL validation tests"""

    def test_validate_rtsp_url_format(self, authenticated_client: VASClient):
        """
        Test: POST /api/v1/devices/validate with invalid RTSP URL format
        Expected: 200 OK with valid=false
        """
        result = authenticated_client.validate_device(
            name="test-invalid-url",
            rtsp_url="not-a-valid-url",
        )

        assert result is not None
        assert result.valid is False
        assert result.error is not None

    def test_validate_rtsp_unreachable(self, authenticated_client: VASClient):
        """
        Test: POST /api/v1/devices/validate with unreachable RTSP URL
        Expected: 200 OK with valid=false (connection failed)
        """
        result = authenticated_client.validate_device(
            name="test-unreachable",
            rtsp_url="rtsp://192.168.255.255:554/stream",  # Non-routable IP
        )

        assert result is not None
        # Should fail due to connection timeout/refused
        assert result.valid is False


@pytest.mark.device
class TestDeviceFields:
    """Device field validation tests"""

    def test_device_has_required_fields(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: Device object contains all required fields
        """
        if not test_device_id:
            pytest.skip("No test device available")

        device = authenticated_client.get_device(test_device_id)

        # Required fields
        assert device.id is not None
        assert device.name is not None
        assert device.rtsp_url is not None
        assert device.created_at is not None

        # Optional fields should have proper types
        assert isinstance(device.is_active, bool)
        assert device.description is None or isinstance(device.description, str)
        assert device.location is None or isinstance(device.location, str)

    def test_device_rtsp_url_format(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: Device RTSP URL follows expected format
        """
        if not test_device_id:
            pytest.skip("No test device available")

        device = authenticated_client.get_device(test_device_id)

        # RTSP URL should start with rtsp:// or rtsps://
        assert device.rtsp_url.startswith("rtsp://") or device.rtsp_url.startswith("rtsps://")

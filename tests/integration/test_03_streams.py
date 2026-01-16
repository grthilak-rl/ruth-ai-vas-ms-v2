"""
VAS-MS-V2 Stream Management Integration Tests

Tests cover:
- Stream start/stop lifecycle
- Stream state machine transitions
- Stream listing and filtering
- Stream health monitoring
- Router capabilities
"""

import pytest
import time
from vas_client import VASClient, VASError, Stream, StreamState


@pytest.mark.stream
class TestStreamLifecycle:
    """Stream lifecycle tests"""

    def test_start_stream(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: POST /api/v1/devices/{device_id}/start-stream
        Expected: 200 OK with stream info, v2_stream_id
        """
        if not test_device_id:
            pytest.skip("No test device available")

        try:
            response = authenticated_client.start_stream(test_device_id)

            assert response is not None
            assert response.status == "success"
            assert response.device_id == test_device_id
            # Use effective_stream_id to handle different field names
            assert response.effective_stream_id is not None

            # Store stream_id for cleanup
            stream_id = response.effective_stream_id

        finally:
            # Cleanup: stop stream
            try:
                authenticated_client.stop_stream(test_device_id)
            except Exception:
                pass

    def test_start_stream_idempotent(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: Starting already-started stream returns existing stream
        Expected: 200 OK with reconnect=true
        """
        if not test_device_id:
            pytest.skip("No test device available")

        try:
            # Start stream first time
            response1 = authenticated_client.start_stream(test_device_id)
            stream_id1 = response1.effective_stream_id

            # Start again - should return existing stream
            response2 = authenticated_client.start_stream(test_device_id)
            stream_id2 = response2.effective_stream_id

            # Should be same stream with reconnect flag
            assert stream_id1 == stream_id2
            assert response2.reconnect is True

        finally:
            try:
                authenticated_client.stop_stream(test_device_id)
            except Exception:
                pass

    def test_stop_stream(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: POST /api/v1/devices/{device_id}/stop-stream
        Expected: 200 OK with stopped=true
        """
        if not test_device_id:
            pytest.skip("No test device available")

        # Start stream first
        authenticated_client.start_stream(test_device_id)

        # Stop stream
        response = authenticated_client.stop_stream(test_device_id)

        assert response is not None
        assert response.status == "success"
        assert response.device_id == test_device_id
        assert response.stopped is True

    def test_stop_stream_not_running(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: Stopping a stream that's not running
        Expected: Should handle gracefully (either 200 OK or specific error)
        """
        if not test_device_id:
            pytest.skip("No test device available")

        # Ensure stream is stopped first
        try:
            authenticated_client.stop_stream(test_device_id)
        except Exception:
            pass

        # Try to stop again
        try:
            response = authenticated_client.stop_stream(test_device_id)
            # If it succeeds, stopped should be false or response indicates no-op
            assert response is not None
        except VASError as e:
            # Some implementations may return 409 or similar
            assert e.status_code in [200, 404, 409]


@pytest.mark.stream
class TestStreamStateTransitions:
    """Stream state machine tests"""

    @pytest.mark.slow
    def test_stream_reaches_live_state(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: Stream transitions to LIVE state
        Expected: INITIALIZING -> READY -> LIVE
        """
        if not test_device_id:
            pytest.skip("No test device available")

        try:
            # Start stream
            response = authenticated_client.start_stream(test_device_id)
            stream_id = response.effective_stream_id

            # Wait for LIVE state
            stream = authenticated_client.wait_for_stream_live(stream_id, timeout=30.0)

            # Compare case-insensitively
            assert stream.state.value.lower() == "live"

        finally:
            try:
                authenticated_client.stop_stream(test_device_id)
            except Exception:
                pass

    def test_stream_state_after_stop(self, authenticated_client: VASClient, test_device_id: str):
        """
        Test: Stream state after stopping
        Expected: State becomes STOPPED or CLOSED
        """
        if not test_device_id:
            pytest.skip("No test device available")

        # Start and wait for LIVE
        response = authenticated_client.start_stream(test_device_id)
        stream_id = response.effective_stream_id

        try:
            authenticated_client.wait_for_stream_live(stream_id, timeout=30.0)
        except VASError:
            pass

        # Stop stream
        authenticated_client.stop_stream(test_device_id)

        # Check state - may need small delay
        time.sleep(1)

        try:
            stream = authenticated_client.get_stream(stream_id)
            # Compare case-insensitively
            assert stream.state.value.lower() in ["stopped", "closed"]
        except VASError as e:
            # Stream might be deleted/closed
            assert e.status_code == 404


@pytest.mark.stream
class TestStreamListing:
    """Stream listing and filtering tests"""

    def test_list_streams(self, authenticated_client: VASClient):
        """
        Test: GET /v2/streams
        Expected: 200 OK with streams list and pagination
        """
        response = authenticated_client.list_streams()

        assert response is not None
        assert hasattr(response, "streams")
        assert hasattr(response, "pagination")
        assert isinstance(response.streams, list)

    def test_list_streams_filter_by_state(self, authenticated_client: VASClient):
        """
        Test: GET /v2/streams?state=LIVE
        Expected: Only returns streams in LIVE state
        """
        response = authenticated_client.list_streams(state=StreamState.LIVE)

        for stream in response.streams:
            assert stream.state == StreamState.LIVE

    def test_list_streams_pagination(self, authenticated_client: VASClient):
        """
        Test: GET /v2/streams with limit and offset
        Expected: Pagination works correctly
        """
        response = authenticated_client.list_streams(limit=5, offset=0)

        assert response.pagination is not None
        assert "limit" in response.pagination
        assert "offset" in response.pagination
        assert response.pagination["limit"] == 5
        assert response.pagination["offset"] == 0


@pytest.mark.stream
@pytest.mark.requires_stream
class TestStreamDetails:
    """Stream details tests (requires active stream)"""

    def test_get_stream_details(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/streams/{stream_id}
        Expected: 200 OK with full stream details
        """
        stream_id = active_stream["stream_id"]
        stream = authenticated_client.get_stream(stream_id)

        assert stream is not None
        assert stream.id == stream_id
        assert stream.camera_id is not None
        assert stream.state is not None
        assert stream.created_at is not None

    def test_get_stream_not_found(self, authenticated_client: VASClient):
        """
        Test: GET /v2/streams/{invalid_id}
        Expected: 404 Not Found
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.get_stream("00000000-0000-0000-0000-000000000000")

        assert exc_info.value.status_code == 404


@pytest.mark.stream
@pytest.mark.requires_stream
class TestStreamHealth:
    """Stream health monitoring tests"""

    def test_get_stream_health(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/streams/{stream_id}/health
        Expected: 200 OK with health status

        Actual API response format:
        {
            "status": "healthy" | "degraded" | "unhealthy",
            "state": "live" | "stopped" | etc.,
            "producer": {...} | null,
            "consumers": {"active": N, "total": N, ...},
            "ffmpeg": {"status": "running"} | null,
            "recording": {...} | null
        }
        """
        stream_id = active_stream["stream_id"]
        health = authenticated_client.get_stream_health(stream_id)

        assert health is not None
        assert health.status in ["healthy", "degraded", "unhealthy"]
        assert health.state is not None
        # Use healthy property which checks status field
        assert isinstance(health.healthy, bool)

    def test_stream_health_response_fields(self, authenticated_client: VASClient, active_stream):
        """
        Test: Health response contains expected fields
        """
        stream_id = active_stream["stream_id"]
        health = authenticated_client.get_stream_health(stream_id)

        # Check required fields are present
        assert health.status is not None
        assert health.state is not None

        # Check optional fields have correct types when present
        if health.consumers is not None:
            assert isinstance(health.consumers, dict)
            # Consumer counts
            if "active" in health.consumers:
                assert isinstance(health.consumers["active"], int)

        if health.ffmpeg is not None:
            assert isinstance(health.ffmpeg, dict)
            if "status" in health.ffmpeg:
                assert health.ffmpeg["status"] in ["running", "stopped", "error"]


@pytest.mark.stream
@pytest.mark.requires_stream
class TestRouterCapabilities:
    """Router capabilities tests (required for WebRTC)"""

    def test_get_router_capabilities(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/streams/{stream_id}/router-capabilities
        Expected: 200 OK with RTP capabilities for mediasoup
        """
        stream_id = active_stream["stream_id"]
        capabilities = authenticated_client.get_router_capabilities(stream_id)

        assert capabilities is not None
        assert "rtp_capabilities" in capabilities or "codecs" in capabilities

        # Check for video codec support
        rtp_caps = capabilities.get("rtp_capabilities", capabilities)
        if "codecs" in rtp_caps:
            codecs = rtp_caps["codecs"]
            assert len(codecs) > 0

            # Should have H264 video codec
            video_codecs = [c for c in codecs if c.get("kind") == "video"]
            assert len(video_codecs) > 0

            h264_codecs = [c for c in video_codecs if "H264" in c.get("mimeType", "")]
            assert len(h264_codecs) > 0, "H264 codec should be available"

    def test_router_capabilities_codec_params(self, authenticated_client: VASClient, active_stream):
        """
        Test: Router capabilities contain valid codec parameters
        """
        stream_id = active_stream["stream_id"]
        capabilities = authenticated_client.get_router_capabilities(stream_id)

        rtp_caps = capabilities.get("rtp_capabilities", capabilities)
        codecs = rtp_caps.get("codecs", [])

        for codec in codecs:
            assert "mimeType" in codec
            assert "clockRate" in codec
            # Video codecs should have 90000 clock rate
            if codec.get("kind") == "video":
                assert codec["clockRate"] == 90000

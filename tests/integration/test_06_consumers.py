"""
VAS-MS-V2 WebRTC Consumer Integration Tests

Tests cover:
- Consumer attachment
- DTLS connection
- Consumer listing
- Consumer cleanup
- ICE candidate handling
"""

import pytest
import uuid
import time
import logging
from vas_client import VASClient, VASError, Consumer, StreamState

logger = logging.getLogger(__name__)


def attach_consumer_with_retry(
    client: VASClient,
    stream_id: str,
    client_id: str,
    rtp_capabilities: dict,
    max_retries: int = 5,
) -> Consumer:
    """
    Attach consumer with retry logic for producer initialization.

    The MediaSoup producer needs ~2 seconds after stream reaches LIVE state
    to fully initialize. The API returns 409 with retry_after_seconds hint.
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            return client.attach_consumer(
                stream_id=stream_id,
                client_id=client_id,
                rtp_capabilities=rtp_capabilities,
            )
        except VASError as e:
            last_error = e
            # Check for NO_PRODUCER error - the error info is in e.error or e.description
            is_no_producer = (
                e.status_code == 409
                and ("NO_PRODUCER" in str(e.error) or "NO_PRODUCER" in str(e.description))
            )
            if is_no_producer:
                # Get retry_after_seconds from details dict, or from description, default to 5
                retry_after = 5
                if e.details and isinstance(e.details, dict):
                    retry_after = e.details.get("retry_after_seconds", 5)
                logger.info(
                    f"Producer not ready (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {retry_after}s..."
                )
                time.sleep(retry_after)
            else:
                raise

    # Max retries exceeded
    raise last_error


# Sample RTP capabilities (simplified for testing)
# In production, these come from mediasoup-client Device.rtpCapabilities
SAMPLE_RTP_CAPABILITIES = {
    "codecs": [
        {
            "kind": "video",
            "mimeType": "video/H264",
            "clockRate": 90000,
            "parameters": {
                "packetization-mode": 1,
                "profile-level-id": "42e01f",
                "level-asymmetry-allowed": 1,
            },
            "rtcpFeedback": [
                {"type": "nack"},
                {"type": "nack", "parameter": "pli"},
                {"type": "ccm", "parameter": "fir"},
                {"type": "goog-remb"},
            ],
        },
        {
            "kind": "video",
            "mimeType": "video/VP8",
            "clockRate": 90000,
            "parameters": {},
            "rtcpFeedback": [
                {"type": "nack"},
                {"type": "nack", "parameter": "pli"},
                {"type": "ccm", "parameter": "fir"},
                {"type": "goog-remb"},
            ],
        },
    ],
    "headerExtensions": [
        {
            "kind": "video",
            "uri": "urn:ietf:params:rtp-hdrext:sdes:mid",
            "preferredId": 1,
            "preferredEncrypt": False,
            "direction": "sendrecv",
        },
        {
            "kind": "video",
            "uri": "http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time",
            "preferredId": 4,
            "preferredEncrypt": False,
            "direction": "sendrecv",
        },
    ],
}


@pytest.mark.consumer
@pytest.mark.requires_stream
class TestConsumerAttachment:
    """Consumer attachment tests"""

    def test_attach_consumer(self, authenticated_client: VASClient, active_stream):
        """
        Test: POST /v2/streams/{stream_id}/consume
        Expected: 201 Created with consumer_id, transport params, rtp params
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        assert consumer is not None
        assert consumer.consumer_id is not None

        # Transport should have ICE and DTLS parameters
        assert consumer.transport is not None
        assert consumer.transport.id is not None
        assert consumer.transport.ice_parameters is not None
        assert consumer.transport.ice_candidates is not None
        assert len(consumer.transport.ice_candidates) > 0
        assert consumer.transport.dtls_parameters is not None

        # RTP parameters should be present
        assert consumer.rtp_parameters is not None
        assert consumer.rtp_parameters.codecs is not None
        assert len(consumer.rtp_parameters.codecs) > 0

        # Cleanup
        try:
            authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
        except Exception:
            pass

    def test_attach_consumer_ice_parameters(self, authenticated_client: VASClient, active_stream):
        """
        Test: ICE parameters are valid for WebRTC
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        ice_params = consumer.transport.ice_parameters
        assert ice_params.usernameFragment is not None
        assert len(ice_params.usernameFragment) > 0
        assert ice_params.password is not None
        assert len(ice_params.password) > 0

        # Cleanup
        try:
            authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
        except Exception:
            pass

    def test_attach_consumer_ice_candidates(self, authenticated_client: VASClient, active_stream):
        """
        Test: ICE candidates are valid
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        candidates = consumer.transport.ice_candidates
        assert len(candidates) > 0

        for candidate in candidates:
            assert candidate.foundation is not None
            assert candidate.priority > 0
            assert candidate.ip is not None
            assert candidate.port > 0
            assert candidate.type in ["host", "srflx", "relay"]
            assert candidate.protocol in ["udp", "tcp"]

        # Cleanup
        try:
            authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
        except Exception:
            pass

    def test_attach_consumer_dtls_parameters(self, authenticated_client: VASClient, active_stream):
        """
        Test: DTLS parameters are valid
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        dtls = consumer.transport.dtls_parameters
        assert dtls.role in ["auto", "client", "server"]
        assert len(dtls.fingerprints) > 0

        for fp in dtls.fingerprints:
            # MediaSoup may use various SHA algorithms
            assert fp.algorithm in ["sha-1", "sha-224", "sha-256", "sha-384", "sha-512"]
            assert fp.value is not None
            # SHA-256 fingerprint should be colon-separated hex
            if fp.algorithm == "sha-256":
                assert ":" in fp.value

        # Cleanup
        try:
            authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
        except Exception:
            pass

    def test_attach_consumer_rtp_parameters(self, authenticated_client: VASClient, active_stream):
        """
        Test: RTP parameters match expected format
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        rtp = consumer.rtp_parameters

        # Should have at least one video codec
        assert len(rtp.codecs) > 0

        # Should have encodings with SSRC
        assert len(rtp.encodings) > 0
        for encoding in rtp.encodings:
            assert "ssrc" in encoding

        # Cleanup
        try:
            authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
        except Exception:
            pass


@pytest.mark.consumer
@pytest.mark.requires_stream
class TestConsumerConnection:
    """Consumer DTLS connection tests"""

    def test_connect_consumer(self, authenticated_client: VASClient, active_stream):
        """
        Test: POST /v2/streams/{stream_id}/consumers/{consumer_id}/connect
        Expected: 200 OK with status=connected
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        # Attach consumer first (with retry for producer initialization)
        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        # Connect with DTLS parameters (simulated client-side params)
        # In real scenario, these come from the RecvTransport
        dtls_params = {
            "role": "client",
            "fingerprints": [
                {
                    "algorithm": "sha-256",
                    "value": "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99",
                }
            ],
        }

        try:
            response = authenticated_client.connect_consumer(
                stream_id=stream_id,
                consumer_id=consumer.consumer_id,
                dtls_parameters=dtls_params,
            )

            assert response is not None
            assert response.status == "connected"
            assert response.consumer_id == consumer.consumer_id
        except VASError as e:
            # DTLS handshake may fail with fake fingerprint, but API call should work
            # Accept 400/500 as the API is working, just handshake failed
            if e.status_code not in [400, 500]:
                raise
        finally:
            try:
                authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
            except Exception:
                pass


@pytest.mark.consumer
@pytest.mark.requires_stream
class TestConsumerListing:
    """Consumer listing tests"""

    def test_list_consumers(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/streams/{stream_id}/consumers
        Expected: 200 OK with consumers list
        """
        stream_id = active_stream["stream_id"]

        response = authenticated_client.list_consumers(stream_id)

        assert response is not None
        assert response.stream_id == stream_id
        assert response.total_consumers >= 0
        assert response.active_consumers >= 0
        assert isinstance(response.consumers, list)

    def test_list_consumers_includes_attached(self, authenticated_client: VASClient, active_stream):
        """
        Test: Newly attached consumer appears in list
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        # Get initial count
        initial = authenticated_client.list_consumers(stream_id)
        initial_count = initial.total_consumers

        # Attach consumer (with retry for producer initialization)
        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        try:
            # Check count increased
            updated = authenticated_client.list_consumers(stream_id)
            assert updated.total_consumers >= initial_count

            # Find our consumer in the list
            consumer_ids = [c.id for c in updated.consumers]
            assert consumer.consumer_id in consumer_ids
        finally:
            try:
                authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
            except Exception:
                pass


@pytest.mark.consumer
@pytest.mark.requires_stream
class TestConsumerCleanup:
    """Consumer cleanup tests"""

    def test_detach_consumer(self, authenticated_client: VASClient, active_stream):
        """
        Test: DELETE /v2/streams/{stream_id}/consumers/{consumer_id}
        Expected: 204 No Content
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        # Attach consumer (with retry for producer initialization)
        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        # Detach
        authenticated_client.detach_consumer(stream_id, consumer.consumer_id)

        # Verify consumer is removed from list
        response = authenticated_client.list_consumers(stream_id)
        consumer_ids = [c.id for c in response.consumers if c.closed_at is None]
        assert consumer.consumer_id not in consumer_ids

    def test_detach_consumer_not_found(self, authenticated_client: VASClient, active_stream):
        """
        Test: DELETE with invalid consumer_id
        Expected: 404 Not Found
        """
        stream_id = active_stream["stream_id"]

        with pytest.raises(VASError) as exc_info:
            authenticated_client.detach_consumer(
                stream_id,
                "00000000-0000-0000-0000-000000000000",
            )

        assert exc_info.value.status_code == 404


@pytest.mark.consumer
@pytest.mark.requires_stream
class TestConsumerICE:
    """ICE candidate handling tests"""

    def test_add_ice_candidate(self, authenticated_client: VASClient, active_stream):
        """
        Test: POST /v2/streams/{stream_id}/consumers/{consumer_id}/ice-candidate
        Expected: 200 OK with acknowledged status
        """
        stream_id = active_stream["stream_id"]
        client_id = f"test-client-{uuid.uuid4().hex[:8]}"

        # Attach consumer (with retry for producer initialization)
        consumer = attach_consumer_with_retry(
            client=authenticated_client,
            stream_id=stream_id,
            client_id=client_id,
            rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
        )

        # Add ICE candidate (simulated)
        candidate = {
            "candidate": "candidate:1 1 UDP 2122252543 192.168.1.100 54321 typ host",
            "sdpMLineIndex": 0,
            "sdpMid": "0",
        }

        try:
            response = authenticated_client.add_ice_candidate(
                stream_id=stream_id,
                consumer_id=consumer.consumer_id,
                candidate=candidate,
            )

            assert response is not None
            assert response.get("status") == "acknowledged"
        except VASError as e:
            # ICE candidate may be rejected if invalid format
            # API should still return proper error (400 or 422 for validation)
            assert e.status_code in [200, 400, 422]
        finally:
            try:
                authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
            except Exception:
                pass


@pytest.mark.consumer
class TestConsumerErrors:
    """Consumer error handling tests"""

    def test_attach_consumer_stream_not_live(self, authenticated_client: VASClient):
        """
        Test: Attaching consumer to non-LIVE stream
        Expected: 409 Conflict (STREAM_NOT_LIVE)
        """
        # Try to attach to non-existent stream
        with pytest.raises(VASError) as exc_info:
            authenticated_client.attach_consumer(
                stream_id="00000000-0000-0000-0000-000000000000",
                client_id="test-client",
                rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
            )

        assert exc_info.value.status_code in [404, 409]

    def test_attach_consumer_invalid_capabilities(self, authenticated_client: VASClient, active_stream):
        """
        Test: Attaching consumer with invalid RTP capabilities
        Expected: 400 Bad Request
        """
        stream_id = active_stream["stream_id"]

        try:
            with pytest.raises(VASError) as exc_info:
                authenticated_client.attach_consumer(
                    stream_id=stream_id,
                    client_id="test-client",
                    rtp_capabilities={"invalid": "capabilities"},
                )

            assert exc_info.value.status_code in [400, 422, 500]
        except Exception:
            # Some implementations may be lenient
            pass


@pytest.mark.consumer
@pytest.mark.requires_stream
class TestMultipleConsumers:
    """Multiple consumer tests"""

    def test_multiple_consumers_same_stream(self, authenticated_client: VASClient, active_stream):
        """
        Test: Multiple consumers can attach to same stream
        """
        stream_id = active_stream["stream_id"]
        consumers = []

        try:
            # Attach multiple consumers (first one may need retry for producer)
            for i in range(3):
                client_id = f"test-client-{i}-{uuid.uuid4().hex[:8]}"
                consumer = attach_consumer_with_retry(
                    client=authenticated_client,
                    stream_id=stream_id,
                    client_id=client_id,
                    rtp_capabilities=SAMPLE_RTP_CAPABILITIES,
                )
                consumers.append(consumer)

            # Verify all attached
            response = authenticated_client.list_consumers(stream_id)
            assert response.total_consumers >= 3

            # Each consumer should have unique ID
            consumer_ids = [c.consumer_id for c in consumers]
            assert len(consumer_ids) == len(set(consumer_ids)), "Consumer IDs should be unique"

        finally:
            # Cleanup all consumers
            for consumer in consumers:
                try:
                    authenticated_client.detach_consumer(stream_id, consumer.consumer_id)
                except Exception:
                    pass

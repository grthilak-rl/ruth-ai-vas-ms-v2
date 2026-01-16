"""
VAS-MS-V2 Snapshot Integration Tests

Tests cover:
- Live snapshot creation
- Historical snapshot creation
- Snapshot async processing
- Snapshot retrieval and download
- Snapshot deletion
"""

import pytest
import time
from datetime import datetime, timedelta
from vas_client import VASClient, VASError, Snapshot, ProcessingStatus


@pytest.mark.snapshot
@pytest.mark.requires_stream
class TestSnapshotCreation:
    """Snapshot creation tests"""

    def test_create_live_snapshot(self, authenticated_client: VASClient, active_stream):
        """
        Test: POST /v2/streams/{stream_id}/snapshots (source=live)
        Expected: 201 Created with snapshot info, status=processing
        """
        stream_id = active_stream["stream_id"]

        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="integration-test",
            metadata={"test": True, "purpose": "integration-test"},
        )

        assert snapshot is not None
        assert snapshot.id is not None
        assert snapshot.stream_id == stream_id
        assert snapshot.source.value == "live"
        assert snapshot.created_by == "integration-test"
        assert snapshot.format == "jpg"
        assert snapshot.created_at is not None

        # Cleanup
        try:
            authenticated_client.delete_snapshot(snapshot.id)
        except Exception:
            pass

    def test_create_snapshot_returns_processing_status(self, authenticated_client: VASClient, active_stream):
        """
        Test: New snapshot starts in processing status
        Expected: status=processing on creation
        """
        stream_id = active_stream["stream_id"]

        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="integration-test",
        )

        # Initial status should be processing
        assert snapshot.status == ProcessingStatus.PROCESSING

        # Cleanup
        try:
            authenticated_client.delete_snapshot(snapshot.id)
        except Exception:
            pass

    def test_create_snapshot_with_metadata(self, authenticated_client: VASClient, active_stream):
        """
        Test: Snapshot creation with custom metadata
        Expected: Metadata preserved in response
        """
        stream_id = active_stream["stream_id"]
        custom_metadata = {
            "violation_type": "speeding",
            "confidence": 0.95,
            "vehicle_id": "ABC123",
        }

        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="ruth-ai",
            metadata=custom_metadata,
        )

        assert snapshot.metadata is not None
        assert snapshot.metadata.get("violation_type") == "speeding"
        assert snapshot.metadata.get("confidence") == 0.95

        # Cleanup
        try:
            authenticated_client.delete_snapshot(snapshot.id)
        except Exception:
            pass


@pytest.mark.snapshot
@pytest.mark.requires_stream
@pytest.mark.slow
class TestSnapshotAsyncProcessing:
    """Snapshot async processing tests"""

    def test_snapshot_becomes_ready(self, authenticated_client: VASClient, active_stream):
        """
        Test: Snapshot transitions to ready status
        Expected: processing -> ready within timeout
        """
        stream_id = active_stream["stream_id"]

        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="integration-test",
        )

        # Wait for ready
        ready_snapshot = authenticated_client.wait_for_snapshot_ready(
            snapshot.id,
            timeout=10.0,
        )

        assert ready_snapshot.status == ProcessingStatus.READY
        assert ready_snapshot.image_url is not None or ready_snapshot.file_size is not None

        # Cleanup
        try:
            authenticated_client.delete_snapshot(snapshot.id)
        except Exception:
            pass

    def test_snapshot_has_dimensions_when_ready(self, authenticated_client: VASClient, active_stream):
        """
        Test: Ready snapshot has width, height, file_size
        """
        stream_id = active_stream["stream_id"]

        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="integration-test",
        )

        ready_snapshot = authenticated_client.wait_for_snapshot_ready(
            snapshot.id,
            timeout=10.0,
        )

        # Should have image dimensions
        assert ready_snapshot.width is not None or ready_snapshot.file_size is not None

        # Cleanup
        try:
            authenticated_client.delete_snapshot(snapshot.id)
        except Exception:
            pass


@pytest.mark.snapshot
@pytest.mark.requires_stream
class TestSnapshotRetrieval:
    """Snapshot retrieval tests"""

    def test_get_snapshot_by_id(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/snapshots/{snapshot_id}
        Expected: 200 OK with snapshot details
        """
        stream_id = active_stream["stream_id"]

        # Create snapshot
        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="integration-test",
        )

        # Retrieve by ID
        retrieved = authenticated_client.get_snapshot(snapshot.id)

        assert retrieved is not None
        assert retrieved.id == snapshot.id
        assert retrieved.stream_id == stream_id

        # Cleanup
        try:
            authenticated_client.delete_snapshot(snapshot.id)
        except Exception:
            pass

    def test_get_snapshot_not_found(self, authenticated_client: VASClient):
        """
        Test: GET /v2/snapshots/{invalid_id}
        Expected: 404 Not Found
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.get_snapshot("00000000-0000-0000-0000-000000000000")

        assert exc_info.value.status_code == 404

    @pytest.mark.slow
    def test_download_snapshot_image(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/snapshots/{snapshot_id}/image
        Expected: 200 OK with JPEG binary data
        """
        stream_id = active_stream["stream_id"]

        # Create and wait for ready
        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="integration-test",
        )

        authenticated_client.wait_for_snapshot_ready(snapshot.id, timeout=10.0)

        # Download image
        image_data = authenticated_client.get_snapshot_image(snapshot.id)

        assert image_data is not None
        assert len(image_data) > 0
        # JPEG magic bytes
        assert image_data[:2] == b'\xff\xd8', "Should be valid JPEG"

        # Cleanup
        try:
            authenticated_client.delete_snapshot(snapshot.id)
        except Exception:
            pass


@pytest.mark.snapshot
class TestSnapshotListing:
    """Snapshot listing tests"""

    def test_list_snapshots(self, authenticated_client: VASClient):
        """
        Test: GET /v2/snapshots
        Expected: 200 OK with snapshots list and pagination
        """
        response = authenticated_client.list_snapshots()

        assert response is not None
        assert hasattr(response, "snapshots")
        assert hasattr(response, "pagination")
        assert isinstance(response.snapshots, list)

    def test_list_snapshots_filter_by_stream(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/snapshots?stream_id={stream_id}
        Expected: Only returns snapshots for specified stream
        """
        stream_id = active_stream["stream_id"]

        # Create a snapshot first
        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="integration-test",
        )

        try:
            response = authenticated_client.list_snapshots(stream_id=stream_id)

            for s in response.snapshots:
                assert s.stream_id == stream_id
        finally:
            try:
                authenticated_client.delete_snapshot(snapshot.id)
            except Exception:
                pass

    def test_list_snapshots_filter_by_created_by(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/snapshots?created_by={created_by}
        """
        stream_id = active_stream["stream_id"]
        created_by = "filter-test-user"

        # Create snapshot with specific created_by
        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by=created_by,
        )

        try:
            response = authenticated_client.list_snapshots(created_by=created_by)

            for s in response.snapshots:
                assert s.created_by == created_by
        finally:
            try:
                authenticated_client.delete_snapshot(snapshot.id)
            except Exception:
                pass


@pytest.mark.snapshot
@pytest.mark.requires_stream
class TestSnapshotDeletion:
    """Snapshot deletion tests"""

    def test_delete_snapshot(self, authenticated_client: VASClient, active_stream):
        """
        Test: DELETE /v2/snapshots/{snapshot_id}
        Expected: 204 No Content
        """
        stream_id = active_stream["stream_id"]

        # Create snapshot
        snapshot = authenticated_client.create_snapshot(
            stream_id=stream_id,
            source="live",
            created_by="integration-test",
        )

        # Delete it
        authenticated_client.delete_snapshot(snapshot.id)

        # Verify it's gone
        with pytest.raises(VASError) as exc_info:
            authenticated_client.get_snapshot(snapshot.id)

        assert exc_info.value.status_code == 404

    def test_delete_snapshot_not_found(self, authenticated_client: VASClient):
        """
        Test: DELETE /v2/snapshots/{invalid_id}
        Expected: 404 Not Found
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.delete_snapshot("00000000-0000-0000-0000-000000000000")

        assert exc_info.value.status_code == 404


@pytest.mark.snapshot
@pytest.mark.requires_stream
class TestSnapshotStreamNotLive:
    """Tests for snapshot creation when stream is not live"""

    def test_create_snapshot_stream_not_live(self, authenticated_client: VASClient):
        """
        Test: Creating snapshot on non-existent stream
        Expected: 404 or 409 error
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.create_snapshot(
                stream_id="00000000-0000-0000-0000-000000000000",
                source="live",
                created_by="integration-test",
            )

        assert exc_info.value.status_code in [404, 409]

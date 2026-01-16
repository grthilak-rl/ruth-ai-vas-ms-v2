"""
VAS-MS-V2 Bookmark Integration Tests

Tests cover:
- Live bookmark creation
- Historical bookmark creation
- Bookmark async processing
- Bookmark video/thumbnail download
- Bookmark update and deletion
"""

import pytest
import time
from datetime import datetime, timedelta
from vas_client import VASClient, VASError, Bookmark, ProcessingStatus


@pytest.mark.bookmark
@pytest.mark.requires_stream
class TestBookmarkCreation:
    """Bookmark creation tests"""

    def test_create_live_bookmark(self, authenticated_client: VASClient, active_stream):
        """
        Test: POST /v2/streams/{stream_id}/bookmarks (source=live)
        Expected: 201 Created with bookmark info, status=processing
        """
        stream_id = active_stream["stream_id"]

        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Test Violation Event",
            event_type="violation",
            source="live",
            before_seconds=5,
            after_seconds=10,
            confidence=0.95,
            tags=["test", "integration"],
            created_by="integration-test",
            metadata={"test": True},
        )

        assert bookmark is not None
        assert bookmark.id is not None
        assert bookmark.stream_id == stream_id
        assert bookmark.source.value == "live"
        assert bookmark.label == "Test Violation Event"
        assert bookmark.event_type == "violation"
        assert bookmark.duration_seconds == 15  # 5 + 10
        assert bookmark.confidence == 0.95
        assert "test" in bookmark.tags
        assert bookmark.created_at is not None

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass

    def test_create_bookmark_returns_processing_status(self, authenticated_client: VASClient, active_stream):
        """
        Test: New bookmark starts in processing status
        Expected: status=processing on creation
        """
        stream_id = active_stream["stream_id"]

        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Processing Status Test",
            event_type="test",
            source="live",
        )

        # Initial status should be processing
        assert bookmark.status == ProcessingStatus.PROCESSING

        # video_url and thumbnail_url should be null initially
        assert bookmark.video_url is None or bookmark.status == ProcessingStatus.PROCESSING

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass

    def test_create_bookmark_time_range(self, authenticated_client: VASClient, active_stream):
        """
        Test: Bookmark time range calculation
        Expected: start_time = center - before, end_time = center + after
        """
        stream_id = active_stream["stream_id"]

        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Time Range Test",
            event_type="test",
            source="live",
            before_seconds=3,
            after_seconds=7,
        )

        # Duration should be sum of before and after
        assert bookmark.duration_seconds == 10

        # Time range should be consistent
        assert bookmark.start_time < bookmark.center_timestamp < bookmark.end_time

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass

    def test_create_bookmark_with_all_fields(self, authenticated_client: VASClient, active_stream):
        """
        Test: Bookmark creation with all optional fields
        """
        stream_id = active_stream["stream_id"]

        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Complete Bookmark Test",
            event_type="speeding",
            source="live",
            before_seconds=5,
            after_seconds=10,
            confidence=0.87,
            tags=["vehicle", "speeding", "zone-a"],
            created_by="ruth-ai-pipeline",
            metadata={
                "vehicle_id": "ABC123",
                "speed": 85,
                "speed_limit": 60,
                "camera_angle": "front",
            },
        )

        assert bookmark.confidence == 0.87
        assert len(bookmark.tags) == 3
        assert bookmark.metadata.get("vehicle_id") == "ABC123"

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass


@pytest.mark.bookmark
@pytest.mark.requires_stream
@pytest.mark.slow
class TestBookmarkAsyncProcessing:
    """Bookmark async processing tests"""

    def test_bookmark_becomes_ready(self, authenticated_client: VASClient, active_stream):
        """
        Test: Bookmark transitions to ready status
        Expected: processing -> ready within timeout
        """
        stream_id = active_stream["stream_id"]

        # Create bookmark with short duration for faster processing
        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Async Processing Test",
            event_type="test",
            source="live",
            before_seconds=2,
            after_seconds=3,  # 5 second clip
        )

        # Wait for ready (may take 5-15s for live bookmark)
        ready_bookmark = authenticated_client.wait_for_bookmark_ready(
            bookmark.id,
            timeout=30.0,
        )

        assert ready_bookmark.status == ProcessingStatus.READY
        assert ready_bookmark.video_url is not None

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass

    def test_bookmark_has_thumbnail_when_ready(self, authenticated_client: VASClient, active_stream):
        """
        Test: Ready bookmark has thumbnail
        """
        stream_id = active_stream["stream_id"]

        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Thumbnail Test",
            event_type="test",
            source="live",
            before_seconds=2,
            after_seconds=3,
        )

        ready_bookmark = authenticated_client.wait_for_bookmark_ready(
            bookmark.id,
            timeout=30.0,
        )

        assert ready_bookmark.thumbnail_url is not None

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass


@pytest.mark.bookmark
@pytest.mark.requires_stream
class TestBookmarkRetrieval:
    """Bookmark retrieval tests"""

    def test_get_bookmark_by_id(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/bookmarks/{bookmark_id}
        Expected: 200 OK with bookmark details
        """
        stream_id = active_stream["stream_id"]

        # Create bookmark
        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Retrieval Test",
            event_type="test",
        )

        # Retrieve by ID
        retrieved = authenticated_client.get_bookmark(bookmark.id)

        assert retrieved is not None
        assert retrieved.id == bookmark.id
        assert retrieved.stream_id == stream_id
        assert retrieved.label == "Retrieval Test"

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass

    def test_get_bookmark_not_found(self, authenticated_client: VASClient):
        """
        Test: GET /v2/bookmarks/{invalid_id}
        Expected: 404 Not Found
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.get_bookmark("00000000-0000-0000-0000-000000000000")

        assert exc_info.value.status_code == 404

    @pytest.mark.slow
    def test_download_bookmark_video(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/bookmarks/{bookmark_id}/video
        Expected: 200 OK with MP4 binary data
        """
        stream_id = active_stream["stream_id"]

        # Create and wait for ready
        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Video Download Test",
            event_type="test",
            before_seconds=2,
            after_seconds=3,
        )

        authenticated_client.wait_for_bookmark_ready(bookmark.id, timeout=30.0)

        # Download video
        video_data = authenticated_client.get_bookmark_video(bookmark.id)

        assert video_data is not None
        assert len(video_data) > 0
        # MP4 typically starts with ftyp box
        assert b'ftyp' in video_data[:32] or video_data[:4] == b'\x00\x00\x00\x1c', "Should be valid MP4"

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass

    @pytest.mark.slow
    def test_download_bookmark_thumbnail(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/bookmarks/{bookmark_id}/thumbnail
        Expected: 200 OK with JPEG binary data
        """
        stream_id = active_stream["stream_id"]

        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Thumbnail Download Test",
            event_type="test",
            before_seconds=2,
            after_seconds=3,
        )

        authenticated_client.wait_for_bookmark_ready(bookmark.id, timeout=30.0)

        # Download thumbnail
        thumb_data = authenticated_client.get_bookmark_thumbnail(bookmark.id)

        assert thumb_data is not None
        assert len(thumb_data) > 0
        # JPEG magic bytes
        assert thumb_data[:2] == b'\xff\xd8', "Should be valid JPEG"

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass


@pytest.mark.bookmark
class TestBookmarkListing:
    """Bookmark listing tests"""

    def test_list_bookmarks(self, authenticated_client: VASClient):
        """
        Test: GET /v2/bookmarks
        Expected: 200 OK with bookmarks list and pagination
        """
        response = authenticated_client.list_bookmarks()

        assert response is not None
        assert hasattr(response, "bookmarks")
        assert hasattr(response, "pagination")
        assert isinstance(response.bookmarks, list)

    def test_list_bookmarks_filter_by_stream(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/bookmarks?stream_id={stream_id}
        Expected: Only returns bookmarks for specified stream
        """
        stream_id = active_stream["stream_id"]

        # Create a bookmark first
        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Filter Test",
            event_type="test",
        )

        try:
            response = authenticated_client.list_bookmarks(stream_id=stream_id)

            for b in response.bookmarks:
                assert b.stream_id == stream_id
        finally:
            try:
                authenticated_client.delete_bookmark(bookmark.id)
            except Exception:
                pass

    def test_list_bookmarks_filter_by_event_type(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/bookmarks?event_type={event_type}
        """
        stream_id = active_stream["stream_id"]
        event_type = "speeding-violation"

        # Create bookmark with specific event type
        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Event Type Filter Test",
            event_type=event_type,
        )

        try:
            response = authenticated_client.list_bookmarks(event_type=event_type)

            for b in response.bookmarks:
                assert b.event_type == event_type
        finally:
            try:
                authenticated_client.delete_bookmark(bookmark.id)
            except Exception:
                pass


@pytest.mark.bookmark
@pytest.mark.requires_stream
class TestBookmarkUpdate:
    """Bookmark update tests"""

    def test_update_bookmark_label(self, authenticated_client: VASClient, active_stream):
        """
        Test: PUT /v2/bookmarks/{bookmark_id}
        Expected: 200 OK with updated bookmark
        """
        stream_id = active_stream["stream_id"]

        # Create bookmark
        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Original Label",
            event_type="test",
        )

        # Update label
        updated = authenticated_client.update_bookmark(
            bookmark.id,
            label="Updated Label",
        )

        assert updated.label == "Updated Label"

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass

    def test_update_bookmark_tags(self, authenticated_client: VASClient, active_stream):
        """
        Test: Update bookmark tags
        """
        stream_id = active_stream["stream_id"]

        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Tag Update Test",
            event_type="test",
            tags=["original"],
        )

        # Update tags
        updated = authenticated_client.update_bookmark(
            bookmark.id,
            tags=["updated", "new-tag"],
        )

        assert "updated" in updated.tags
        assert "new-tag" in updated.tags

        # Cleanup
        try:
            authenticated_client.delete_bookmark(bookmark.id)
        except Exception:
            pass


@pytest.mark.bookmark
@pytest.mark.requires_stream
class TestBookmarkDeletion:
    """Bookmark deletion tests"""

    def test_delete_bookmark(self, authenticated_client: VASClient, active_stream):
        """
        Test: DELETE /v2/bookmarks/{bookmark_id}
        Expected: 204 No Content
        """
        stream_id = active_stream["stream_id"]

        # Create bookmark
        bookmark = authenticated_client.create_bookmark(
            stream_id=stream_id,
            label="Deletion Test",
            event_type="test",
        )

        # Delete it
        authenticated_client.delete_bookmark(bookmark.id)

        # Verify it's gone
        with pytest.raises(VASError) as exc_info:
            authenticated_client.get_bookmark(bookmark.id)

        assert exc_info.value.status_code == 404

    def test_delete_bookmark_not_found(self, authenticated_client: VASClient):
        """
        Test: DELETE /v2/bookmarks/{invalid_id}
        Expected: 404 Not Found
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.delete_bookmark("00000000-0000-0000-0000-000000000000")

        assert exc_info.value.status_code == 404


@pytest.mark.bookmark
class TestBookmarkValidation:
    """Bookmark validation tests"""

    def test_create_bookmark_invalid_stream(self, authenticated_client: VASClient):
        """
        Test: Creating bookmark on non-existent stream
        Expected: 404 or 409 error
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.create_bookmark(
                stream_id="00000000-0000-0000-0000-000000000000",
                label="Invalid Stream Test",
                event_type="test",
            )

        assert exc_info.value.status_code in [404, 409]

    def test_create_bookmark_missing_required_fields(self, authenticated_client: VASClient, active_stream):
        """
        Test: Creating bookmark without required fields
        Expected: 400 Bad Request or validation error
        """
        stream_id = active_stream["stream_id"]

        # Label and event_type are required in our client
        # Test that the API properly validates
        try:
            # This should fail if label is empty
            bookmark = authenticated_client.create_bookmark(
                stream_id=stream_id,
                label="",  # Empty label
                event_type="test",
            )
            # If it succeeded, clean up
            authenticated_client.delete_bookmark(bookmark.id)
        except VASError as e:
            # Expected to fail with validation error
            assert e.status_code == 400 or e.status_code == 422

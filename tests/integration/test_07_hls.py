"""
VAS-MS-V2 HLS Playback Integration Tests

Tests cover:
- HLS playlist retrieval
- HLS segment retrieval
- Playlist format validation
"""

import pytest
import re
from vas_client import VASClient, VASError


@pytest.mark.hls
@pytest.mark.requires_stream
class TestHLSPlaylist:
    """HLS playlist tests"""

    def test_get_hls_playlist(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/streams/{stream_id}/hls/playlist.m3u8
        Expected: 200 OK with valid M3U8 playlist
        """
        stream_id = active_stream["stream_id"]

        playlist = authenticated_client.get_hls_playlist(stream_id)

        assert playlist is not None
        assert len(playlist) > 0
        assert playlist.startswith("#EXTM3U"), "Should be valid M3U8 format"

    def test_hls_playlist_contains_required_tags(self, authenticated_client: VASClient, active_stream):
        """
        Test: HLS playlist contains required M3U8 tags
        """
        stream_id = active_stream["stream_id"]

        playlist = authenticated_client.get_hls_playlist(stream_id)

        # Required HLS tags
        assert "#EXTM3U" in playlist
        assert "#EXT-X-VERSION" in playlist
        assert "#EXT-X-TARGETDURATION" in playlist

    def test_hls_playlist_has_segments(self, authenticated_client: VASClient, active_stream):
        """
        Test: HLS playlist contains segment references
        """
        stream_id = active_stream["stream_id"]

        playlist = authenticated_client.get_hls_playlist(stream_id)

        # Should have EXTINF tags for segments
        assert "#EXTINF:" in playlist

        # Should have .ts segment references
        lines = playlist.split("\n")
        ts_segments = [line for line in lines if line.endswith(".ts")]
        assert len(ts_segments) > 0, "Playlist should contain .ts segments"

    def test_hls_playlist_segment_duration(self, authenticated_client: VASClient, active_stream):
        """
        Test: HLS segment duration is reasonable
        """
        stream_id = active_stream["stream_id"]

        playlist = authenticated_client.get_hls_playlist(stream_id)

        # Extract target duration
        match = re.search(r"#EXT-X-TARGETDURATION:(\d+)", playlist)
        if match:
            target_duration = int(match.group(1))
            # Typical HLS segment is 2-10 seconds
            assert 1 <= target_duration <= 20, "Target duration should be reasonable"


@pytest.mark.hls
@pytest.mark.requires_stream
@pytest.mark.slow
class TestHLSSegments:
    """HLS segment tests"""

    def test_get_hls_segment(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET /v2/streams/{stream_id}/hls/{segment_name}
        Expected: 200 OK with TS binary data
        """
        stream_id = active_stream["stream_id"]

        # First get playlist to find segment names
        playlist = authenticated_client.get_hls_playlist(stream_id)

        # Extract first segment name
        lines = playlist.split("\n")
        ts_segments = [line.strip() for line in lines if line.strip().endswith(".ts")]

        if not ts_segments:
            pytest.skip("No segments available in playlist")

        segment_name = ts_segments[0]

        # Get segment
        segment_data = authenticated_client.get_hls_segment(stream_id, segment_name)

        assert segment_data is not None
        assert len(segment_data) > 0
        # TS files start with sync byte 0x47
        assert segment_data[0] == 0x47 or segment_data[:3] == b'\x00\x00\x01', "Should be valid TS data"

    def test_get_hls_segment_not_found(self, authenticated_client: VASClient, active_stream):
        """
        Test: GET non-existent HLS segment
        Expected: 404 Not Found
        """
        stream_id = active_stream["stream_id"]

        with pytest.raises(VASError) as exc_info:
            authenticated_client.get_hls_segment(stream_id, "nonexistent.ts")

        assert exc_info.value.status_code == 404


@pytest.mark.hls
class TestHLSErrors:
    """HLS error handling tests"""

    def test_get_playlist_stream_not_found(self, authenticated_client: VASClient):
        """
        Test: GET playlist for non-existent stream
        Expected: 404 Not Found
        """
        with pytest.raises(VASError) as exc_info:
            authenticated_client.get_hls_playlist("00000000-0000-0000-0000-000000000000")

        assert exc_info.value.status_code == 404

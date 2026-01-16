"""VAS-MS-V2 API Client for Integration Testing"""

import os
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import httpx
from .models import (
    TokenResponse,
    Device,
    DeviceValidation,
    StreamStartResponse,
    StreamStopResponse,
    Stream,
    StreamListResponse,
    StreamHealth,
    Consumer,
    ConsumerListResponse,
    ConnectResponse,
    Snapshot,
    SnapshotListResponse,
    Bookmark,
    BookmarkListResponse,
    VASError,
    StreamState,
    ProcessingStatus,
)


class VASClient:
    """
    VAS-MS-V2 API Client

    Provides methods for all VAS API endpoints with automatic token management.
    """

    def __init__(
        self,
        base_url: str = None,
        client_id: str = None,
        client_secret: str = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or os.getenv("VAS_BASE_URL", "http://10.30.250.245:8085")).rstrip("/")
        self.client_id = client_id or os.getenv("VAS_DEFAULT_CLIENT_ID", "vas-portal")
        self.client_secret = client_secret or os.getenv("VAS_DEFAULT_CLIENT_SECRET", "vas-portal-secret-2024")
        self.timeout = timeout

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

        self._client = httpx.Client(timeout=timeout)
        self._async_client: Optional[httpx.AsyncClient] = None

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_client

    async def close(self):
        """Close the client connections"""
        self._client.close()
        if self._async_client:
            await self._async_client.aclose()

    def _handle_error(self, response: httpx.Response) -> None:
        """Parse and raise VAS API errors"""
        try:
            data = response.json()
            if isinstance(data, dict):
                error = data.get("error", data.get("detail", "UNKNOWN_ERROR"))
                if isinstance(error, dict):
                    raise VASError(
                        status_code=response.status_code,
                        error=error.get("error_code", "UNKNOWN_ERROR"),
                        description=error.get("message", str(error)),
                        details=error.get("detail"),
                    )
                description = data.get("error_description", data.get("message", str(data)))
                raise VASError(
                    status_code=response.status_code,
                    error=str(error),
                    description=description,
                    details=data.get("details"),
                )
        except (ValueError, KeyError):
            pass
        raise VASError(
            status_code=response.status_code,
            error="HTTP_ERROR",
            description=response.text or f"HTTP {response.status_code}",
        )

    def _get_headers(self, authenticated: bool = True) -> Dict[str, str]:
        """Get request headers with optional authentication"""
        headers = {"Content-Type": "application/json"}
        if authenticated and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    @property
    def is_token_expired(self) -> bool:
        """Check if token is expired or will expire soon (within 5 minutes)"""
        if not self._token_expires_at:
            return True
        return datetime.now() >= (self._token_expires_at - timedelta(minutes=5))

    # ==================== Authentication APIs ====================

    def authenticate(self) -> TokenResponse:
        """
        Authenticate and get access token
        POST /v2/auth/token
        """
        response = self._client.post(
            f"{self.base_url}/v2/auth/token",
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            self._handle_error(response)

        data = response.json()
        token = TokenResponse(**data)

        self._access_token = token.access_token
        self._refresh_token = token.refresh_token
        self._token_expires_at = datetime.now() + timedelta(seconds=token.expires_in)

        return token

    def refresh_token(self) -> TokenResponse:
        """
        Refresh access token
        POST /v2/auth/token/refresh
        """
        if not self._refresh_token:
            raise VASError(401, "NO_REFRESH_TOKEN", "No refresh token available")

        response = self._client.post(
            f"{self.base_url}/v2/auth/token/refresh",
            json={"refresh_token": self._refresh_token},
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            self._handle_error(response)

        data = response.json()
        token = TokenResponse(**data)

        self._access_token = token.access_token
        self._refresh_token = token.refresh_token
        self._token_expires_at = datetime.now() + timedelta(seconds=token.expires_in)

        return token

    def ensure_authenticated(self) -> None:
        """Ensure we have a valid token, refreshing if needed"""
        if self.is_token_expired:
            if self._refresh_token:
                try:
                    self.refresh_token()
                    return
                except VASError:
                    pass
            self.authenticate()

    # ==================== Device APIs (V1) ====================

    def list_devices(self, skip: int = 0, limit: int = 100) -> List[Device]:
        """
        List all devices
        GET /api/v1/devices
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/api/v1/devices",
            params={"skip": skip, "limit": limit},
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        data = response.json()
        # Handle both list and dict response formats
        if isinstance(data, list):
            return [Device(**d) for d in data]
        return [Device(**d) for d in data.get("devices", data)]

    def get_device(self, device_id: str) -> Device:
        """
        Get device details
        GET /api/v1/devices/{device_id}
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/api/v1/devices/{device_id}",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return Device(**response.json())

    def create_device(
        self,
        name: str,
        rtsp_url: str,
        description: str = None,
        location: str = None,
    ) -> Device:
        """
        Create a new device
        POST /api/v1/devices
        """
        self.ensure_authenticated()
        payload = {"name": name, "rtsp_url": rtsp_url}
        if description:
            payload["description"] = description
        if location:
            payload["location"] = location

        response = self._client.post(
            f"{self.base_url}/api/v1/devices",
            json=payload,
            headers=self._get_headers(),
        )

        if response.status_code not in [200, 201]:
            self._handle_error(response)

        return Device(**response.json())

    def validate_device(self, name: str, rtsp_url: str) -> DeviceValidation:
        """
        Validate RTSP URL
        POST /api/v1/devices/validate
        """
        self.ensure_authenticated()
        response = self._client.post(
            f"{self.base_url}/api/v1/devices/validate",
            json={"name": name, "rtsp_url": rtsp_url},
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return DeviceValidation(**response.json())

    def start_stream(self, device_id: str) -> StreamStartResponse:
        """
        Start streaming from device
        POST /api/v1/devices/{device_id}/start-stream
        """
        self.ensure_authenticated()
        response = self._client.post(
            f"{self.base_url}/api/v1/devices/{device_id}/start-stream",
            headers=self._get_headers(),
            timeout=60.0,  # Stream start can take longer
        )

        if response.status_code != 200:
            self._handle_error(response)

        return StreamStartResponse(**response.json())

    def stop_stream(self, device_id: str) -> StreamStopResponse:
        """
        Stop streaming from device
        POST /api/v1/devices/{device_id}/stop-stream
        """
        self.ensure_authenticated()
        response = self._client.post(
            f"{self.base_url}/api/v1/devices/{device_id}/stop-stream",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return StreamStopResponse(**response.json())

    def get_device_status(self, device_id: str) -> Dict[str, Any]:
        """
        Get device status
        GET /api/v1/devices/{device_id}/status
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/api/v1/devices/{device_id}/status",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.json()

    # ==================== Stream APIs (V2) ====================

    def list_streams(
        self,
        state: StreamState = None,
        camera_id: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> StreamListResponse:
        """
        List streams with optional filters
        GET /v2/streams
        """
        self.ensure_authenticated()
        params = {"limit": limit, "offset": offset}
        if state:
            params["state"] = state.value
        if camera_id:
            params["camera_id"] = camera_id

        response = self._client.get(
            f"{self.base_url}/v2/streams",
            params=params,
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        data = response.json()
        return StreamListResponse(**data)

    def get_stream(self, stream_id: str) -> Stream:
        """
        Get stream details
        GET /v2/streams/{stream_id}
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/streams/{stream_id}",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return Stream(**response.json())

    def delete_stream(self, stream_id: str) -> None:
        """
        Delete stream
        DELETE /v2/streams/{stream_id}
        """
        self.ensure_authenticated()
        response = self._client.delete(
            f"{self.base_url}/v2/streams/{stream_id}",
            headers=self._get_headers(),
        )

        if response.status_code not in [200, 204]:
            self._handle_error(response)

    def get_stream_health(self, stream_id: str) -> StreamHealth:
        """
        Get stream health metrics
        GET /v2/streams/{stream_id}/health
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/streams/{stream_id}/health",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return StreamHealth(**response.json())

    def get_router_capabilities(self, stream_id: str) -> Dict[str, Any]:
        """
        Get MediaSoup router RTP capabilities
        GET /v2/streams/{stream_id}/router-capabilities
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/streams/{stream_id}/router-capabilities",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.json()

    def wait_for_stream_live(
        self,
        stream_id: str,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> Stream:
        """
        Wait for stream to reach LIVE state
        """
        start = time.time()
        while time.time() - start < timeout:
            stream = self.get_stream(stream_id)
            # Compare case-insensitively to handle both "LIVE" and "live"
            state_lower = stream.state.value.lower()
            if state_lower == "live":
                return stream
            if state_lower in ["error", "stopped", "closed"]:
                raise VASError(
                    409,
                    "STREAM_NOT_LIVE",
                    f"Stream reached terminal state: {stream.state.value}",
                    {"current_state": stream.state.value},
                )
            time.sleep(poll_interval)

        raise VASError(
            504,
            "STREAM_TIMEOUT",
            f"Stream did not reach LIVE state within {timeout}s",
        )

    # ==================== WebRTC Consumer APIs ====================

    def attach_consumer(
        self,
        stream_id: str,
        client_id: str,
        rtp_capabilities: Dict[str, Any],
    ) -> Consumer:
        """
        Attach WebRTC consumer to stream
        POST /v2/streams/{stream_id}/consume
        """
        self.ensure_authenticated()
        response = self._client.post(
            f"{self.base_url}/v2/streams/{stream_id}/consume",
            json={
                "client_id": client_id,
                "rtp_capabilities": rtp_capabilities,
            },
            headers=self._get_headers(),
        )

        if response.status_code not in [200, 201]:
            self._handle_error(response)

        return Consumer(**response.json())

    def connect_consumer(
        self,
        stream_id: str,
        consumer_id: str,
        dtls_parameters: Dict[str, Any],
    ) -> ConnectResponse:
        """
        Complete DTLS handshake for consumer
        POST /v2/streams/{stream_id}/consumers/{consumer_id}/connect
        """
        self.ensure_authenticated()
        response = self._client.post(
            f"{self.base_url}/v2/streams/{stream_id}/consumers/{consumer_id}/connect",
            json={"dtls_parameters": dtls_parameters},
            headers=self._get_headers(),
            timeout=15.0,
        )

        if response.status_code != 200:
            self._handle_error(response)

        return ConnectResponse(**response.json())

    def add_ice_candidate(
        self,
        stream_id: str,
        consumer_id: str,
        candidate: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Add ICE candidate
        POST /v2/streams/{stream_id}/consumers/{consumer_id}/ice-candidate
        """
        self.ensure_authenticated()
        response = self._client.post(
            f"{self.base_url}/v2/streams/{stream_id}/consumers/{consumer_id}/ice-candidate",
            json={"candidate": candidate},
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.json()

    def list_consumers(self, stream_id: str) -> ConsumerListResponse:
        """
        List consumers for a stream
        GET /v2/streams/{stream_id}/consumers
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/streams/{stream_id}/consumers",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return ConsumerListResponse(**response.json())

    def detach_consumer(self, stream_id: str, consumer_id: str) -> None:
        """
        Detach consumer from stream
        DELETE /v2/streams/{stream_id}/consumers/{consumer_id}
        """
        self.ensure_authenticated()
        response = self._client.delete(
            f"{self.base_url}/v2/streams/{stream_id}/consumers/{consumer_id}",
            headers=self._get_headers(),
        )

        if response.status_code not in [200, 204]:
            self._handle_error(response)

    # ==================== Snapshot APIs ====================

    def create_snapshot(
        self,
        stream_id: str,
        source: str = "live",
        created_by: str = "ruth-ai-test",
        timestamp: datetime = None,
        metadata: Dict[str, Any] = None,
    ) -> Snapshot:
        """
        Create snapshot from stream
        POST /v2/streams/{stream_id}/snapshots
        """
        self.ensure_authenticated()
        payload = {
            "source": source,
            "created_by": created_by,
        }
        if source == "historical" and timestamp:
            payload["timestamp"] = timestamp.isoformat()
        if metadata:
            payload["metadata"] = metadata

        response = self._client.post(
            f"{self.base_url}/v2/streams/{stream_id}/snapshots",
            json=payload,
            headers=self._get_headers(),
        )

        if response.status_code not in [200, 201]:
            self._handle_error(response)

        return Snapshot(**response.json())

    def list_snapshots(
        self,
        stream_id: str = None,
        created_by: str = None,
        source: str = None,
        after: datetime = None,
        before: datetime = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SnapshotListResponse:
        """
        List snapshots with optional filters
        GET /v2/snapshots
        """
        self.ensure_authenticated()
        params = {"limit": limit, "offset": offset}
        if stream_id:
            params["stream_id"] = stream_id
        if created_by:
            params["created_by"] = created_by
        if source:
            params["source"] = source
        if after:
            params["after"] = after.isoformat()
        if before:
            params["before"] = before.isoformat()

        response = self._client.get(
            f"{self.base_url}/v2/snapshots",
            params=params,
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return SnapshotListResponse(**response.json())

    def get_snapshot(self, snapshot_id: str) -> Snapshot:
        """
        Get snapshot details
        GET /v2/snapshots/{snapshot_id}
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/snapshots/{snapshot_id}",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return Snapshot(**response.json())

    def get_snapshot_image(self, snapshot_id: str) -> bytes:
        """
        Download snapshot image
        GET /v2/snapshots/{snapshot_id}/image
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/snapshots/{snapshot_id}/image",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.content

    def delete_snapshot(self, snapshot_id: str) -> None:
        """
        Delete snapshot
        DELETE /v2/snapshots/{snapshot_id}
        """
        self.ensure_authenticated()
        response = self._client.delete(
            f"{self.base_url}/v2/snapshots/{snapshot_id}",
            headers=self._get_headers(),
        )

        if response.status_code not in [200, 204]:
            self._handle_error(response)

    def wait_for_snapshot_ready(
        self,
        snapshot_id: str,
        timeout: float = 10.0,
        poll_interval: float = 0.5,
    ) -> Snapshot:
        """
        Wait for snapshot to be ready
        """
        start = time.time()
        backoff = poll_interval
        while time.time() - start < timeout:
            snapshot = self.get_snapshot(snapshot_id)
            if snapshot.status == ProcessingStatus.READY:
                return snapshot
            if snapshot.status == ProcessingStatus.FAILED:
                raise VASError(
                    500,
                    "SNAPSHOT_FAILED",
                    "Snapshot processing failed",
                )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 5.0)  # Exponential backoff

        raise VASError(
            504,
            "SNAPSHOT_TIMEOUT",
            f"Snapshot did not complete within {timeout}s",
        )

    # ==================== Bookmark APIs ====================

    def create_bookmark(
        self,
        stream_id: str,
        label: str,
        event_type: str,
        source: str = "live",
        before_seconds: int = 5,
        after_seconds: int = 10,
        center_timestamp: datetime = None,
        confidence: float = None,
        tags: List[str] = None,
        created_by: str = "ruth-ai-test",
        metadata: Dict[str, Any] = None,
    ) -> Bookmark:
        """
        Create bookmark (video clip) from stream
        POST /v2/streams/{stream_id}/bookmarks
        """
        self.ensure_authenticated()
        payload = {
            "source": source,
            "label": label,
            "event_type": event_type,
            "before_seconds": before_seconds,
            "after_seconds": after_seconds,
            "created_by": created_by,
        }
        if source == "historical" and center_timestamp:
            payload["center_timestamp"] = center_timestamp.isoformat()
        if confidence is not None:
            payload["confidence"] = confidence
        if tags:
            payload["tags"] = tags
        if metadata:
            payload["metadata"] = metadata

        response = self._client.post(
            f"{self.base_url}/v2/streams/{stream_id}/bookmarks",
            json=payload,
            headers=self._get_headers(),
        )

        if response.status_code not in [200, 201]:
            self._handle_error(response)

        return Bookmark(**response.json())

    def list_bookmarks(
        self,
        stream_id: str = None,
        event_type: str = None,
        created_by: str = None,
        source: str = None,
        start_after: datetime = None,
        start_before: datetime = None,
        limit: int = 50,
        offset: int = 0,
    ) -> BookmarkListResponse:
        """
        List bookmarks with optional filters
        GET /v2/bookmarks
        """
        self.ensure_authenticated()
        params = {"limit": limit, "offset": offset}
        if stream_id:
            params["stream_id"] = stream_id
        if event_type:
            params["event_type"] = event_type
        if created_by:
            params["created_by"] = created_by
        if source:
            params["source"] = source
        if start_after:
            params["start_after"] = start_after.isoformat()
        if start_before:
            params["start_before"] = start_before.isoformat()

        response = self._client.get(
            f"{self.base_url}/v2/bookmarks",
            params=params,
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return BookmarkListResponse(**response.json())

    def get_bookmark(self, bookmark_id: str) -> Bookmark:
        """
        Get bookmark details
        GET /v2/bookmarks/{bookmark_id}
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/bookmarks/{bookmark_id}",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return Bookmark(**response.json())

    def get_bookmark_video(self, bookmark_id: str) -> bytes:
        """
        Download bookmark video
        GET /v2/bookmarks/{bookmark_id}/video
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/bookmarks/{bookmark_id}/video",
            headers=self._get_headers(),
            timeout=60.0,
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.content

    def get_bookmark_thumbnail(self, bookmark_id: str) -> bytes:
        """
        Download bookmark thumbnail
        GET /v2/bookmarks/{bookmark_id}/thumbnail
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/bookmarks/{bookmark_id}/thumbnail",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.content

    def update_bookmark(
        self,
        bookmark_id: str,
        label: str = None,
        event_type: str = None,
        tags: List[str] = None,
    ) -> Bookmark:
        """
        Update bookmark metadata
        PUT /v2/bookmarks/{bookmark_id}
        """
        self.ensure_authenticated()
        payload = {}
        if label is not None:
            payload["label"] = label
        if event_type is not None:
            payload["event_type"] = event_type
        if tags is not None:
            payload["tags"] = tags

        response = self._client.put(
            f"{self.base_url}/v2/bookmarks/{bookmark_id}",
            json=payload,
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return Bookmark(**response.json())

    def delete_bookmark(self, bookmark_id: str) -> None:
        """
        Delete bookmark
        DELETE /v2/bookmarks/{bookmark_id}
        """
        self.ensure_authenticated()
        response = self._client.delete(
            f"{self.base_url}/v2/bookmarks/{bookmark_id}",
            headers=self._get_headers(),
        )

        if response.status_code not in [200, 204]:
            self._handle_error(response)

    def wait_for_bookmark_ready(
        self,
        bookmark_id: str,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> Bookmark:
        """
        Wait for bookmark to be ready
        """
        start = time.time()
        backoff = poll_interval
        while time.time() - start < timeout:
            bookmark = self.get_bookmark(bookmark_id)
            if bookmark.status == ProcessingStatus.READY:
                return bookmark
            if bookmark.status == ProcessingStatus.FAILED:
                raise VASError(
                    500,
                    "BOOKMARK_FAILED",
                    "Bookmark processing failed",
                )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 5.0)  # Exponential backoff

        raise VASError(
            504,
            "BOOKMARK_TIMEOUT",
            f"Bookmark did not complete within {timeout}s",
        )

    # ==================== HLS Playback APIs ====================

    def get_hls_playlist(self, stream_id: str) -> str:
        """
        Get HLS playlist
        GET /v2/streams/{stream_id}/hls/playlist.m3u8
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/streams/{stream_id}/hls/playlist.m3u8",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.text

    def get_hls_segment(self, stream_id: str, segment_name: str) -> bytes:
        """
        Get HLS segment
        GET /v2/streams/{stream_id}/hls/{segment_name}
        """
        self.ensure_authenticated()
        response = self._client.get(
            f"{self.base_url}/v2/streams/{stream_id}/hls/{segment_name}",
            headers=self._get_headers(),
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.content

    # ==================== OpenAPI / Docs ====================

    def get_openapi_spec(self, format: str = "json") -> Dict[str, Any] | str:
        """
        Get OpenAPI specification
        GET /v2/openapi.json or /v2/openapi.yaml
        """
        ext = "yaml" if format == "yaml" else "json"
        response = self._client.get(
            f"{self.base_url}/v2/openapi.{ext}",
        )

        if response.status_code != 200:
            self._handle_error(response)

        if format == "yaml":
            return response.text
        return response.json()

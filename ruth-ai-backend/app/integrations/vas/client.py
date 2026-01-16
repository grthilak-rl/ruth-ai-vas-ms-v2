"""VAS API async client.

Defensive async client for VAS-MS-V2 integration with:
- Automatic token management (refresh at 80% TTL)
- Exponential backoff retry logic
- Typed responses via Pydantic models
- Structured error handling
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from pydantic import ValidationError

from app.core.logging import get_logger

from .exceptions import (
    VASAuthenticationError,
    VASConflictError,
    VASConnectionError,
    VASError,
    VASForbiddenError,
    VASMediaSoupUnavailableError,
    VASNotFoundError,
    VASRefreshTokenError,
    VASRTSPError,
    VASServerError,
    VASStreamNotLiveError,
    VASTimeoutError,
    VASValidationError,
)
from .models import (
    Bookmark,
    BookmarkCreateRequest,
    BookmarkListResponse,
    Device,
    DeviceStatus,
    Snapshot,
    SnapshotCreateRequest,
    SnapshotListResponse,
    Stream,
    StreamHealth,
    StreamListResponse,
    StreamStartResponse,
    StreamStopResponse,
    TokenRefreshResponse,
    TokenResponse,
    VASErrorResponse,
)

logger = get_logger(__name__)


# Token refresh threshold: refresh when 80% of TTL has elapsed
TOKEN_REFRESH_THRESHOLD = 0.8

# Default timeouts (in seconds)
DEFAULT_TIMEOUT = 30.0
STREAM_START_TIMEOUT = 45.0  # Stream start can take longer

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # Exponential backoff: 2^attempt seconds
RETRY_BACKOFF_MAX = 30.0  # Maximum backoff delay


class VASClient:
    """Async client for VAS-MS-V2 API.

    Usage:
        async with VASClient(base_url, client_id, client_secret) as client:
            devices = await client.get_devices()
            stream = await client.start_stream(device_id)

    Or manually manage lifecycle:
        client = VASClient(base_url, client_id, client_secret)
        await client.connect()
        try:
            devices = await client.get_devices()
        finally:
            await client.close()
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize VAS client.

        Args:
            base_url: VAS API base URL (e.g., http://10.30.250.245:8085)
            client_id: OAuth client ID
            client_secret: OAuth client secret
            timeout: Default request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout

        # Token state
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0
        self._token_lock = asyncio.Lock()

        # HTTP client
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Initialize HTTP client and authenticate."""
        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
        )

        # Obtain initial tokens
        await self._authenticate()
        logger.info("VAS client connected", base_url=self.base_url)

    async def close(self) -> None:
        """Close HTTP client and clean up resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._access_token = None
            self._refresh_token = None
            logger.info("VAS client closed")

    async def __aenter__(self) -> "VASClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    async def _authenticate(self) -> None:
        """Obtain access and refresh tokens using client credentials."""
        if not self._client:
            raise VASConnectionError("Client not connected")

        try:
            response = await self._client.post(
                "/v2/auth/token",
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )

            if response.status_code == 401:
                raise VASAuthenticationError(
                    "Invalid client credentials",
                    error_code="INVALID_CREDENTIALS",
                )

            response.raise_for_status()
            token_data = TokenResponse.model_validate(response.json())

            async with self._token_lock:
                self._access_token = token_data.access_token
                self._refresh_token = token_data.refresh_token
                self._token_expires_at = time.time() + token_data.expires_in

            logger.info(
                "Authenticated with VAS",
                expires_in=token_data.expires_in,
                scopes=token_data.scopes,
            )

        except httpx.ConnectError as e:
            raise VASConnectionError(f"Failed to connect to VAS: {e}") from e
        except httpx.TimeoutException as e:
            raise VASTimeoutError("Authentication request timed out") from e

    async def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        if not self._client or not self._refresh_token:
            await self._authenticate()
            return

        try:
            response = await self._client.post(
                "/v2/auth/token/refresh",
                json={"refresh_token": self._refresh_token},
            )

            if response.status_code == 401:
                # Refresh token expired - need full re-auth
                logger.warning("Refresh token expired, re-authenticating")
                raise VASRefreshTokenError()

            response.raise_for_status()
            token_data = TokenRefreshResponse.model_validate(response.json())

            async with self._token_lock:
                self._access_token = token_data.access_token
                self._token_expires_at = time.time() + token_data.expires_in

            logger.debug("Access token refreshed", expires_in=token_data.expires_in)

        except VASRefreshTokenError:
            # Re-authenticate with credentials
            await self._authenticate()
        except httpx.ConnectError as e:
            raise VASConnectionError(f"Failed to connect to VAS: {e}") from e

    async def _ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, refreshing if needed.

        Returns:
            Valid access token
        """
        async with self._token_lock:
            # Check if token needs refresh (at 80% TTL)
            time_until_expiry = self._token_expires_at - time.time()
            token_lifetime = self._token_expires_at - (
                self._token_expires_at - 3600
            )  # Assume 1hr default
            threshold = token_lifetime * TOKEN_REFRESH_THRESHOLD

            if time_until_expiry < threshold or not self._access_token:
                # Release lock for refresh operation
                pass
            else:
                return self._access_token

        # Refresh outside lock to avoid blocking
        await self._refresh_access_token()

        async with self._token_lock:
            if not self._access_token:
                raise VASAuthenticationError("Failed to obtain access token")
            return self._access_token

    def _get_auth_headers(self, token: str) -> dict[str, str]:
        """Build authorization headers."""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # -------------------------------------------------------------------------
    # Request Handling
    # -------------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
        timeout: float | None = None,
        retries: int = MAX_RETRIES,
    ) -> httpx.Response:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method
            path: API path
            json: JSON body
            params: Query parameters
            authenticated: Whether to include auth header
            timeout: Request timeout override
            retries: Number of retries

        Returns:
            HTTP response

        Raises:
            VASError: On API errors
        """
        if not self._client:
            raise VASConnectionError("Client not connected")

        headers = {}
        if authenticated:
            token = await self._ensure_valid_token()
            headers = self._get_auth_headers(token)

        request_timeout = timeout or self.timeout
        attempt = 0

        while True:
            try:
                response = await self._client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers=headers,
                    timeout=request_timeout,
                )

                # Handle auth errors with refresh
                if response.status_code == 401 and authenticated:
                    if attempt == 0:
                        logger.debug("Token expired, refreshing and retrying")
                        await self._refresh_access_token()
                        token = await self._ensure_valid_token()
                        headers = self._get_auth_headers(token)
                        attempt += 1
                        continue
                    else:
                        self._raise_for_status(response)

                # Check for errors
                self._raise_for_status(response)
                return response

            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                if attempt < retries:
                    delay = min(
                        RETRY_BACKOFF_BASE ** attempt,
                        RETRY_BACKOFF_MAX,
                    )
                    logger.warning(
                        "Connection failed, retrying",
                        attempt=attempt + 1,
                        max_retries=retries,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                else:
                    raise VASConnectionError(
                        f"Failed to connect after {retries} retries: {e}"
                    ) from e

            except httpx.TimeoutException as e:
                if attempt < retries:
                    delay = min(
                        RETRY_BACKOFF_BASE ** attempt,
                        RETRY_BACKOFF_MAX,
                    )
                    logger.warning(
                        "Request timed out, retrying",
                        attempt=attempt + 1,
                        max_retries=retries,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                else:
                    raise VASTimeoutError(
                        f"Request timed out after {retries} retries"
                    ) from e

            except VASServerError as e:
                # Retry 5xx errors with backoff
                if attempt < retries and e.status_code >= 500:
                    delay = min(
                        RETRY_BACKOFF_BASE ** attempt,
                        RETRY_BACKOFF_MAX,
                    )
                    logger.warning(
                        "Server error, retrying",
                        attempt=attempt + 1,
                        max_retries=retries,
                        delay=delay,
                        status_code=e.status_code,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                else:
                    raise

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Raise appropriate exception for error responses."""
        if response.is_success:
            return

        # Try to parse error response
        error_data: dict[str, Any] = {}
        try:
            error_data = response.json()
            vas_error = VASErrorResponse.model_validate(error_data)
            error_code = vas_error.error
            error_message = vas_error.error_description
            details = vas_error.details
            request_id = vas_error.request_id
        except (ValueError, ValidationError):
            error_code = None
            error_message = response.text or f"HTTP {response.status_code}"
            details = None
            request_id = None

        status = response.status_code

        # Map to specific exceptions
        if status == 400:
            raise VASValidationError(
                error_message,
                details=details,
                request_id=request_id,
            )

        if status == 401:
            raise VASAuthenticationError(
                error_message,
                error_code=error_code,
                request_id=request_id,
            )

        if status == 403:
            raise VASForbiddenError(
                error_message,
                error_code=error_code,
                request_id=request_id,
            )

        if status == 404:
            raise VASNotFoundError(
                resource_type="Resource",
                request_id=request_id,
            )

        if status == 409:
            # Check for stream not live error
            if error_code == "STREAM_NOT_LIVE":
                raise VASStreamNotLiveError(
                    stream_id=details.get("stream_id") if details else None,
                    current_state=details.get("current_state") if details else None,
                    request_id=request_id,
                )
            raise VASConflictError(
                error_message,
                error_code=error_code,
                details=details,
                request_id=request_id,
            )

        if status == 502:
            # RTSP/Camera errors
            if error_code in ("RTSP_CONNECTION_FAILED", "SSRC_CAPTURE_FAILED"):
                raise VASRTSPError(
                    error_message,
                    status_code=status,
                    error_code=error_code,
                    details=details,
                    request_id=request_id,
                )
            raise VASServerError(
                error_message,
                status_code=status,
                error_code=error_code,
                details=details,
                request_id=request_id,
            )

        if status == 503:
            if error_code == "MEDIASOUP_UNAVAILABLE":
                raise VASMediaSoupUnavailableError(
                    error_message,
                    request_id=request_id,
                )
            raise VASServerError(
                error_message,
                status_code=status,
                error_code=error_code,
                request_id=request_id,
            )

        if status == 504:
            raise VASRTSPError(
                error_message or "RTSP timeout",
                status_code=status,
                error_code=error_code or "RTSP_TIMEOUT",
                request_id=request_id,
            )

        if status >= 500:
            raise VASServerError(
                error_message,
                status_code=status,
                error_code=error_code,
                details=details,
                request_id=request_id,
            )

        # Generic error for other status codes
        raise VASError(
            error_message,
            status_code=status,
            error_code=error_code,
            details=details,
            request_id=request_id,
        )

    # -------------------------------------------------------------------------
    # Health API
    # -------------------------------------------------------------------------

    async def get_health(self) -> dict[str, Any]:
        """Check VAS service health.

        Returns:
            Health status dict
        """
        response = await self._request(
            "GET",
            "/health",
            authenticated=False,
        )
        return response.json()

    # -------------------------------------------------------------------------
    # Device APIs (V1 - Legacy)
    # -------------------------------------------------------------------------

    async def get_devices(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Device]:
        """List all devices.

        Args:
            skip: Pagination offset
            limit: Max results

        Returns:
            List of devices
        """
        response = await self._request(
            "GET",
            "/api/v1/devices",
            params={"skip": skip, "limit": limit},
            authenticated=False,  # V1 API doesn't require auth
        )
        return [Device.model_validate(d) for d in response.json()]

    async def get_device(self, device_id: str) -> Device:
        """Get device by ID.

        Args:
            device_id: Device UUID

        Returns:
            Device details
        """
        response = await self._request(
            "GET",
            f"/api/v1/devices/{device_id}",
            authenticated=False,
        )
        return Device.model_validate(response.json())

    async def get_device_status(self, device_id: str) -> DeviceStatus:
        """Get device status including streaming state.

        Args:
            device_id: Device UUID

        Returns:
            Device status with streaming info
        """
        response = await self._request(
            "GET",
            f"/api/v1/devices/{device_id}/status",
            authenticated=False,
        )
        return DeviceStatus.model_validate(response.json())

    async def start_stream(self, device_id: str) -> StreamStartResponse:
        """Start streaming from a device.

        Args:
            device_id: Device UUID

        Returns:
            Stream start response with v2_stream_id
        """
        response = await self._request(
            "POST",
            f"/api/v1/devices/{device_id}/start-stream",
            authenticated=False,
            timeout=STREAM_START_TIMEOUT,
        )
        return StreamStartResponse.model_validate(response.json())

    async def stop_stream(self, device_id: str) -> StreamStopResponse:
        """Stop streaming from a device.

        Args:
            device_id: Device UUID

        Returns:
            Stream stop response
        """
        response = await self._request(
            "POST",
            f"/api/v1/devices/{device_id}/stop-stream",
            authenticated=False,
        )
        return StreamStopResponse.model_validate(response.json())

    # -------------------------------------------------------------------------
    # Stream APIs (V2)
    # -------------------------------------------------------------------------

    async def get_streams(
        self,
        state: str | None = None,
        camera_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> StreamListResponse:
        """List streams with optional filtering.

        Args:
            state: Filter by state (LIVE, STOPPED, etc.)
            camera_id: Filter by camera/device ID
            limit: Max results (1-100)
            offset: Pagination offset

        Returns:
            Stream list with pagination
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if state:
            params["state"] = state
        if camera_id:
            params["camera_id"] = camera_id

        response = await self._request("GET", "/v2/streams", params=params)
        return StreamListResponse.model_validate(response.json())

    async def get_stream(self, stream_id: str) -> Stream:
        """Get stream by ID.

        Args:
            stream_id: Stream UUID

        Returns:
            Stream details
        """
        response = await self._request("GET", f"/v2/streams/{stream_id}")
        return Stream.model_validate(response.json())

    async def get_stream_health(self, stream_id: str) -> StreamHealth:
        """Get stream health metrics.

        Args:
            stream_id: Stream UUID

        Returns:
            Stream health status
        """
        response = await self._request("GET", f"/v2/streams/{stream_id}/health")
        return StreamHealth.model_validate(response.json())

    async def delete_stream(self, stream_id: str) -> None:
        """Stop and delete a stream.

        Args:
            stream_id: Stream UUID
        """
        await self._request("DELETE", f"/v2/streams/{stream_id}")

    # -------------------------------------------------------------------------
    # Snapshot APIs
    # -------------------------------------------------------------------------

    async def create_snapshot(
        self,
        stream_id: str,
        request: SnapshotCreateRequest,
    ) -> Snapshot:
        """Create a snapshot from a stream.

        Args:
            stream_id: Stream UUID
            request: Snapshot creation parameters

        Returns:
            Created snapshot (status=processing)
        """
        response = await self._request(
            "POST",
            f"/v2/streams/{stream_id}/snapshots",
            json=request.model_dump(exclude_none=True),
        )
        return Snapshot.model_validate(response.json())

    async def get_snapshot(self, snapshot_id: str) -> Snapshot:
        """Get snapshot by ID.

        Args:
            snapshot_id: Snapshot UUID

        Returns:
            Snapshot details
        """
        response = await self._request("GET", f"/v2/snapshots/{snapshot_id}")
        return Snapshot.model_validate(response.json())

    async def get_snapshots(
        self,
        stream_id: str | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SnapshotListResponse:
        """List snapshots with optional filtering.

        Args:
            stream_id: Filter by stream
            created_by: Filter by creator
            limit: Max results
            offset: Pagination offset

        Returns:
            Snapshot list
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if stream_id:
            params["stream_id"] = stream_id
        if created_by:
            params["created_by"] = created_by

        response = await self._request("GET", "/v2/snapshots", params=params)
        return SnapshotListResponse.model_validate(response.json())

    async def delete_snapshot(self, snapshot_id: str) -> None:
        """Delete a snapshot.

        Args:
            snapshot_id: Snapshot UUID
        """
        await self._request("DELETE", f"/v2/snapshots/{snapshot_id}")

    @asynccontextmanager
    async def download_snapshot_image(
        self,
        snapshot_id: str,
    ) -> AsyncIterator[httpx.Response]:
        """Download snapshot image as streaming response.

        Usage:
            async with client.download_snapshot_image(snapshot_id) as response:
                async for chunk in response.aiter_bytes():
                    # Process image data

        Args:
            snapshot_id: Snapshot UUID

        Yields:
            Streaming HTTP response
        """
        if not self._client:
            raise VASConnectionError("Client not connected")

        token = await self._ensure_valid_token()
        async with self._client.stream(
            "GET",
            f"/v2/snapshots/{snapshot_id}/image",
            headers=self._get_auth_headers(token),
        ) as response:
            self._raise_for_status(response)
            yield response

    # -------------------------------------------------------------------------
    # Bookmark APIs
    # -------------------------------------------------------------------------

    async def create_bookmark(
        self,
        stream_id: str,
        request: BookmarkCreateRequest,
    ) -> Bookmark:
        """Create a bookmark (video clip) from a stream.

        Args:
            stream_id: Stream UUID
            request: Bookmark creation parameters

        Returns:
            Created bookmark (status=processing)
        """
        response = await self._request(
            "POST",
            f"/v2/streams/{stream_id}/bookmarks",
            json=request.model_dump(exclude_none=True),
        )
        return Bookmark.model_validate(response.json())

    async def get_bookmark(self, bookmark_id: str) -> Bookmark:
        """Get bookmark by ID.

        Args:
            bookmark_id: Bookmark UUID

        Returns:
            Bookmark details
        """
        response = await self._request("GET", f"/v2/bookmarks/{bookmark_id}")
        return Bookmark.model_validate(response.json())

    async def get_bookmarks(
        self,
        stream_id: str | None = None,
        event_type: str | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> BookmarkListResponse:
        """List bookmarks with optional filtering.

        Args:
            stream_id: Filter by stream
            event_type: Filter by event type
            created_by: Filter by creator
            limit: Max results
            offset: Pagination offset

        Returns:
            Bookmark list
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if stream_id:
            params["stream_id"] = stream_id
        if event_type:
            params["event_type"] = event_type
        if created_by:
            params["created_by"] = created_by

        response = await self._request("GET", "/v2/bookmarks", params=params)
        return BookmarkListResponse.model_validate(response.json())

    async def delete_bookmark(self, bookmark_id: str) -> None:
        """Delete a bookmark.

        Args:
            bookmark_id: Bookmark UUID
        """
        await self._request("DELETE", f"/v2/bookmarks/{bookmark_id}")

    @asynccontextmanager
    async def download_bookmark_video(
        self,
        bookmark_id: str,
    ) -> AsyncIterator[httpx.Response]:
        """Download bookmark video as streaming response.

        Usage:
            async with client.download_bookmark_video(bookmark_id) as response:
                async for chunk in response.aiter_bytes():
                    # Process video data

        Args:
            bookmark_id: Bookmark UUID

        Yields:
            Streaming HTTP response
        """
        if not self._client:
            raise VASConnectionError("Client not connected")

        token = await self._ensure_valid_token()
        async with self._client.stream(
            "GET",
            f"/v2/bookmarks/{bookmark_id}/video",
            headers=self._get_auth_headers(token),
        ) as response:
            self._raise_for_status(response)
            yield response

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    async def wait_for_stream_live(
        self,
        stream_id: str,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> Stream:
        """Wait for a stream to reach LIVE state.

        Args:
            stream_id: Stream UUID
            timeout: Maximum wait time in seconds
            poll_interval: Time between status checks

        Returns:
            Stream in LIVE state

        Raises:
            VASTimeoutError: If timeout reached
            VASError: If stream enters ERROR/CLOSED state
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            stream = await self.get_stream(stream_id)

            if stream.state.value == "live":
                return stream

            if stream.state.value in ("error", "closed"):
                raise VASError(
                    f"Stream entered {stream.state.value} state",
                    error_code=f"STREAM_{stream.state.value.upper()}",
                )

            await asyncio.sleep(poll_interval)

        raise VASTimeoutError(
            f"Timeout waiting for stream {stream_id} to become LIVE"
        )

    async def wait_for_snapshot_ready(
        self,
        snapshot_id: str,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> Snapshot:
        """Wait for a snapshot to be ready.

        Args:
            snapshot_id: Snapshot UUID
            timeout: Maximum wait time in seconds
            poll_interval: Time between status checks

        Returns:
            Snapshot in ready state

        Raises:
            VASTimeoutError: If timeout reached
            VASError: If processing failed
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            snapshot = await self.get_snapshot(snapshot_id)

            if snapshot.status and snapshot.status.value == "ready":
                return snapshot

            if snapshot.status and snapshot.status.value == "failed":
                raise VASError(
                    f"Snapshot processing failed: {snapshot.error}",
                    error_code="SNAPSHOT_PROCESSING_FAILED",
                )

            await asyncio.sleep(poll_interval)

        raise VASTimeoutError(
            f"Timeout waiting for snapshot {snapshot_id} to be ready"
        )

    async def wait_for_bookmark_ready(
        self,
        bookmark_id: str,
        timeout: float = 60.0,
        poll_interval: float = 2.0,
    ) -> Bookmark:
        """Wait for a bookmark to be ready.

        Args:
            bookmark_id: Bookmark UUID
            timeout: Maximum wait time in seconds
            poll_interval: Time between status checks

        Returns:
            Bookmark in ready state

        Raises:
            VASTimeoutError: If timeout reached
            VASError: If processing failed
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            bookmark = await self.get_bookmark(bookmark_id)

            if bookmark.status and bookmark.status.value == "ready":
                return bookmark

            if bookmark.status and bookmark.status.value == "failed":
                raise VASError(
                    f"Bookmark processing failed: {bookmark.error}",
                    error_code="BOOKMARK_PROCESSING_FAILED",
                )

            await asyncio.sleep(poll_interval)

        raise VASTimeoutError(
            f"Timeout waiting for bookmark {bookmark_id} to be ready"
        )

"""VAS-MS-V2 Integration Layer.

Provides async client for interacting with VAS (Video Analytics Service).

Usage:
    from app.integrations.vas import VASClient

    async with VASClient(base_url, client_id, client_secret) as client:
        # List devices
        devices = await client.get_devices()

        # Start a stream
        stream_info = await client.start_stream(device_id)

        # Create a snapshot
        snapshot = await client.create_snapshot(
            stream_id,
            SnapshotCreateRequest(source="live", created_by="ruth-ai")
        )

        # Wait for snapshot to be ready
        ready_snapshot = await client.wait_for_snapshot_ready(snapshot.id)

Exception Hierarchy:
    VASError (base)
    ├── VASConnectionError - Network/connection failure
    ├── VASTimeoutError - Request timeout
    ├── VASAuthenticationError - 401 (token refresh needed)
    ├── VASRefreshTokenError - Refresh token expired (re-auth needed)
    ├── VASForbiddenError - 403 (no retry)
    ├── VASNotFoundError - 404 (no retry)
    ├── VASValidationError - 400 (no retry)
    ├── VASConflictError - 409 (state conflict)
    │   └── VASStreamNotLiveError - Stream not in LIVE state
    ├── VASServerError - 5xx (retryable)
    │   └── VASMediaSoupUnavailableError - 503 MediaSoup down
    └── VASRTSPError - 502/504 camera errors
"""

from .client import VASClient
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
    BookmarkSource,
    BookmarkStatus,
    Device,
    DeviceStatus,
    Snapshot,
    SnapshotCreateRequest,
    SnapshotListResponse,
    SnapshotSource,
    SnapshotStatus,
    Stream,
    StreamHealth,
    StreamListResponse,
    StreamStartResponse,
    StreamState,
    StreamStopResponse,
    TokenRefreshResponse,
    TokenResponse,
)

__all__ = [
    # Client
    "VASClient",
    # Exceptions
    "VASError",
    "VASConnectionError",
    "VASTimeoutError",
    "VASAuthenticationError",
    "VASRefreshTokenError",
    "VASForbiddenError",
    "VASNotFoundError",
    "VASValidationError",
    "VASConflictError",
    "VASStreamNotLiveError",
    "VASServerError",
    "VASMediaSoupUnavailableError",
    "VASRTSPError",
    # Models - Auth
    "TokenResponse",
    "TokenRefreshResponse",
    # Models - Device
    "Device",
    "DeviceStatus",
    "StreamStartResponse",
    "StreamStopResponse",
    # Models - Stream
    "Stream",
    "StreamState",
    "StreamListResponse",
    "StreamHealth",
    # Models - Snapshot
    "Snapshot",
    "SnapshotStatus",
    "SnapshotSource",
    "SnapshotCreateRequest",
    "SnapshotListResponse",
    # Models - Bookmark
    "Bookmark",
    "BookmarkStatus",
    "BookmarkSource",
    "BookmarkCreateRequest",
    "BookmarkListResponse",
]

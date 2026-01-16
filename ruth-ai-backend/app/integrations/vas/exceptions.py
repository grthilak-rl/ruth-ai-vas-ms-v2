"""VAS API client exceptions.

Defines typed exceptions for VAS API errors to enable
precise error handling and retry logic.
"""

from typing import Any


class VASError(Exception):
    """Base exception for all VAS API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        self.request_id = request_id

    def __str__(self) -> str:
        parts = [self.message]
        if self.error_code:
            parts.append(f"[{self.error_code}]")
        if self.status_code:
            parts.append(f"(HTTP {self.status_code})")
        return " ".join(parts)


class VASConnectionError(VASError):
    """Failed to connect to VAS service."""

    def __init__(self, message: str = "Failed to connect to VAS service") -> None:
        super().__init__(message)


class VASTimeoutError(VASError):
    """VAS request timed out."""

    def __init__(self, message: str = "VAS request timed out") -> None:
        super().__init__(message)


class VASAuthenticationError(VASError):
    """Authentication failed (401 Unauthorized).

    Indicates invalid or expired access token.
    Client should attempt token refresh.
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=401,
            error_code=error_code,
            request_id=request_id,
        )


class VASRefreshTokenError(VASError):
    """Refresh token is invalid or expired.

    Client must re-authenticate with credentials.
    """

    def __init__(
        self,
        message: str = "Refresh token is invalid or expired",
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=401,
            error_code="INVALID_REFRESH_TOKEN",
            request_id=request_id,
        )


class VASForbiddenError(VASError):
    """Access forbidden (403 Forbidden).

    Indicates insufficient scope or permissions.
    Do not retry - requires admin intervention.
    """

    def __init__(
        self,
        message: str = "Access forbidden - insufficient permissions",
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=403,
            error_code=error_code or "INSUFFICIENT_SCOPE",
            request_id=request_id,
        )


class VASNotFoundError(VASError):
    """Resource not found (404 Not Found).

    Do not retry - resource does not exist.
    """

    def __init__(
        self,
        resource_type: str = "Resource",
        resource_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if resource_id:
            message = f"{resource_type} not found: {resource_id}"
        else:
            message = f"{resource_type} not found"
        super().__init__(
            message,
            status_code=404,
            error_code="RESOURCE_NOT_FOUND",
            request_id=request_id,
        )


class VASConflictError(VASError):
    """Conflict error (409 Conflict).

    Indicates state conflict (e.g., stream not LIVE).
    May be retryable after waiting for state change.
    """

    def __init__(
        self,
        message: str = "Resource state conflict",
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=409,
            error_code=error_code,
            details=details,
            request_id=request_id,
        )


class VASValidationError(VASError):
    """Validation error (400 Bad Request).

    Do not retry - fix request parameters.
    """

    def __init__(
        self,
        message: str = "Request validation failed",
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=400,
            error_code="VALIDATION_ERROR",
            details=details,
            request_id=request_id,
        )


class VASServerError(VASError):
    """Server error (5xx).

    May be retryable with backoff.
    """

    def __init__(
        self,
        message: str = "VAS server error",
        status_code: int = 500,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
            details=details,
            request_id=request_id,
        )


class VASMediaSoupUnavailableError(VASServerError):
    """MediaSoup service unavailable (503).

    Retry with backoff.
    """

    def __init__(
        self,
        message: str = "MediaSoup service unavailable",
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=503,
            error_code="MEDIASOUP_UNAVAILABLE",
            request_id=request_id,
        )


class VASRTSPError(VASError):
    """RTSP/Camera related error (502/504).

    May indicate camera offline or unreachable.
    """

    def __init__(
        self,
        message: str = "RTSP connection failed",
        status_code: int = 502,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code or "RTSP_CONNECTION_FAILED",
            details=details,
            request_id=request_id,
        )


class VASStreamNotLiveError(VASConflictError):
    """Stream is not in LIVE state.

    Consumer cannot attach to non-LIVE stream.
    Wait for stream to become LIVE before retrying.
    """

    def __init__(
        self,
        stream_id: str | None = None,
        current_state: str | None = None,
        request_id: str | None = None,
    ) -> None:
        details = {}
        if stream_id:
            details["stream_id"] = stream_id
        if current_state:
            details["current_state"] = current_state
            details["required_state"] = "LIVE"

        super().__init__(
            message=f"Stream is not LIVE (current: {current_state})"
            if current_state
            else "Stream is not LIVE",
            error_code="STREAM_NOT_LIVE",
            details=details,
            request_id=request_id,
        )

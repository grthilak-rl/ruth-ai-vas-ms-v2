"""Centralized error handling and exception-to-HTTP mapping.

This module provides:
1. API-facing error taxonomy (RuthAPIError hierarchy)
2. Exception-to-HTTP mapping for domain and integration errors
3. FastAPI exception handlers for consistent error responses

Error Response Format (per API contract):
{
    "error": "ERROR_CODE",
    "error_description": "Human readable message",
    "status_code": 409,
    "details": { ... },
    "request_id": "<uuid>",
    "timestamp": "<iso8601>"
}

Retry Semantics (via HTTP status codes):
- 5xx → Retryable with backoff
- 429/503 → Retryable with backoff (explicit)
- 4xx (except 409) → NOT retryable
- 409 → May be retryable after state change

Usage:
    from app.core.errors import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from app.core.logging import get_logger

# Import domain exceptions
from app.services.exceptions import (
    DeviceError,
    DeviceInactiveError,
    DeviceNotFoundError,
    DeviceSyncError,
    DuplicateViolationError,
    EvidenceAlreadyExistsError,
    EvidenceCreationError,
    EvidenceError,
    EvidenceNotFoundError,
    EvidencePollingTimeoutError,
    EvidenceStateError,
    EvidenceTerminalStateError,
    EvidenceVASError,
    EventDeviceMissingError,
    EventError,
    EventIngestionError,
    EventSessionMissingError,
    InferenceFailedError,
    NoActiveStreamError,
    ServiceError,
    StreamAlreadyActiveError,
    StreamError,
    StreamNotActiveError,
    StreamSessionNotFoundError,
    StreamStartError,
    StreamStateTransitionError,
    StreamStopError,
    ViolationCreationError,
    ViolationError,
    ViolationNotFoundError,
    ViolationStateError,
    ViolationTerminalStateError,
)

# Import integration exceptions
from app.integrations.vas.exceptions import (
    VASAuthenticationError,
    VASConflictError,
    VASConnectionError,
    VASError,
    VASForbiddenError,
    VASMediaSoupUnavailableError,
    VASNotFoundError,
    VASRTSPError,
    VASServerError,
    VASStreamNotLiveError,
    VASTimeoutError,
    VASValidationError,
)
from app.integrations.ai_runtime.exceptions import (
    AIRuntimeCapabilityError,
    AIRuntimeConnectionError,
    AIRuntimeError,
    AIRuntimeInvalidResponseError,
    AIRuntimeModelNotFoundError,
    AIRuntimeOverloadedError,
    AIRuntimeProtocolError,
    AIRuntimeTimeoutError,
    AIRuntimeUnavailableError,
)

logger = get_logger(__name__)


# =============================================================================
# API Error Taxonomy
# =============================================================================


class RuthAPIError(Exception):
    """Base class for API-facing errors.

    All API errors must define:
    - error_code: SCREAMING_SNAKE_CASE identifier
    - http_status: HTTP status code
    - message: Human-readable description
    - details: Optional additional context (dict)
    """

    error_code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_response(self, request_id: str | None = None) -> dict[str, Any]:
        """Convert to API error response format."""
        return {
            "error": self.error_code,
            "error_description": self.message,
            "status_code": self.http_status,
            "details": self.details if self.details else None,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class ValidationAPIError(RuthAPIError):
    """Request validation failed (400)."""

    error_code = "VALIDATION_ERROR"
    http_status = 400


class NotFoundAPIError(RuthAPIError):
    """Resource not found (404)."""

    error_code = "RESOURCE_NOT_FOUND"
    http_status = 404


class ConflictAPIError(RuthAPIError):
    """State conflict or duplicate resource (409)."""

    error_code = "CONFLICT"
    http_status = 409


class UnauthorizedAPIError(RuthAPIError):
    """Authentication required (401)."""

    error_code = "UNAUTHORIZED"
    http_status = 401


class ForbiddenAPIError(RuthAPIError):
    """Access forbidden (403)."""

    error_code = "FORBIDDEN"
    http_status = 403


class ServiceUnavailableAPIError(RuthAPIError):
    """Downstream service unavailable (503)."""

    error_code = "SERVICE_UNAVAILABLE"
    http_status = 503


class TimeoutAPIError(RuthAPIError):
    """Request or downstream timeout (504)."""

    error_code = "TIMEOUT"
    http_status = 504


class BadGatewayAPIError(RuthAPIError):
    """Upstream service error (502)."""

    error_code = "BAD_GATEWAY"
    http_status = 502


class InternalServerAPIError(RuthAPIError):
    """Internal server error (500)."""

    error_code = "INTERNAL_ERROR"
    http_status = 500


# =============================================================================
# Exception → API Error Mapping
# =============================================================================


def map_domain_exception(exc: ServiceError) -> RuthAPIError:
    """Map domain service exceptions to API errors.

    Args:
        exc: Domain service exception

    Returns:
        Appropriate RuthAPIError subclass
    """
    # -------------------------------------------------------------------------
    # Device Exceptions
    # -------------------------------------------------------------------------
    if isinstance(exc, DeviceNotFoundError):
        return NotFoundAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, DeviceInactiveError):
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, DeviceSyncError):
        return ServiceUnavailableAPIError(
            message="Device synchronization failed",
            details=exc.details,
        )

    # -------------------------------------------------------------------------
    # Stream Exceptions
    # -------------------------------------------------------------------------
    if isinstance(exc, StreamSessionNotFoundError):
        return NotFoundAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, StreamAlreadyActiveError):
        # Idempotent - this should return success, not error
        # But if it does reach here, return conflict
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, StreamNotActiveError):
        # Idempotent stop - this should succeed
        # If it reaches here, return conflict
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, StreamStateTransitionError):
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, (StreamStartError, StreamStopError)):
        return BadGatewayAPIError(
            message=exc.message,
            details=exc.details,
        )

    # -------------------------------------------------------------------------
    # Event Exceptions
    # -------------------------------------------------------------------------
    if isinstance(exc, EventDeviceMissingError):
        return NotFoundAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, EventSessionMissingError):
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, InferenceFailedError):
        return BadGatewayAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, EventIngestionError):
        return InternalServerAPIError(
            message="Event ingestion failed",
            details=exc.details,
        )

    # -------------------------------------------------------------------------
    # Violation Exceptions
    # -------------------------------------------------------------------------
    if isinstance(exc, ViolationNotFoundError):
        return NotFoundAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, (ViolationStateError, ViolationTerminalStateError)):
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, DuplicateViolationError):
        # Idempotent - duplicate should succeed
        # If it reaches here, return conflict with existing ID
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, ViolationCreationError):
        return InternalServerAPIError(
            message="Failed to create violation",
            details=exc.details,
        )

    # -------------------------------------------------------------------------
    # Evidence Exceptions
    # -------------------------------------------------------------------------
    if isinstance(exc, EvidenceNotFoundError):
        return NotFoundAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, EvidenceAlreadyExistsError):
        # Idempotent - this should return success
        # If it reaches here, return conflict with existing ID
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, (EvidenceStateError, EvidenceTerminalStateError)):
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, EvidencePollingTimeoutError):
        return TimeoutAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, NoActiveStreamError):
        return ServiceUnavailableAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, EvidenceVASError):
        return BadGatewayAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, EvidenceCreationError):
        return InternalServerAPIError(
            message="Failed to create evidence",
            details=exc.details,
        )

    # -------------------------------------------------------------------------
    # Generic Service Errors
    # -------------------------------------------------------------------------
    if isinstance(exc, DeviceError):
        return InternalServerAPIError(
            message="Device operation failed",
            details=exc.details,
        )

    if isinstance(exc, StreamError):
        return InternalServerAPIError(
            message="Stream operation failed",
            details=exc.details,
        )

    if isinstance(exc, EventError):
        return InternalServerAPIError(
            message="Event operation failed",
            details=exc.details,
        )

    if isinstance(exc, ViolationError):
        return InternalServerAPIError(
            message="Violation operation failed",
            details=exc.details,
        )

    if isinstance(exc, EvidenceError):
        return InternalServerAPIError(
            message="Evidence operation failed",
            details=exc.details,
        )

    # Base ServiceError
    return InternalServerAPIError(
        message="Service error",
        details=exc.details,
    )


def map_vas_exception(exc: VASError) -> RuthAPIError:
    """Map VAS integration exceptions to API errors.

    Args:
        exc: VAS client exception

    Returns:
        Appropriate RuthAPIError subclass
    """
    if isinstance(exc, VASConnectionError):
        return ServiceUnavailableAPIError(
            message="Video analytics service unavailable",
            details={"vas_error": str(exc)},
        )

    if isinstance(exc, VASTimeoutError):
        return TimeoutAPIError(
            message="Video analytics service timeout",
            details={"vas_error": str(exc)},
        )

    if isinstance(exc, VASAuthenticationError):
        return ServiceUnavailableAPIError(
            message="Video analytics service authentication failed",
            details={"vas_error": str(exc)},
        )

    if isinstance(exc, VASForbiddenError):
        return ForbiddenAPIError(
            message="Access to video analytics resource forbidden",
            details={"vas_error": str(exc)},
        )

    if isinstance(exc, VASNotFoundError):
        return NotFoundAPIError(
            message=exc.message,
            details={"vas_error": str(exc)},
        )

    if isinstance(exc, VASStreamNotLiveError):
        return ServiceUnavailableAPIError(
            message="Stream is not live",
            details=exc.details,
        )

    if isinstance(exc, VASConflictError):
        return ConflictAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, VASValidationError):
        return ValidationAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, VASMediaSoupUnavailableError):
        return ServiceUnavailableAPIError(
            message="Media streaming service unavailable",
            details={"vas_error": str(exc)},
        )

    if isinstance(exc, VASRTSPError):
        return BadGatewayAPIError(
            message="Camera connection failed",
            details=exc.details,
        )

    if isinstance(exc, VASServerError):
        return BadGatewayAPIError(
            message="Video analytics service error",
            details={"vas_error": str(exc)},
        )

    # Generic VAS error
    return BadGatewayAPIError(
        message="Video analytics service error",
        details={"vas_error": str(exc)},
    )


def map_ai_runtime_exception(exc: AIRuntimeError) -> RuthAPIError:
    """Map AI Runtime integration exceptions to API errors.

    Args:
        exc: AI Runtime client exception

    Returns:
        Appropriate RuthAPIError subclass
    """
    if isinstance(exc, AIRuntimeUnavailableError):
        return ServiceUnavailableAPIError(
            message="AI inference service unavailable",
            details=exc.details,
        )

    if isinstance(exc, AIRuntimeConnectionError):
        return ServiceUnavailableAPIError(
            message="Cannot connect to AI inference service",
            details=exc.details,
        )

    if isinstance(exc, AIRuntimeTimeoutError):
        return TimeoutAPIError(
            message="AI inference timeout",
            details=exc.details,
        )

    if isinstance(exc, AIRuntimeOverloadedError):
        return ServiceUnavailableAPIError(
            message="AI inference service overloaded",
            details=exc.details,
        )

    if isinstance(exc, AIRuntimeModelNotFoundError):
        return NotFoundAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, AIRuntimeCapabilityError):
        return BadGatewayAPIError(
            message=exc.message,
            details=exc.details,
        )

    if isinstance(exc, AIRuntimeProtocolError):
        return BadGatewayAPIError(
            message="AI inference protocol error",
            details=exc.details,
        )

    if isinstance(exc, AIRuntimeInvalidResponseError):
        return BadGatewayAPIError(
            message="AI inference returned invalid response",
            details=exc.details,
        )

    # Generic AI Runtime error
    return BadGatewayAPIError(
        message="AI inference service error",
        details=exc.details,
    )


def map_exception_to_api_error(exc: Exception) -> RuthAPIError:
    """Map any exception to an API error.

    This is the main entry point for exception mapping.

    Args:
        exc: Any exception

    Returns:
        Appropriate RuthAPIError subclass
    """
    # Already an API error
    if isinstance(exc, RuthAPIError):
        return exc

    # Domain service exceptions
    if isinstance(exc, ServiceError):
        return map_domain_exception(exc)

    # VAS integration exceptions
    if isinstance(exc, VASError):
        return map_vas_exception(exc)

    # AI Runtime integration exceptions
    if isinstance(exc, AIRuntimeError):
        return map_ai_runtime_exception(exc)

    # Unknown exceptions → Internal Server Error
    return InternalServerAPIError(
        message="An unexpected error occurred",
        details={"exception_type": type(exc).__name__},
    )


# =============================================================================
# Helper Functions
# =============================================================================


def get_request_id(request: Request) -> str | None:
    """Extract request ID from request state."""
    return getattr(request.state, "request_id", None)


def create_error_response(
    api_error: RuthAPIError,
    request_id: str | None = None,
) -> JSONResponse:
    """Create a JSONResponse from an API error.

    Args:
        api_error: The API error
        request_id: Optional request ID for tracing

    Returns:
        JSONResponse with appropriate status code and body
    """
    return JSONResponse(
        status_code=api_error.http_status,
        content=api_error.to_response(request_id),
    )


# =============================================================================
# FastAPI Exception Handlers
# =============================================================================


async def ruth_api_error_handler(
    request: Request,
    exc: RuthAPIError,
) -> JSONResponse:
    """Handle RuthAPIError exceptions."""
    request_id = get_request_id(request)

    logger.warning(
        "API error",
        error_code=exc.error_code,
        status_code=exc.http_status,
        message=exc.message,
        path=request.url.path,
    )

    return create_error_response(exc, request_id)


async def service_error_handler(
    request: Request,
    exc: ServiceError,
) -> JSONResponse:
    """Handle domain service exceptions."""
    request_id = get_request_id(request)
    api_error = map_domain_exception(exc)

    logger.warning(
        "Domain service error",
        exception_type=type(exc).__name__,
        error_code=api_error.error_code,
        status_code=api_error.http_status,
        message=api_error.message,
        path=request.url.path,
    )

    return create_error_response(api_error, request_id)


async def vas_error_handler(
    request: Request,
    exc: VASError,
) -> JSONResponse:
    """Handle VAS integration exceptions."""
    request_id = get_request_id(request)
    api_error = map_vas_exception(exc)

    logger.warning(
        "VAS integration error",
        exception_type=type(exc).__name__,
        vas_status_code=exc.status_code,
        error_code=api_error.error_code,
        status_code=api_error.http_status,
        message=api_error.message,
        path=request.url.path,
    )

    return create_error_response(api_error, request_id)


async def ai_runtime_error_handler(
    request: Request,
    exc: AIRuntimeError,
) -> JSONResponse:
    """Handle AI Runtime integration exceptions."""
    request_id = get_request_id(request)
    api_error = map_ai_runtime_exception(exc)

    logger.warning(
        "AI Runtime integration error",
        exception_type=type(exc).__name__,
        runtime_id=exc.runtime_id,
        error_code=api_error.error_code,
        status_code=api_error.http_status,
        message=api_error.message,
        path=request.url.path,
    )

    return create_error_response(api_error, request_id)


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle FastAPI request validation errors."""
    request_id = get_request_id(request)

    # Format validation errors for response
    error_details = []
    for error in exc.errors():
        error_details.append({
            "loc": list(error.get("loc", [])),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        })

    api_error = ValidationAPIError(
        message="Request validation failed",
        details={"errors": error_details},
    )

    logger.warning(
        "Validation error",
        error_count=len(error_details),
        path=request.url.path,
    )

    return create_error_response(api_error, request_id)


async def pydantic_validation_error_handler(
    request: Request,
    exc: PydanticValidationError,
) -> JSONResponse:
    """Handle Pydantic validation errors (from response serialization)."""
    request_id = get_request_id(request)

    # Format validation errors
    error_details = []
    for error in exc.errors():
        error_details.append({
            "loc": list(error.get("loc", [])),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        })

    api_error = InternalServerAPIError(
        message="Response serialization failed",
        details={"validation_errors": error_details},
    )

    logger.error(
        "Response serialization error",
        error_count=len(error_details),
        path=request.url.path,
    )

    return create_error_response(api_error, request_id)


async def generic_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Fallback handler for uncaught exceptions.

    NEVER leaks internal exception details to clients.
    Always returns a generic 500 Internal Server Error.
    """
    request_id = get_request_id(request)

    # Log the full exception for debugging
    logger.exception(
        "Unhandled exception",
        exception_type=type(exc).__name__,
        path=request.url.path,
    )

    api_error = InternalServerAPIError(
        message="An unexpected error occurred",
    )

    return create_error_response(api_error, request_id)


# =============================================================================
# Registration Function
# =============================================================================


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers with the FastAPI application.

    Args:
        app: FastAPI application instance

    Usage:
        app = FastAPI()
        register_exception_handlers(app)
    """
    # API errors (highest priority - explicit API errors)
    app.add_exception_handler(RuthAPIError, ruth_api_error_handler)

    # Domain service errors
    app.add_exception_handler(ServiceError, service_error_handler)

    # Integration errors
    app.add_exception_handler(VASError, vas_error_handler)
    app.add_exception_handler(AIRuntimeError, ai_runtime_error_handler)

    # Validation errors
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(PydanticValidationError, pydantic_validation_error_handler)

    # Fallback for all other exceptions
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("Exception handlers registered")

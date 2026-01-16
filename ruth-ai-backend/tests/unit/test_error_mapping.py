"""Unit tests for error handling and exception-to-HTTP mapping.

Tests:
- API error taxonomy
- Domain exception mapping
- VAS exception mapping
- AI Runtime exception mapping
- HTTP status code correctness
- Retry semantics preservation
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.core.errors import (
    # API Error Classes
    RuthAPIError,
    ValidationAPIError,
    NotFoundAPIError,
    ConflictAPIError,
    UnauthorizedAPIError,
    ForbiddenAPIError,
    ServiceUnavailableAPIError,
    TimeoutAPIError,
    BadGatewayAPIError,
    InternalServerAPIError,
    # Mapping Functions
    map_domain_exception,
    map_vas_exception,
    map_ai_runtime_exception,
    map_exception_to_api_error,
)

# Domain exceptions
from app.services.exceptions import (
    DeviceNotFoundError,
    DeviceInactiveError,
    DeviceSyncError,
    StreamSessionNotFoundError,
    StreamAlreadyActiveError,
    StreamNotActiveError,
    StreamStateTransitionError,
    StreamStartError,
    StreamStopError,
    EventDeviceMissingError,
    EventSessionMissingError,
    InferenceFailedError,
    EventIngestionError,
    ViolationNotFoundError,
    ViolationStateError,
    ViolationTerminalStateError,
    DuplicateViolationError,
    ViolationCreationError,
    EvidenceNotFoundError,
    EvidenceAlreadyExistsError,
    EvidenceStateError,
    EvidenceTerminalStateError,
    EvidencePollingTimeoutError,
    NoActiveStreamError,
    EvidenceVASError,
    EvidenceCreationError,
    ServiceError,
)

# VAS exceptions
from app.integrations.vas.exceptions import (
    VASConnectionError,
    VASTimeoutError,
    VASAuthenticationError,
    VASForbiddenError,
    VASNotFoundError,
    VASStreamNotLiveError,
    VASConflictError,
    VASValidationError,
    VASMediaSoupUnavailableError,
    VASRTSPError,
    VASServerError,
    VASError,
)

# AI Runtime exceptions
from app.integrations.ai_runtime.exceptions import (
    AIRuntimeUnavailableError,
    AIRuntimeConnectionError,
    AIRuntimeTimeoutError,
    AIRuntimeOverloadedError,
    AIRuntimeModelNotFoundError,
    AIRuntimeCapabilityError,
    AIRuntimeProtocolError,
    AIRuntimeInvalidResponseError,
    AIRuntimeError,
)


class TestAPIErrorTaxonomy:
    """Tests for API error class hierarchy."""

    def test_validation_error_is_400(self):
        """ValidationAPIError returns 400 status."""
        error = ValidationAPIError("Invalid input")
        assert error.http_status == 400
        assert error.error_code == "VALIDATION_ERROR"

    def test_not_found_error_is_404(self):
        """NotFoundAPIError returns 404 status."""
        error = NotFoundAPIError("Resource not found")
        assert error.http_status == 404
        assert error.error_code == "RESOURCE_NOT_FOUND"

    def test_conflict_error_is_409(self):
        """ConflictAPIError returns 409 status."""
        error = ConflictAPIError("State conflict")
        assert error.http_status == 409
        assert error.error_code == "CONFLICT"

    def test_unauthorized_error_is_401(self):
        """UnauthorizedAPIError returns 401 status."""
        error = UnauthorizedAPIError("Authentication required")
        assert error.http_status == 401
        assert error.error_code == "UNAUTHORIZED"

    def test_forbidden_error_is_403(self):
        """ForbiddenAPIError returns 403 status."""
        error = ForbiddenAPIError("Access denied")
        assert error.http_status == 403
        assert error.error_code == "FORBIDDEN"

    def test_service_unavailable_error_is_503(self):
        """ServiceUnavailableAPIError returns 503 status."""
        error = ServiceUnavailableAPIError("Service down")
        assert error.http_status == 503
        assert error.error_code == "SERVICE_UNAVAILABLE"

    def test_timeout_error_is_504(self):
        """TimeoutAPIError returns 504 status."""
        error = TimeoutAPIError("Request timeout")
        assert error.http_status == 504
        assert error.error_code == "TIMEOUT"

    def test_bad_gateway_error_is_502(self):
        """BadGatewayAPIError returns 502 status."""
        error = BadGatewayAPIError("Upstream error")
        assert error.http_status == 502
        assert error.error_code == "BAD_GATEWAY"

    def test_internal_server_error_is_500(self):
        """InternalServerAPIError returns 500 status."""
        error = InternalServerAPIError("Internal error")
        assert error.http_status == 500
        assert error.error_code == "INTERNAL_ERROR"


class TestAPIErrorResponse:
    """Tests for API error response format."""

    def test_to_response_format(self):
        """to_response returns correct format."""
        error = NotFoundAPIError(
            "Device not found",
            details={"device_id": "123"},
        )
        response = error.to_response(request_id="req-456")

        assert response["error"] == "RESOURCE_NOT_FOUND"
        assert response["error_description"] == "Device not found"
        assert response["status_code"] == 404
        assert response["details"] == {"device_id": "123"}
        assert response["request_id"] == "req-456"
        assert "timestamp" in response

    def test_to_response_without_details(self):
        """to_response handles missing details."""
        error = InternalServerAPIError("Error")
        response = error.to_response()

        assert response["details"] is None
        assert response["request_id"] is None


class TestDomainExceptionMapping:
    """Tests for domain exception to API error mapping."""

    # -------------------------------------------------------------------------
    # Device Exceptions
    # -------------------------------------------------------------------------

    def test_device_not_found_maps_to_404(self):
        """DeviceNotFoundError maps to 404 NotFound."""
        exc = DeviceNotFoundError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, NotFoundAPIError)
        assert api_error.http_status == 404

    def test_device_inactive_maps_to_409(self):
        """DeviceInactiveError maps to 409 Conflict."""
        exc = DeviceInactiveError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_device_sync_error_maps_to_503(self):
        """DeviceSyncError maps to 503 ServiceUnavailable."""
        exc = DeviceSyncError("Sync failed")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    # -------------------------------------------------------------------------
    # Stream Exceptions
    # -------------------------------------------------------------------------

    def test_stream_session_not_found_maps_to_404(self):
        """StreamSessionNotFoundError maps to 404 NotFound."""
        exc = StreamSessionNotFoundError(session_id=uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, NotFoundAPIError)
        assert api_error.http_status == 404

    def test_stream_already_active_maps_to_409(self):
        """StreamAlreadyActiveError maps to 409 Conflict."""
        exc = StreamAlreadyActiveError(uuid.uuid4(), uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_stream_not_active_maps_to_409(self):
        """StreamNotActiveError maps to 409 Conflict."""
        exc = StreamNotActiveError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_stream_state_transition_maps_to_409(self):
        """StreamStateTransitionError maps to 409 Conflict."""
        exc = StreamStateTransitionError(uuid.uuid4(), "live", "stopped")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_stream_start_error_maps_to_502(self):
        """StreamStartError maps to 502 BadGateway."""
        exc = StreamStartError(uuid.uuid4(), "VAS failure")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    def test_stream_stop_error_maps_to_502(self):
        """StreamStopError maps to 502 BadGateway."""
        exc = StreamStopError(uuid.uuid4(), "VAS failure")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    # -------------------------------------------------------------------------
    # Event Exceptions
    # -------------------------------------------------------------------------

    def test_event_device_missing_maps_to_404(self):
        """EventDeviceMissingError maps to 404 NotFound."""
        exc = EventDeviceMissingError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, NotFoundAPIError)
        assert api_error.http_status == 404

    def test_event_session_missing_maps_to_409(self):
        """EventSessionMissingError maps to 409 Conflict."""
        exc = EventSessionMissingError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_inference_failed_maps_to_502(self):
        """InferenceFailedError maps to 502 BadGateway."""
        exc = InferenceFailedError(uuid.uuid4(), "Model error")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    def test_event_ingestion_error_maps_to_500(self):
        """EventIngestionError maps to 500 InternalServer."""
        exc = EventIngestionError("Ingestion failed")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, InternalServerAPIError)
        assert api_error.http_status == 500

    # -------------------------------------------------------------------------
    # Violation Exceptions
    # -------------------------------------------------------------------------

    def test_violation_not_found_maps_to_404(self):
        """ViolationNotFoundError maps to 404 NotFound."""
        exc = ViolationNotFoundError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, NotFoundAPIError)
        assert api_error.http_status == 404

    def test_violation_state_error_maps_to_409(self):
        """ViolationStateError maps to 409 Conflict."""
        exc = ViolationStateError(uuid.uuid4(), "open", "resolved")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_violation_terminal_state_maps_to_409(self):
        """ViolationTerminalStateError maps to 409 Conflict."""
        exc = ViolationTerminalStateError(uuid.uuid4(), "resolved")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_duplicate_violation_maps_to_409(self):
        """DuplicateViolationError maps to 409 Conflict."""
        exc = DuplicateViolationError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_violation_creation_error_maps_to_500(self):
        """ViolationCreationError maps to 500 InternalServer."""
        exc = ViolationCreationError("Creation failed")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, InternalServerAPIError)
        assert api_error.http_status == 500

    # -------------------------------------------------------------------------
    # Evidence Exceptions
    # -------------------------------------------------------------------------

    def test_evidence_not_found_maps_to_404(self):
        """EvidenceNotFoundError maps to 404 NotFound."""
        exc = EvidenceNotFoundError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, NotFoundAPIError)
        assert api_error.http_status == 404

    def test_evidence_already_exists_maps_to_409(self):
        """EvidenceAlreadyExistsError maps to 409 Conflict."""
        exc = EvidenceAlreadyExistsError(uuid.uuid4(), "snapshot", uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_evidence_state_error_maps_to_409(self):
        """EvidenceStateError maps to 409 Conflict."""
        exc = EvidenceStateError(uuid.uuid4(), "pending", "ready")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_evidence_terminal_state_maps_to_409(self):
        """EvidenceTerminalStateError maps to 409 Conflict."""
        exc = EvidenceTerminalStateError(uuid.uuid4(), "ready")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_evidence_polling_timeout_maps_to_504(self):
        """EvidencePollingTimeoutError maps to 504 Timeout."""
        exc = EvidencePollingTimeoutError(uuid.uuid4(), 30.0)
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, TimeoutAPIError)
        assert api_error.http_status == 504

    def test_no_active_stream_maps_to_503(self):
        """NoActiveStreamError maps to 503 ServiceUnavailable."""
        exc = NoActiveStreamError(uuid.uuid4())
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    def test_evidence_vas_error_maps_to_502(self):
        """EvidenceVASError maps to 502 BadGateway."""
        exc = EvidenceVASError("VAS failed")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    def test_evidence_creation_error_maps_to_500(self):
        """EvidenceCreationError maps to 500 InternalServer."""
        exc = EvidenceCreationError("Creation failed")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, InternalServerAPIError)
        assert api_error.http_status == 500

    # -------------------------------------------------------------------------
    # Generic Service Error
    # -------------------------------------------------------------------------

    def test_generic_service_error_maps_to_500(self):
        """Generic ServiceError maps to 500 InternalServer."""
        exc = ServiceError("Something failed")
        api_error = map_domain_exception(exc)

        assert isinstance(api_error, InternalServerAPIError)
        assert api_error.http_status == 500


class TestVASExceptionMapping:
    """Tests for VAS exception to API error mapping."""

    def test_vas_connection_error_maps_to_503(self):
        """VASConnectionError maps to 503 ServiceUnavailable."""
        exc = VASConnectionError("Connection refused")
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    def test_vas_timeout_maps_to_504(self):
        """VASTimeoutError maps to 504 Timeout."""
        exc = VASTimeoutError("Request timeout")
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, TimeoutAPIError)
        assert api_error.http_status == 504

    def test_vas_auth_error_maps_to_503(self):
        """VASAuthenticationError maps to 503 ServiceUnavailable."""
        exc = VASAuthenticationError("Auth failed", status_code=401)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    def test_vas_forbidden_maps_to_403(self):
        """VASForbiddenError maps to 403 Forbidden."""
        exc = VASForbiddenError("Access denied", status_code=403)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, ForbiddenAPIError)
        assert api_error.http_status == 403

    def test_vas_not_found_maps_to_404(self):
        """VASNotFoundError maps to 404 NotFound."""
        exc = VASNotFoundError("Stream not found", status_code=404)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, NotFoundAPIError)
        assert api_error.http_status == 404

    def test_vas_stream_not_live_maps_to_503(self):
        """VASStreamNotLiveError maps to 503 ServiceUnavailable."""
        exc = VASStreamNotLiveError("Stream not live", status_code=409)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    def test_vas_conflict_maps_to_409(self):
        """VASConflictError maps to 409 Conflict."""
        exc = VASConflictError("State conflict", status_code=409)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, ConflictAPIError)
        assert api_error.http_status == 409

    def test_vas_validation_maps_to_400(self):
        """VASValidationError maps to 400 Validation."""
        exc = VASValidationError("Invalid request", status_code=400)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, ValidationAPIError)
        assert api_error.http_status == 400

    def test_vas_mediasoup_unavailable_maps_to_503(self):
        """VASMediaSoupUnavailableError maps to 503 ServiceUnavailable."""
        exc = VASMediaSoupUnavailableError("MediaSoup down", status_code=503)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    def test_vas_rtsp_error_maps_to_502(self):
        """VASRTSPError maps to 502 BadGateway."""
        exc = VASRTSPError("Camera connection failed", status_code=502)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    def test_vas_server_error_maps_to_502(self):
        """VASServerError maps to 502 BadGateway."""
        exc = VASServerError("Internal VAS error", status_code=500)
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    def test_generic_vas_error_maps_to_502(self):
        """Generic VASError maps to 502 BadGateway."""
        exc = VASError("VAS error")
        api_error = map_vas_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502


class TestAIRuntimeExceptionMapping:
    """Tests for AI Runtime exception to API error mapping."""

    def test_ai_runtime_unavailable_maps_to_503(self):
        """AIRuntimeUnavailableError maps to 503 ServiceUnavailable."""
        exc = AIRuntimeUnavailableError("Runtime down")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    def test_ai_runtime_connection_maps_to_503(self):
        """AIRuntimeConnectionError maps to 503 ServiceUnavailable."""
        exc = AIRuntimeConnectionError("Cannot connect")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    def test_ai_runtime_timeout_maps_to_504(self):
        """AIRuntimeTimeoutError maps to 504 Timeout."""
        exc = AIRuntimeTimeoutError("Inference timeout")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, TimeoutAPIError)
        assert api_error.http_status == 504

    def test_ai_runtime_overloaded_maps_to_503(self):
        """AIRuntimeOverloadedError maps to 503 ServiceUnavailable."""
        exc = AIRuntimeOverloadedError("Queue full")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, ServiceUnavailableAPIError)
        assert api_error.http_status == 503

    def test_ai_runtime_model_not_found_maps_to_404(self):
        """AIRuntimeModelNotFoundError maps to 404 NotFound."""
        exc = AIRuntimeModelNotFoundError("Model not found")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, NotFoundAPIError)
        assert api_error.http_status == 404

    def test_ai_runtime_capability_maps_to_502(self):
        """AIRuntimeCapabilityError maps to 502 BadGateway."""
        exc = AIRuntimeCapabilityError("Capability mismatch")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    def test_ai_runtime_protocol_maps_to_502(self):
        """AIRuntimeProtocolError maps to 502 BadGateway."""
        exc = AIRuntimeProtocolError("Protocol error")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    def test_ai_runtime_invalid_response_maps_to_502(self):
        """AIRuntimeInvalidResponseError maps to 502 BadGateway."""
        exc = AIRuntimeInvalidResponseError("Invalid response")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502

    def test_generic_ai_runtime_error_maps_to_502(self):
        """Generic AIRuntimeError maps to 502 BadGateway."""
        exc = AIRuntimeError("AI error")
        api_error = map_ai_runtime_exception(exc)

        assert isinstance(api_error, BadGatewayAPIError)
        assert api_error.http_status == 502


class TestMapExceptionToAPIError:
    """Tests for the unified exception mapping function."""

    def test_passes_through_api_errors(self):
        """RuthAPIError passes through unchanged."""
        original = NotFoundAPIError("Not found")
        result = map_exception_to_api_error(original)

        assert result is original

    def test_maps_service_errors(self):
        """ServiceError subclasses are mapped."""
        exc = DeviceNotFoundError(uuid.uuid4())
        result = map_exception_to_api_error(exc)

        assert isinstance(result, NotFoundAPIError)

    def test_maps_vas_errors(self):
        """VASError subclasses are mapped."""
        exc = VASTimeoutError("Timeout")
        result = map_exception_to_api_error(exc)

        assert isinstance(result, TimeoutAPIError)

    def test_maps_ai_runtime_errors(self):
        """AIRuntimeError subclasses are mapped."""
        exc = AIRuntimeTimeoutError("Timeout")
        result = map_exception_to_api_error(exc)

        assert isinstance(result, TimeoutAPIError)

    def test_unknown_exception_maps_to_500(self):
        """Unknown exceptions map to 500 InternalServer."""
        exc = ValueError("Some error")
        result = map_exception_to_api_error(exc)

        assert isinstance(result, InternalServerAPIError)
        assert result.http_status == 500
        assert result.details.get("exception_type") == "ValueError"


class TestRetrySemantics:
    """Tests for retry semantics preservation in HTTP status codes."""

    def test_5xx_errors_are_retryable(self):
        """5xx errors (except some) should be retryable."""
        # 500 - retryable with caution
        assert InternalServerAPIError("Error").http_status == 500

        # 502 - retryable
        assert BadGatewayAPIError("Gateway error").http_status == 502

        # 503 - explicitly retryable
        assert ServiceUnavailableAPIError("Unavailable").http_status == 503

        # 504 - retryable
        assert TimeoutAPIError("Timeout").http_status == 504

    def test_4xx_errors_are_not_retryable(self):
        """Most 4xx errors should NOT be retried."""
        # 400 - not retryable (fix request)
        assert ValidationAPIError("Invalid").http_status == 400

        # 401 - may retry after auth
        assert UnauthorizedAPIError("Unauthorized").http_status == 401

        # 403 - not retryable
        assert ForbiddenAPIError("Forbidden").http_status == 403

        # 404 - not retryable (resource doesn't exist)
        assert NotFoundAPIError("Not found").http_status == 404

    def test_409_may_be_retryable(self):
        """409 Conflict may be retryable after state change."""
        error = ConflictAPIError("State conflict")
        assert error.http_status == 409
        # 409 indicates state-dependent condition
        # Client may retry after the conflicting state is resolved

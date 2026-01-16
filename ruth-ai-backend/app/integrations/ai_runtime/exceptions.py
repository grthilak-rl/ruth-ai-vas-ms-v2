"""AI Runtime client exceptions.

Typed exception hierarchy for AI Runtime integration errors.
Exceptions are transport-agnostic and safe to log.
"""

from typing import Any


class AIRuntimeError(Exception):
    """Base exception for all AI Runtime errors.

    All AI Runtime exceptions inherit from this base class,
    enabling catch-all handling while preserving specific types.
    """

    def __init__(
        self,
        message: str,
        *,
        runtime_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.runtime_id = runtime_id
        self.details = details or {}

    def __str__(self) -> str:
        parts = [self.message]
        if self.runtime_id:
            parts.append(f"[runtime: {self.runtime_id}]")
        return " ".join(parts)


class AIRuntimeUnavailableError(AIRuntimeError):
    """AI Runtime service is unavailable.

    Indicates the runtime cannot be reached due to:
    - Service not running
    - Network connectivity issues
    - Service in unhealthy state

    This error is retryable with backoff.
    """

    def __init__(
        self,
        message: str = "AI Runtime service is unavailable",
        *,
        runtime_id: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        details = {}
        if endpoint:
            details["endpoint"] = endpoint
        super().__init__(message, runtime_id=runtime_id, details=details)
        self.endpoint = endpoint


class AIRuntimeConnectionError(AIRuntimeError):
    """Failed to establish connection to AI Runtime.

    Distinct from unavailable - this indicates a connection
    could not be established at all (DNS failure, refused, etc).

    This error is retryable with backoff.
    """

    def __init__(
        self,
        message: str = "Failed to connect to AI Runtime",
        *,
        runtime_id: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        details = {}
        if endpoint:
            details["endpoint"] = endpoint
        super().__init__(message, runtime_id=runtime_id, details=details)
        self.endpoint = endpoint


class AIRuntimeTimeoutError(AIRuntimeError):
    """AI Runtime request timed out.

    Indicates the runtime did not respond within the configured timeout.
    This may indicate:
    - Runtime overloaded
    - Inference taking too long
    - Network issues

    This error is retryable with backoff (with caution).
    """

    def __init__(
        self,
        message: str = "AI Runtime request timed out",
        *,
        runtime_id: str | None = None,
        timeout_seconds: float | None = None,
        operation: str | None = None,
    ) -> None:
        details = {}
        if timeout_seconds is not None:
            details["timeout_seconds"] = timeout_seconds
        if operation:
            details["operation"] = operation
        super().__init__(message, runtime_id=runtime_id, details=details)
        self.timeout_seconds = timeout_seconds
        self.operation = operation


class AIRuntimeProtocolError(AIRuntimeError):
    """Protocol-level error in AI Runtime communication.

    Indicates a transport or protocol failure:
    - gRPC status errors
    - HTTP errors
    - Serialization failures

    Generally not retryable without fixing the underlying issue.
    """

    def __init__(
        self,
        message: str = "AI Runtime protocol error",
        *,
        runtime_id: str | None = None,
        status_code: int | str | None = None,
        protocol: str | None = None,
    ) -> None:
        details = {}
        if status_code is not None:
            details["status_code"] = status_code
        if protocol:
            details["protocol"] = protocol
        super().__init__(message, runtime_id=runtime_id, details=details)
        self.status_code = status_code
        self.protocol = protocol


class AIRuntimeInvalidResponseError(AIRuntimeError):
    """AI Runtime returned an invalid or malformed response.

    Indicates the response could not be parsed or validated:
    - Missing required fields
    - Invalid field types
    - Schema mismatch

    Not retryable - indicates a contract violation.
    """

    def __init__(
        self,
        message: str = "AI Runtime returned invalid response",
        *,
        runtime_id: str | None = None,
        expected: str | None = None,
        received: str | None = None,
    ) -> None:
        details = {}
        if expected:
            details["expected"] = expected
        if received:
            details["received"] = received
        super().__init__(message, runtime_id=runtime_id, details=details)
        self.expected = expected
        self.received = received


class AIRuntimeCapabilityError(AIRuntimeError):
    """AI Runtime capability mismatch or registration failure.

    Indicates:
    - Runtime does not support requested capability
    - Capability registration failed
    - Required model not available

    May be retryable after capability refresh.
    """

    def __init__(
        self,
        message: str = "AI Runtime capability error",
        *,
        runtime_id: str | None = None,
        capability: str | None = None,
        available_capabilities: list[str] | None = None,
    ) -> None:
        details = {}
        if capability:
            details["requested_capability"] = capability
        if available_capabilities:
            details["available_capabilities"] = available_capabilities
        super().__init__(message, runtime_id=runtime_id, details=details)
        self.capability = capability
        self.available_capabilities = available_capabilities


class AIRuntimeModelNotFoundError(AIRuntimeError):
    """Requested model not found on AI Runtime.

    Indicates the specified model ID or version is not
    available on the runtime.

    Not retryable without model deployment.
    """

    def __init__(
        self,
        model_id: str,
        model_version: str | None = None,
        *,
        runtime_id: str | None = None,
        available_models: list[str] | None = None,
    ) -> None:
        message = f"Model not found: {model_id}"
        if model_version:
            message += f" (version {model_version})"

        details = {
            "model_id": model_id,
        }
        if model_version:
            details["model_version"] = model_version
        if available_models:
            details["available_models"] = available_models

        super().__init__(message, runtime_id=runtime_id, details=details)
        self.model_id = model_id
        self.model_version = model_version
        self.available_models = available_models


class AIRuntimeOverloadedError(AIRuntimeError):
    """AI Runtime is overloaded and cannot accept requests.

    Indicates the runtime is at capacity:
    - Too many concurrent requests
    - Queue full
    - Resource exhaustion

    Retryable with backoff - consider circuit breaker.
    """

    def __init__(
        self,
        message: str = "AI Runtime is overloaded",
        *,
        runtime_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        details = {}
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        super().__init__(message, runtime_id=runtime_id, details=details)
        self.retry_after_seconds = retry_after_seconds

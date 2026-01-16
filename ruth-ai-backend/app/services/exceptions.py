"""Domain service exceptions.

These are business-logic level exceptions, not HTTP or transport errors.
They represent violations of domain rules and invariants.
"""

from typing import Any
from uuid import UUID


class ServiceError(Exception):
    """Base exception for all service-layer errors."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        return self.message


# -----------------------------------------------------------------------------
# Device Service Exceptions
# -----------------------------------------------------------------------------


class DeviceError(ServiceError):
    """Base exception for device-related errors."""

    pass


class DeviceNotFoundError(DeviceError):
    """Device does not exist in local database."""

    def __init__(
        self,
        device_id: UUID | str,
        *,
        vas_device_id: str | None = None,
    ) -> None:
        message = f"Device not found: {device_id}"
        if vas_device_id:
            message += f" (VAS ID: {vas_device_id})"
        super().__init__(message, details={"device_id": str(device_id)})
        self.device_id = device_id
        self.vas_device_id = vas_device_id


class DeviceSyncError(DeviceError):
    """Failed to sync devices from VAS."""

    def __init__(
        self,
        message: str = "Failed to sync devices from VAS",
        *,
        cause: Exception | None = None,
    ) -> None:
        details = {}
        if cause:
            details["cause"] = str(cause)
        super().__init__(message, details=details)
        self.cause = cause


class DeviceInactiveError(DeviceError):
    """Device exists but is not active."""

    def __init__(self, device_id: UUID | str) -> None:
        super().__init__(
            f"Device is inactive: {device_id}",
            details={"device_id": str(device_id)},
        )
        self.device_id = device_id


# -----------------------------------------------------------------------------
# Stream Service Exceptions
# -----------------------------------------------------------------------------


class StreamError(ServiceError):
    """Base exception for stream-related errors."""

    pass


class StreamSessionNotFoundError(StreamError):
    """Stream session does not exist."""

    def __init__(
        self,
        *,
        session_id: UUID | str | None = None,
        device_id: UUID | str | None = None,
    ) -> None:
        if session_id:
            message = f"Stream session not found: {session_id}"
        elif device_id:
            message = f"No active stream session for device: {device_id}"
        else:
            message = "Stream session not found"
        super().__init__(message)
        self.session_id = session_id
        self.device_id = device_id


class StreamAlreadyActiveError(StreamError):
    """Stream is already active for this device."""

    def __init__(
        self,
        device_id: UUID | str,
        session_id: UUID | str,
    ) -> None:
        super().__init__(
            f"Stream already active for device {device_id} (session: {session_id})",
            details={
                "device_id": str(device_id),
                "session_id": str(session_id),
            },
        )
        self.device_id = device_id
        self.session_id = session_id


class StreamNotActiveError(StreamError):
    """No active stream exists for this device."""

    def __init__(self, device_id: UUID | str) -> None:
        super().__init__(
            f"No active stream for device: {device_id}",
            details={"device_id": str(device_id)},
        )
        self.device_id = device_id


class StreamStateTransitionError(StreamError):
    """Invalid state transition attempted."""

    def __init__(
        self,
        session_id: UUID | str,
        current_state: str,
        target_state: str,
    ) -> None:
        super().__init__(
            f"Invalid state transition: {current_state} → {target_state}",
            details={
                "session_id": str(session_id),
                "current_state": current_state,
                "target_state": target_state,
            },
        )
        self.session_id = session_id
        self.current_state = current_state
        self.target_state = target_state


class StreamStartError(StreamError):
    """Failed to start stream."""

    def __init__(
        self,
        device_id: UUID | str,
        reason: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        message = f"Failed to start stream for device {device_id}: {reason}"
        details = {"device_id": str(device_id), "reason": reason}
        if cause:
            details["cause"] = str(cause)
        super().__init__(message, details=details)
        self.device_id = device_id
        self.reason = reason
        self.cause = cause


class StreamStopError(StreamError):
    """Failed to stop stream."""

    def __init__(
        self,
        device_id: UUID | str,
        reason: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        message = f"Failed to stop stream for device {device_id}: {reason}"
        details = {"device_id": str(device_id), "reason": reason}
        if cause:
            details["cause"] = str(cause)
        super().__init__(message, details=details)
        self.device_id = device_id
        self.reason = reason
        self.cause = cause


# -----------------------------------------------------------------------------
# Event Ingestion Exceptions
# -----------------------------------------------------------------------------


class EventError(ServiceError):
    """Base exception for event-related errors."""

    pass


class EventIngestionError(EventError):
    """Failed to ingest event from inference result."""

    def __init__(
        self,
        message: str = "Failed to ingest event",
        *,
        request_id: UUID | str | None = None,
        cause: Exception | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if request_id:
            details["request_id"] = str(request_id)
        if cause:
            details["cause"] = str(cause)
        super().__init__(message, details=details)
        self.request_id = request_id
        self.cause = cause


class EventSessionMissingError(EventError):
    """Event received but no active session exists."""

    def __init__(
        self,
        device_id: UUID | str,
        *,
        stream_id: UUID | str | None = None,
    ) -> None:
        message = f"No active session for device: {device_id}"
        details = {"device_id": str(device_id)}
        if stream_id:
            details["stream_id"] = str(stream_id)
        super().__init__(message, details=details)
        self.device_id = device_id
        self.stream_id = stream_id


class EventDeviceMissingError(EventError):
    """Event received for unknown device."""

    def __init__(
        self,
        device_id: UUID | str,
    ) -> None:
        super().__init__(
            f"Unknown device for event: {device_id}",
            details={"device_id": str(device_id)},
        )
        self.device_id = device_id


class InferenceFailedError(EventError):
    """Inference request failed."""

    def __init__(
        self,
        request_id: UUID | str,
        reason: str,
    ) -> None:
        super().__init__(
            f"Inference failed: {reason}",
            details={
                "request_id": str(request_id),
                "reason": reason,
            },
        )
        self.request_id = request_id
        self.reason = reason


# -----------------------------------------------------------------------------
# Violation Service Exceptions
# -----------------------------------------------------------------------------


class ViolationError(ServiceError):
    """Base exception for violation-related errors."""

    pass


class ViolationNotFoundError(ViolationError):
    """Violation does not exist."""

    def __init__(self, violation_id: UUID | str) -> None:
        super().__init__(
            f"Violation not found: {violation_id}",
            details={"violation_id": str(violation_id)},
        )
        self.violation_id = violation_id


class ViolationStateError(ViolationError):
    """Invalid violation state transition."""

    def __init__(
        self,
        violation_id: UUID | str,
        current_status: str,
        target_status: str,
    ) -> None:
        super().__init__(
            f"Invalid status transition: {current_status} → {target_status}",
            details={
                "violation_id": str(violation_id),
                "current_status": current_status,
                "target_status": target_status,
            },
        )
        self.violation_id = violation_id
        self.current_status = current_status
        self.target_status = target_status


class ViolationTerminalStateError(ViolationError):
    """Violation is in terminal state and cannot be modified."""

    def __init__(
        self,
        violation_id: UUID | str,
        current_status: str,
    ) -> None:
        super().__init__(
            f"Violation {violation_id} is in terminal state: {current_status}",
            details={
                "violation_id": str(violation_id),
                "current_status": current_status,
            },
        )
        self.violation_id = violation_id
        self.current_status = current_status


class ViolationCreationError(ViolationError):
    """Failed to create violation."""

    def __init__(
        self,
        message: str = "Failed to create violation",
        *,
        event_id: UUID | str | None = None,
        device_id: UUID | str | None = None,
        cause: Exception | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if event_id:
            details["event_id"] = str(event_id)
        if device_id:
            details["device_id"] = str(device_id)
        if cause:
            details["cause"] = str(cause)
        super().__init__(message, details=details)
        self.event_id = event_id
        self.device_id = device_id
        self.cause = cause


class DuplicateViolationError(ViolationError):
    """Attempted to create duplicate violation."""

    def __init__(
        self,
        existing_violation_id: UUID | str,
        *,
        device_id: UUID | str | None = None,
        event_id: UUID | str | None = None,
    ) -> None:
        super().__init__(
            f"Open violation already exists: {existing_violation_id}",
            details={
                "existing_violation_id": str(existing_violation_id),
                "device_id": str(device_id) if device_id else None,
                "event_id": str(event_id) if event_id else None,
            },
        )
        self.existing_violation_id = existing_violation_id
        self.device_id = device_id
        self.event_id = event_id


# -----------------------------------------------------------------------------
# Evidence Service Exceptions
# -----------------------------------------------------------------------------


class EvidenceError(ServiceError):
    """Base exception for evidence-related errors."""

    pass


class EvidenceNotFoundError(EvidenceError):
    """Evidence does not exist."""

    def __init__(self, evidence_id: UUID | str) -> None:
        super().__init__(
            f"Evidence not found: {evidence_id}",
            details={"evidence_id": str(evidence_id)},
        )
        self.evidence_id = evidence_id


class EvidenceStateError(EvidenceError):
    """Invalid evidence state transition."""

    def __init__(
        self,
        evidence_id: UUID | str,
        current_status: str,
        target_status: str,
    ) -> None:
        super().__init__(
            f"Invalid status transition: {current_status} → {target_status}",
            details={
                "evidence_id": str(evidence_id),
                "current_status": current_status,
                "target_status": target_status,
            },
        )
        self.evidence_id = evidence_id
        self.current_status = current_status
        self.target_status = target_status


class EvidenceTerminalStateError(EvidenceError):
    """Evidence is in terminal state and cannot be modified."""

    def __init__(
        self,
        evidence_id: UUID | str,
        current_status: str,
    ) -> None:
        super().__init__(
            f"Evidence {evidence_id} is in terminal state: {current_status}",
            details={
                "evidence_id": str(evidence_id),
                "current_status": current_status,
            },
        )
        self.evidence_id = evidence_id
        self.current_status = current_status


class EvidenceCreationError(EvidenceError):
    """Failed to create evidence."""

    def __init__(
        self,
        message: str = "Failed to create evidence",
        *,
        violation_id: UUID | str | None = None,
        evidence_type: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if violation_id:
            details["violation_id"] = str(violation_id)
        if evidence_type:
            details["evidence_type"] = evidence_type
        if cause:
            details["cause"] = str(cause)
        super().__init__(message, details=details)
        self.violation_id = violation_id
        self.evidence_type = evidence_type
        self.cause = cause


class EvidenceAlreadyExistsError(EvidenceError):
    """Evidence of this type already exists for violation."""

    def __init__(
        self,
        violation_id: UUID | str,
        evidence_type: str,
        existing_evidence_id: UUID | str,
    ) -> None:
        super().__init__(
            f"Evidence of type {evidence_type} already exists for violation {violation_id}",
            details={
                "violation_id": str(violation_id),
                "evidence_type": evidence_type,
                "existing_evidence_id": str(existing_evidence_id),
            },
        )
        self.violation_id = violation_id
        self.evidence_type = evidence_type
        self.existing_evidence_id = existing_evidence_id


class EvidencePollingTimeoutError(EvidenceError):
    """Timeout waiting for evidence to become ready."""

    def __init__(
        self,
        evidence_id: UUID | str,
        timeout_seconds: float,
    ) -> None:
        super().__init__(
            f"Timeout waiting for evidence {evidence_id} after {timeout_seconds}s",
            details={
                "evidence_id": str(evidence_id),
                "timeout_seconds": timeout_seconds,
            },
        )
        self.evidence_id = evidence_id
        self.timeout_seconds = timeout_seconds


class EvidenceVASError(EvidenceError):
    """VAS operation failed for evidence."""

    def __init__(
        self,
        message: str,
        *,
        evidence_id: UUID | str | None = None,
        vas_error: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if evidence_id:
            details["evidence_id"] = str(evidence_id)
        if vas_error:
            details["vas_error"] = vas_error
        if cause:
            details["cause"] = str(cause)
        super().__init__(message, details=details)
        self.evidence_id = evidence_id
        self.vas_error = vas_error
        self.cause = cause


class NoActiveStreamError(EvidenceError):
    """No active VAS stream for evidence capture."""

    def __init__(
        self,
        violation_id: UUID | str,
        device_id: UUID | str | None = None,
    ) -> None:
        super().__init__(
            f"No active VAS stream for violation {violation_id}",
            details={
                "violation_id": str(violation_id),
                "device_id": str(device_id) if device_id else None,
            },
        )
        self.violation_id = violation_id
        self.device_id = device_id

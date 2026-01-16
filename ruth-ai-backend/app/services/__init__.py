"""Ruth AI Domain Services.

Business logic layer for Ruth AI backend.
Services orchestrate integrations and enforce domain rules.

Services in this package:
- DeviceService: Device discovery and sync from VAS
- StreamService: Stream lifecycle and session management
- EventIngestionService: AI inference → Event conversion pipeline
- ViolationService: Violation creation, aggregation, and lifecycle
- EvidenceService: Evidence (snapshot/bookmark) orchestration via VAS

Usage:
    from app.services import (
        DeviceService, StreamService, EventIngestionService,
        ViolationService, EvidenceService
    )

    # Create services with injected dependencies
    device_service = DeviceService(vas_client, db)
    stream_service = StreamService(vas_client, ai_runtime_client, db)
    violation_service = ViolationService(db)
    evidence_service = EvidenceService(vas_client, db)
    event_service = EventIngestionService(
        device_service, stream_service, db,
        violation_service=violation_service,
        confidence_threshold=0.7
    )

    # Sync devices from VAS
    devices = await device_service.sync_devices_from_vas()

    # Start a stream
    session = await stream_service.start_stream(device_id)

    # Ingest inference result (creates events → violations)
    events = await event_service.ingest_inference_result(inference_response)

    # Manage violation lifecycle
    violation = await violation_service.mark_reviewed(violation_id, "operator@example.com")

    # Capture evidence for violation
    snapshot = await evidence_service.create_snapshot(violation)
    ready_snapshot = await evidence_service.poll_evidence(snapshot.id)

Exception Hierarchy:
    ServiceError (base)
    ├── DeviceError
    │   ├── DeviceNotFoundError
    │   ├── DeviceSyncError
    │   └── DeviceInactiveError
    ├── StreamError
    │   ├── StreamSessionNotFoundError
    │   ├── StreamAlreadyActiveError
    │   ├── StreamNotActiveError
    │   ├── StreamStateTransitionError
    │   ├── StreamStartError
    │   └── StreamStopError
    ├── EventError
    │   ├── EventIngestionError
    │   ├── EventSessionMissingError
    │   ├── EventDeviceMissingError
    │   └── InferenceFailedError
    ├── ViolationError
    │   ├── ViolationNotFoundError
    │   ├── ViolationStateError
    │   ├── ViolationTerminalStateError
    │   ├── ViolationCreationError
    │   └── DuplicateViolationError
    └── EvidenceError
        ├── EvidenceNotFoundError
        ├── EvidenceStateError
        ├── EvidenceTerminalStateError
        ├── EvidenceCreationError
        ├── EvidenceAlreadyExistsError
        ├── EvidencePollingTimeoutError
        ├── EvidenceVASError
        └── NoActiveStreamError

Design Principles:
    - Services receive dependencies via constructor (DI)
    - Services do NOT create database sessions or clients
    - Services do NOT implement HTTP/API logic
    - Services raise domain exceptions, not HTTP errors
    - Services are the single source of truth for domain state
"""

from .device_service import DeviceService
from .event_ingestion_service import EventIngestionService
from .evidence_service import EvidenceService
from .exceptions import (
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
from .stream_service import StreamService
from .violation_service import ViolationService

__all__ = [
    # Services
    "DeviceService",
    "StreamService",
    "EventIngestionService",
    "ViolationService",
    "EvidenceService",
    # Base Exceptions
    "ServiceError",
    # Device Exceptions
    "DeviceError",
    "DeviceNotFoundError",
    "DeviceSyncError",
    "DeviceInactiveError",
    # Stream Exceptions
    "StreamError",
    "StreamSessionNotFoundError",
    "StreamAlreadyActiveError",
    "StreamNotActiveError",
    "StreamStateTransitionError",
    "StreamStartError",
    "StreamStopError",
    # Event Exceptions
    "EventError",
    "EventIngestionError",
    "EventSessionMissingError",
    "EventDeviceMissingError",
    "InferenceFailedError",
    # Violation Exceptions
    "ViolationError",
    "ViolationNotFoundError",
    "ViolationStateError",
    "ViolationTerminalStateError",
    "ViolationCreationError",
    "DuplicateViolationError",
    # Evidence Exceptions
    "EvidenceError",
    "EvidenceNotFoundError",
    "EvidenceStateError",
    "EvidenceTerminalStateError",
    "EvidenceCreationError",
    "EvidenceAlreadyExistsError",
    "EvidencePollingTimeoutError",
    "EvidenceVASError",
    "NoActiveStreamError",
]

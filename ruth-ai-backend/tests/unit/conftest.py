"""Shared pytest fixtures for unit tests.

Provides:
- Mock VAS client fixtures
- Mock AI Runtime client fixtures
- Mock AsyncSession fixtures
- Test data factories for domain models
"""

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.integrations.ai_runtime import (
    AIRuntimeClient,
    BoundingBox,
    Detection,
    InferenceResponse,
    InferenceStatus,
    ModelCapability,
    ModelStatus,
    RuntimeCapabilities,
    RuntimeHealth,
    RuntimeStatus,
)
from app.integrations.vas import (
    VASClient,
    Bookmark,
    BookmarkStatus,
    Device as VASDevice,
    DeviceStatus,
    Snapshot,
    SnapshotStatus,
    Stream,
    StreamHealth,
    StreamStartResponse,
    StreamStopResponse,
    StreamState as VASStreamState,
)
from app.models import (
    Device,
    Event,
    EventType,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    StreamSession,
    StreamState,
    Violation,
    ViolationStatus,
    ViolationType,
)


# -----------------------------------------------------------------------------
# UUID Generators
# -----------------------------------------------------------------------------


def make_uuid() -> uuid.UUID:
    """Generate a new UUID."""
    return uuid.uuid4()


# -----------------------------------------------------------------------------
# Mock AsyncSession Fixture
# -----------------------------------------------------------------------------


class MockAsyncSession:
    """Mock AsyncSession for unit tests.

    Tracks added objects and provides basic query simulation.
    """

    def __init__(self) -> None:
        self._added: list[Any] = []
        self._deleted: list[Any] = []
        self._committed = False
        self._flushed = False
        self._query_results: dict[type, list[Any]] = {}

    def add(self, obj: Any) -> None:
        """Track added object."""
        self._added.append(obj)
        # Assign ID if not set
        if hasattr(obj, "id") and obj.id is None:
            obj.id = make_uuid()

    def delete(self, obj: Any) -> None:
        """Track deleted object."""
        self._deleted.append(obj)

    async def commit(self) -> None:
        """Simulate commit."""
        self._committed = True

    async def flush(self) -> None:
        """Simulate flush - assigns IDs to new objects."""
        self._flushed = True
        for obj in self._added:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = make_uuid()

    async def rollback(self) -> None:
        """Simulate rollback."""
        self._added.clear()
        self._deleted.clear()

    async def refresh(self, obj: Any) -> None:
        """Simulate refresh (no-op in mock)."""
        pass

    async def execute(self, stmt: Any) -> "MockResult":
        """Simulate query execution."""
        return MockResult(self._query_results)

    def set_query_result(self, model_type: type, results: list[Any]) -> None:
        """Set expected query results for a model type."""
        self._query_results[model_type] = results

    def get_added(self) -> list[Any]:
        """Get all added objects."""
        return self._added.copy()

    def get_added_of_type(self, model_type: type) -> list[Any]:
        """Get added objects of specific type."""
        return [obj for obj in self._added if isinstance(obj, model_type)]


class MockResult:
    """Mock result for query execution."""

    def __init__(self, query_results: dict[type, list[Any]]) -> None:
        self._results = query_results
        self._scalar_result: Any = None

    def scalar_one_or_none(self) -> Any:
        """Return single result or None."""
        return self._scalar_result

    def scalars(self) -> "MockScalars":
        """Return scalars wrapper."""
        return MockScalars(self._results)

    def scalar_one(self) -> Any:
        """Return single result."""
        if self._scalar_result is None:
            raise ValueError("No result found")
        return self._scalar_result


class MockScalars:
    """Mock scalars result."""

    def __init__(self, results: dict[type, list[Any]]) -> None:
        self._results = results
        self._all_results: list[Any] = []
        for items in results.values():
            self._all_results.extend(items)

    def all(self) -> list[Any]:
        """Return all results."""
        return self._all_results

    def first(self) -> Any:
        """Return first result or None."""
        return self._all_results[0] if self._all_results else None


@pytest.fixture
def mock_db() -> MockAsyncSession:
    """Provide a mock database session."""
    return MockAsyncSession()


# -----------------------------------------------------------------------------
# Mock VAS Client Fixture
# -----------------------------------------------------------------------------


class MockVASClient:
    """Mock VAS client for unit tests."""

    def __init__(self) -> None:
        self._devices: list[VASDevice] = []
        self._streams: dict[str, Stream] = {}
        self._snapshots: dict[str, Snapshot] = {}
        self._bookmarks: dict[str, Bookmark] = {}
        self._should_fail: dict[str, Exception] = {}

    def set_devices(self, devices: list[VASDevice]) -> None:
        """Set devices to return from get_devices."""
        self._devices = devices

    def set_failure(self, method: str, error: Exception) -> None:
        """Make a method raise an exception."""
        self._should_fail[method] = error

    def clear_failure(self, method: str) -> None:
        """Clear failure for a method."""
        self._should_fail.pop(method, None)

    def _check_failure(self, method: str) -> None:
        """Raise configured failure if set."""
        if method in self._should_fail:
            raise self._should_fail[method]

    async def get_devices(self) -> list[VASDevice]:
        """Get all devices."""
        self._check_failure("get_devices")
        return self._devices

    async def get_device(self, device_id: str) -> VASDevice:
        """Get single device."""
        self._check_failure("get_device")
        for device in self._devices:
            if device.id == device_id:
                return device
        from app.integrations.vas import VASNotFoundError
        raise VASNotFoundError(f"Device not found: {device_id}")

    async def start_stream(self, device_id: str) -> StreamStartResponse:
        """Start stream for device."""
        self._check_failure("start_stream")
        stream_id = str(make_uuid())
        return StreamStartResponse(
            camera_id=device_id,
            stream_id=stream_id,
            v2_stream_id=stream_id,
            state=VASStreamState.LIVE,
            message="Stream started",
        )

    async def stop_stream(self, device_id: str) -> StreamStopResponse:
        """Stop stream for device."""
        self._check_failure("stop_stream")
        return StreamStopResponse(
            camera_id=device_id,
            message="Stream stopped",
        )

    async def create_snapshot(
        self,
        stream_id: str,
        request: Any,
    ) -> Snapshot:
        """Create snapshot."""
        self._check_failure("create_snapshot")
        snapshot_id = str(make_uuid())
        snapshot = Snapshot(
            id=snapshot_id,
            stream_id=stream_id,
            status=SnapshotStatus.PROCESSING,
            created_at=datetime.now(timezone.utc),
        )
        self._snapshots[snapshot_id] = snapshot
        return snapshot

    async def get_snapshot(self, snapshot_id: str) -> Snapshot:
        """Get snapshot by ID."""
        self._check_failure("get_snapshot")
        if snapshot_id in self._snapshots:
            return self._snapshots[snapshot_id]
        from app.integrations.vas import VASNotFoundError
        raise VASNotFoundError(f"Snapshot not found: {snapshot_id}")

    async def create_bookmark(
        self,
        stream_id: str,
        request: Any,
    ) -> Bookmark:
        """Create bookmark."""
        self._check_failure("create_bookmark")
        bookmark_id = str(make_uuid())
        bookmark = Bookmark(
            id=bookmark_id,
            stream_id=stream_id,
            status=BookmarkStatus.PROCESSING,
            created_at=datetime.now(timezone.utc),
        )
        self._bookmarks[bookmark_id] = bookmark
        return bookmark

    async def get_bookmark(self, bookmark_id: str) -> Bookmark:
        """Get bookmark by ID."""
        self._check_failure("get_bookmark")
        if bookmark_id in self._bookmarks:
            return self._bookmarks[bookmark_id]
        from app.integrations.vas import VASNotFoundError
        raise VASNotFoundError(f"Bookmark not found: {bookmark_id}")

    def mark_snapshot_ready(self, snapshot_id: str) -> None:
        """Mark a snapshot as ready."""
        if snapshot_id in self._snapshots:
            self._snapshots[snapshot_id].status = SnapshotStatus.READY

    def mark_bookmark_ready(self, bookmark_id: str) -> None:
        """Mark a bookmark as ready."""
        if bookmark_id in self._bookmarks:
            self._bookmarks[bookmark_id].status = BookmarkStatus.READY


@pytest.fixture
def mock_vas_client() -> MockVASClient:
    """Provide a mock VAS client."""
    return MockVASClient()


# -----------------------------------------------------------------------------
# Mock AI Runtime Client Fixture
# -----------------------------------------------------------------------------


class MockAIRuntimeClient:
    """Mock AI Runtime client for unit tests."""

    def __init__(self) -> None:
        self._healthy = True
        self._capabilities: RuntimeCapabilities | None = None
        self._should_fail: dict[str, Exception] = {}

    def set_healthy(self, healthy: bool) -> None:
        """Set health status."""
        self._healthy = healthy

    def set_capabilities(self, caps: RuntimeCapabilities) -> None:
        """Set runtime capabilities."""
        self._capabilities = caps

    def set_failure(self, method: str, error: Exception) -> None:
        """Make a method raise an exception."""
        self._should_fail[method] = error

    def _check_failure(self, method: str) -> None:
        """Raise configured failure if set."""
        if method in self._should_fail:
            raise self._should_fail[method]

    async def is_healthy(self) -> bool:
        """Check if runtime is healthy."""
        self._check_failure("is_healthy")
        return self._healthy

    async def get_capabilities(
        self,
        force_refresh: bool = False,
    ) -> RuntimeCapabilities:
        """Get runtime capabilities."""
        self._check_failure("get_capabilities")
        if self._capabilities is None:
            self._capabilities = RuntimeCapabilities(
                runtime_id="test-runtime",
                supported_models=[
                    ModelCapability(
                        model_id="fall_detection",
                        version="1.0.0",
                        status=ModelStatus.READY,
                    )
                ],
            )
        return self._capabilities

    def has_model(self, model_id: str) -> bool:
        """Check if model is available."""
        if self._capabilities is None:
            return False
        return self._capabilities.has_model(model_id)


@pytest.fixture
def mock_ai_runtime_client() -> MockAIRuntimeClient:
    """Provide a mock AI Runtime client."""
    return MockAIRuntimeClient()


# -----------------------------------------------------------------------------
# Test Data Factories
# -----------------------------------------------------------------------------


@pytest.fixture
def device_factory():
    """Factory for creating test Device instances."""
    def _create(
        *,
        id: uuid.UUID | None = None,
        vas_device_id: str | None = None,
        name: str = "Test Camera",
        description: str | None = "Test camera description",
        location: str | None = "Test Location",
        is_active: bool = True,
    ) -> Device:
        device = Device(
            vas_device_id=vas_device_id or f"vas-{make_uuid()}",
            name=name,
            description=description,
            location=location,
            is_active=is_active,
            last_synced_at=datetime.now(timezone.utc),
        )
        device.id = id or make_uuid()
        return device
    return _create


@pytest.fixture
def vas_device_factory():
    """Factory for creating test VAS Device instances."""
    def _create(
        *,
        id: str | None = None,
        name: str = "VAS Test Camera",
        description: str | None = "VAS test camera",
        location: str | None = "VAS Location",
        is_active: bool = True,
    ) -> VASDevice:
        return VASDevice(
            id=id or f"vas-{make_uuid()}",
            name=name,
            description=description,
            location=location,
            status=DeviceStatus.ONLINE if is_active else DeviceStatus.OFFLINE,
            is_active=is_active,
        )
    return _create


@pytest.fixture
def stream_session_factory(device_factory):
    """Factory for creating test StreamSession instances."""
    def _create(
        *,
        id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        vas_stream_id: str | None = None,
        state: StreamState = StreamState.LIVE,
        model_id: str = "fall_detection",
        model_version: str | None = "1.0.0",
        inference_fps: int = 10,
        confidence_threshold: float = 0.7,
        error_message: str | None = None,
    ) -> StreamSession:
        session = StreamSession(
            device_id=device_id or make_uuid(),
            vas_stream_id=vas_stream_id or str(make_uuid()),
            state=state,
            model_id=model_id,
            model_version=model_version,
            inference_fps=inference_fps,
            confidence_threshold=confidence_threshold,
            started_at=datetime.now(timezone.utc),
            error_message=error_message,
        )
        session.id = id or make_uuid()
        return session
    return _create


@pytest.fixture
def event_factory(device_factory):
    """Factory for creating test Event instances."""
    def _create(
        *,
        id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        stream_session_id: uuid.UUID | None = None,
        event_type: EventType = EventType.FALL_DETECTED,
        confidence: float = 0.85,
        timestamp: datetime | None = None,
        model_id: str = "fall_detection",
        model_version: str = "1.0.0",
        bounding_boxes: list[dict] | None = None,
        frame_id: str | None = None,
        violation_id: uuid.UUID | None = None,
    ) -> Event:
        event = Event(
            device_id=device_id or make_uuid(),
            stream_session_id=stream_session_id,
            event_type=event_type,
            confidence=confidence,
            timestamp=timestamp or datetime.now(timezone.utc),
            model_id=model_id,
            model_version=model_version,
            bounding_boxes=bounding_boxes,
            frame_id=frame_id or str(make_uuid()),
            violation_id=violation_id,
        )
        event.id = id or make_uuid()
        return event
    return _create


@pytest.fixture
def violation_factory(device_factory):
    """Factory for creating test Violation instances."""
    def _create(
        *,
        id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        stream_session_id: uuid.UUID | None = None,
        type: ViolationType = ViolationType.FALL_DETECTED,
        status: ViolationStatus = ViolationStatus.OPEN,
        confidence: float = 0.85,
        timestamp: datetime | None = None,
        camera_name: str = "Test Camera",
        model_id: str = "fall_detection",
        model_version: str = "1.0.0",
        bounding_boxes: list[dict] | None = None,
        reviewed_by: str | None = None,
        reviewed_at: datetime | None = None,
        resolution_notes: str | None = None,
    ) -> Violation:
        violation = Violation(
            device_id=device_id or make_uuid(),
            stream_session_id=stream_session_id,
            type=type,
            status=status,
            confidence=confidence,
            timestamp=timestamp or datetime.now(timezone.utc),
            camera_name=camera_name,
            model_id=model_id,
            model_version=model_version,
            bounding_boxes=bounding_boxes,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            resolution_notes=resolution_notes,
        )
        violation.id = id or make_uuid()
        return violation
    return _create


@pytest.fixture
def evidence_factory(violation_factory):
    """Factory for creating test Evidence instances."""
    def _create(
        *,
        id: uuid.UUID | None = None,
        violation_id: uuid.UUID | None = None,
        evidence_type: EvidenceType = EvidenceType.SNAPSHOT,
        status: EvidenceStatus = EvidenceStatus.PENDING,
        vas_snapshot_id: str | None = None,
        vas_bookmark_id: str | None = None,
        bookmark_duration_seconds: int | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> Evidence:
        evidence = Evidence(
            violation_id=violation_id or make_uuid(),
            evidence_type=evidence_type,
            status=status,
            vas_snapshot_id=vas_snapshot_id,
            vas_bookmark_id=vas_bookmark_id,
            bookmark_duration_seconds=bookmark_duration_seconds,
            error_message=error_message,
            retry_count=retry_count,
            requested_at=datetime.now(timezone.utc),
        )
        evidence.id = id or make_uuid()
        return evidence
    return _create


@pytest.fixture
def inference_response_factory():
    """Factory for creating test InferenceResponse instances."""
    def _create(
        *,
        request_id: uuid.UUID | None = None,
        stream_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        status: InferenceStatus = InferenceStatus.COMPLETED,
        timestamp: datetime | None = None,
        model_id: str = "fall_detection",
        model_version: str | None = "1.0.0",
        detections: list[Detection] | None = None,
        inference_time_ms: float | None = 15.5,
        error: str | None = None,
    ) -> InferenceResponse:
        return InferenceResponse(
            request_id=request_id or make_uuid(),
            stream_id=stream_id or make_uuid(),
            device_id=device_id,
            status=status,
            timestamp=timestamp or datetime.now(timezone.utc),
            model_id=model_id,
            model_version=model_version,
            detections=detections or [],
            inference_time_ms=inference_time_ms,
            error=error,
        )
    return _create


@pytest.fixture
def detection_factory():
    """Factory for creating test Detection instances."""
    def _create(
        *,
        detection_id: str | None = None,
        class_name: str = "fall_detected",
        confidence: float = 0.85,
        bounding_box: BoundingBox | None = None,
    ) -> Detection:
        return Detection(
            detection_id=detection_id or str(make_uuid()),
            class_name=class_name,
            confidence=confidence,
            bounding_box=bounding_box or BoundingBox(
                x=100, y=150, width=200, height=300, confidence=confidence
            ),
        )
    return _create

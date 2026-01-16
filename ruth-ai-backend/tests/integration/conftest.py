"""Shared pytest fixtures for integration tests.

Provides:
- Test database setup and teardown
- Test application with overridden dependencies
- Mock VAS client fixture
- Mock AI Runtime client fixture
- HTTP client for API testing
- Factory fixtures for test data
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Set test environment before importing app
os.environ["RUTH_AI_ENV"] = "test"
os.environ["RUTH_AI_LOG_LEVEL"] = "warning"
os.environ["RUTH_AI_LOG_FORMAT"] = "text"

from app.core.config import Settings, get_settings
from app.core.database import (
    _async_session_factory,
    _engine,
    get_db_session,
)
from app.deps.services import set_vas_client, get_vas_client
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
from app.main import create_application
from app.models import Base


# -----------------------------------------------------------------------------
# Test Settings Override
# -----------------------------------------------------------------------------


def get_test_settings() -> Settings:
    """Get test-specific settings with SQLite."""
    return Settings(
        ruth_ai_env="test",
        ruth_ai_log_level="warning",
        ruth_ai_log_format="text",
        database_url="postgresql+asyncpg://ruth:ruth@localhost:5432/ruth_ai_test",
        database_pool_size=5,
        database_pool_overflow=2,
    )


# -----------------------------------------------------------------------------
# Database Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create test database engine.

    Uses PostgreSQL test database. Assumes database exists.
    """
    settings = get_test_settings()

    engine = create_async_engine(
        str(settings.database_url),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_overflow,
        pool_pre_ping=True,
        echo=False,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(
    test_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test.

    Rolls back after each test to ensure isolation.
    """
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def clean_db(test_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Clean database tables before and after each test."""
    # Tables to clean (in order due to FK constraints)
    tables = [
        "evidence",
        "events",
        "violations",
        "stream_sessions",
        "devices",
    ]

    async with test_engine.begin() as conn:
        for table in tables:
            try:
                await conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
            except Exception:
                pass  # Table might not exist yet

    yield

    async with test_engine.begin() as conn:
        for table in tables:
            try:
                await conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
            except Exception:
                pass


# -----------------------------------------------------------------------------
# Mock VAS Client
# -----------------------------------------------------------------------------


class MockVASClient:
    """Mock VAS client for integration tests.

    Simulates VAS API responses without making real network calls.
    """

    def __init__(self) -> None:
        self._devices: list[VASDevice] = []
        self._streams: dict[str, Stream] = {}
        self._snapshots: dict[str, Snapshot] = {}
        self._bookmarks: dict[str, Bookmark] = {}
        self._failures: dict[str, Exception] = {}

    def set_devices(self, devices: list[VASDevice]) -> None:
        """Set devices to return from API calls."""
        self._devices = devices

    def add_device(self, device: VASDevice) -> None:
        """Add a single device."""
        self._devices.append(device)

    def set_failure(self, method: str, error: Exception) -> None:
        """Make a method raise an exception."""
        self._failures[method] = error

    def clear_failure(self, method: str) -> None:
        """Clear failure for a method."""
        self._failures.pop(method, None)

    def _check_failure(self, method: str) -> None:
        """Raise configured failure if set."""
        if method in self._failures:
            raise self._failures[method]

    async def authenticate(self) -> None:
        """Mock authentication."""
        self._check_failure("authenticate")

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
        raise VASNotFoundError(f"Device not found: {device_id}", status_code=404)

    async def start_stream(self, device_id: str) -> StreamStartResponse:
        """Start stream for device."""
        self._check_failure("start_stream")
        stream_id = str(uuid.uuid4())
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

    async def get_stream_health(self, stream_id: str) -> StreamHealth:
        """Get stream health."""
        self._check_failure("get_stream_health")
        return StreamHealth(
            stream_id=stream_id,
            state=VASStreamState.LIVE,
            is_healthy=True,
        )

    async def create_snapshot(
        self,
        stream_id: str,
        request,
    ) -> Snapshot:
        """Create snapshot."""
        self._check_failure("create_snapshot")
        snapshot_id = str(uuid.uuid4())
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
        raise VASNotFoundError(f"Snapshot not found: {snapshot_id}", status_code=404)

    async def create_bookmark(
        self,
        stream_id: str,
        request,
    ) -> Bookmark:
        """Create bookmark."""
        self._check_failure("create_bookmark")
        bookmark_id = str(uuid.uuid4())
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
        raise VASNotFoundError(f"Bookmark not found: {bookmark_id}", status_code=404)

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
# Test Application
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(
    test_engine: AsyncEngine,
    mock_vas_client: MockVASClient,
    clean_db,
):
    """Create test application with mocked dependencies."""
    import app.core.database as db_module
    import app.deps.services as services_module

    # Create session factory for tests
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    # Override database globals
    db_module._engine = test_engine
    db_module._async_session_factory = session_factory

    # Override VAS client
    services_module._vas_client = mock_vas_client

    # Create application without lifespan (we manage DB ourselves)
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app import __version__
    from app.api.internal import events as internal_events
    from app.api.v1 import analytics, devices, events, health, violations
    from app.core.errors import register_exception_handlers
    from app.core.metrics import create_metrics_router
    from app.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware

    test_app = FastAPI(
        title="Ruth AI Backend - Test",
        description="Test instance",
        version=__version__,
    )

    test_app.add_middleware(RequestIDMiddleware)
    test_app.add_middleware(RequestLoggingMiddleware)

    # Register routers
    test_app.include_router(health.router, prefix="/api/v1")
    test_app.include_router(devices.router, prefix="/api/v1")
    test_app.include_router(events.router, prefix="/api/v1")
    test_app.include_router(violations.router, prefix="/api/v1")
    test_app.include_router(analytics.router, prefix="/api/v1")
    test_app.include_router(internal_events.router, prefix="/internal")
    test_app.include_router(create_metrics_router())

    register_exception_handlers(test_app)

    yield test_app

    # Cleanup
    db_module._engine = None
    db_module._async_session_factory = None
    services_module._vas_client = None


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# -----------------------------------------------------------------------------
# Test Data Factories
# -----------------------------------------------------------------------------


def make_uuid() -> uuid.UUID:
    """Generate a new UUID."""
    return uuid.uuid4()


@pytest.fixture
def vas_device_factory():
    """Factory for creating VAS Device instances."""
    def _create(
        *,
        id: str | None = None,
        name: str = "Test Camera",
        description: str | None = "Test camera description",
        location: str | None = "Test Location",
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
def event_payload_factory():
    """Factory for creating event ingestion payloads."""
    def _create(
        *,
        device_id: uuid.UUID | None = None,
        stream_session_id: uuid.UUID | None = None,
        event_type: str = "fall_detected",
        confidence: float = 0.85,
        timestamp: datetime | None = None,
        model_id: str = "fall_detection",
        model_version: str = "1.0.0",
        bounding_boxes: list[dict] | None = None,
    ) -> dict:
        payload = {
            "device_id": str(device_id or make_uuid()),
            "event_type": event_type,
            "confidence": confidence,
            "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
            "model_id": model_id,
            "model_version": model_version,
        }
        if stream_session_id:
            payload["stream_session_id"] = str(stream_session_id)
        if bounding_boxes:
            payload["bounding_boxes"] = bounding_boxes
        return payload
    return _create


# -----------------------------------------------------------------------------
# Helper Fixtures
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_device(
    test_engine: AsyncEngine,
    vas_device_factory,
    mock_vas_client: MockVASClient,
) -> dict:
    """Create a device in the database and mock VAS client.

    Returns dict with device info including IDs.
    """
    from app.models import Device

    vas_device_id = f"vas-{make_uuid()}"
    vas_device = vas_device_factory(id=vas_device_id, name="Seeded Camera")
    mock_vas_client.add_device(vas_device)

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        device = Device(
            vas_device_id=vas_device_id,
            name="Seeded Camera",
            description="Test device for integration tests",
            location="Test Location",
            is_active=True,
            last_synced_at=datetime.now(timezone.utc),
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)

        return {
            "id": device.id,
            "vas_device_id": device.vas_device_id,
            "name": device.name,
        }


@pytest_asyncio.fixture
async def seeded_violation(
    test_engine: AsyncEngine,
    seeded_device: dict,
) -> dict:
    """Create a violation in the database.

    Returns dict with violation info including IDs.
    """
    from app.models import Violation, ViolationType, ViolationStatus

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        violation = Violation(
            device_id=seeded_device["id"],
            type=ViolationType.FALL_DETECTED,
            status=ViolationStatus.OPEN,
            confidence=0.85,
            timestamp=datetime.now(timezone.utc),
            camera_name=seeded_device["name"],
            model_id="fall_detection",
            model_version="1.0.0",
        )
        session.add(violation)
        await session.commit()
        await session.refresh(violation)

        return {
            "id": violation.id,
            "device_id": violation.device_id,
            "type": violation.type.value,
            "status": violation.status.value,
        }


@pytest_asyncio.fixture
async def seeded_stream_session(
    test_engine: AsyncEngine,
    seeded_device: dict,
) -> dict:
    """Create a stream session in the database.

    Returns dict with session info including IDs.
    """
    from app.models import StreamSession, StreamState

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        stream_session = StreamSession(
            device_id=seeded_device["id"],
            vas_stream_id=str(make_uuid()),
            state=StreamState.LIVE,
            model_id="fall_detection",
            model_version="1.0.0",
            inference_fps=10,
            confidence_threshold=0.7,
            started_at=datetime.now(timezone.utc),
        )
        session.add(stream_session)
        await session.commit()
        await session.refresh(stream_session)

        return {
            "id": stream_session.id,
            "device_id": stream_session.device_id,
            "vas_stream_id": stream_session.vas_stream_id,
            "state": stream_session.state.value,
        }

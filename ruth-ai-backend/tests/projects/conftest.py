"""Fixtures for DB-backed project-archiving tests.

Needs a throwaway Postgres — the archiver uses INSERT ... SELECT with enum
casts, ON COMMIT DROP temp tables, advisory locks and partial unique
indexes, none of which SQLite can stand in for. Point it at a scratch
database:

    PROJECT_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

The tests are skipped when the variable is unset, matching tests/model_store.

Every table in `Base.metadata` is created, because the archive walks the
whole detection schema (devices, stream_sessions, violations, events,
evidence, bookmark_analyses, projects and the five archive tables) and the
FK ordering it depends on is exactly what is under test.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    Base,
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
from app.services.device_service import DeviceService

DATABASE_URL = os.environ.get("PROJECT_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="PROJECT_TEST_DATABASE_URL not set"
)


@pytest.fixture
async def engine():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        # Drop first: enum types survive a dropped table and would collide.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def device_service(db) -> DeviceService:
    """DeviceService for list/count assertions.

    Those two methods never touch VAS, so the client can be None. Note the
    positional order: DeviceService takes (vas_client, db).
    """
    return DeviceService(None, db)


@pytest.fixture
def backup_dir(tmp_path):
    """A writable backup directory, so preflight does not block on it."""
    target = tmp_path / "backups"
    target.mkdir()
    return target


class Seeder:
    """Builds a small but structurally complete slice of detection data.

    Shapes that matter to the archiver and are easy to miss:
    - a violation with NULL stream_session_id (the FK is nullable)
    - an event linked to a violation AND an event linked to neither
    - evidence with a VAS snapshot id and evidence with none
    - a session carrying non-zero counters
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self.device: Device | None = None
        self.session: StreamSession | None = None
        self.violations: list[Violation] = []
        self.events: list[Event] = []
        self.evidence: list[Evidence] = []

    async def seed(self, *, violations: int = 3, live: bool = False) -> "Seeder":
        now = datetime.now(timezone.utc)

        self.device = Device(
            vas_device_id=f"vas-{uuid.uuid4()}",
            name="CAM-TEST-01",
            is_active=True,
            enabled=True,
        )
        self._db.add(self.device)
        await self._db.flush()

        self.session = StreamSession(
            device_id=self.device.id,
            model_id="fall_detection",
            inference_fps=10,
            confidence_threshold=0.7,
            state=StreamState.LIVE if live else StreamState.STOPPED,
            started_at=now - timedelta(hours=2),
            stopped_at=None if live else now - timedelta(hours=1),
            frames_processed=1234,
            events_count=10,
            violations_count=violations,
        )
        self._db.add(self.session)
        await self._db.flush()

        for index in range(violations):
            violation = Violation(
                device_id=self.device.id,
                # Last one deliberately unlinked from any session.
                stream_session_id=None if index == violations - 1 else self.session.id,
                type=ViolationType.FALL_DETECTED,
                status=ViolationStatus.OPEN,
                confidence=0.9,
                timestamp=now - timedelta(minutes=index),
                camera_name=self.device.name,
                model_id="fall_detection",
                model_version="1.0.0",
                bounding_boxes=[{"x": 1, "y": 2, "width": 3, "height": 4}],
            )
            self._db.add(violation)
            self.violations.append(violation)
        await self._db.flush()

        for index, violation in enumerate(self.violations):
            event = Event(
                device_id=self.device.id,
                stream_session_id=self.session.id,
                violation_id=violation.id,
                event_type=EventType.FALL_DETECTED,
                confidence=0.9,
                timestamp=violation.timestamp,
                model_id="fall_detection",
                model_version="1.0.0",
            )
            self._db.add(event)
            self.events.append(event)

            evidence = Evidence(
                violation_id=violation.id,
                evidence_type=EvidenceType.SNAPSHOT,
                status=EvidenceStatus.READY,
                # One evidence row with no VAS id at all.
                vas_snapshot_id=None if index == 0 else f"snap-{index}",
                requested_at=violation.timestamp,
                retry_count=0,
            )
            self._db.add(evidence)
            self.evidence.append(evidence)

        # An event with no violation: the archive must keep it, and the
        # delete ordering must not depend on every event having a parent.
        orphan = Event(
            device_id=self.device.id,
            stream_session_id=self.session.id,
            violation_id=None,
            event_type=EventType.NO_FALL,
            confidence=0.1,
            timestamp=now,
            model_id="fall_detection",
            model_version="1.0.0",
        )
        self._db.add(orphan)
        self.events.append(orphan)

        await self._db.commit()
        return self


@pytest.fixture
def seeder(db) -> Seeder:
    return Seeder(db)

"""Background tasks and project scope, against a real Postgres.

Background tasks open sessions from the session factory, not through the
request's get_db, so they are never scoped: they see every project. That is
right for each of them (see the scope table in app/core/project_scope.py),
and these tests pin the ones where "every project" is the point:

* the export / report sweepers must expire past projects' files too;
* clip-status sync must finish clips requested in a past project;
* event aggregation must never fold a new detection into a past project's
  still-open violation, even in an unscoped session.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.project_scope import session_scope
from app.models import (
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_ENDED,
    CustomerReport,
    Device,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    Project,
    Violation,
    ViolationExport,
    ViolationStatus,
    ViolationType,
)
from app.models.violation_export import EXPORT_EXPIRED, EXPORT_READY

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)

NOW = datetime.now(timezone.utc)


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def world(factory):
    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'ended'"))
        hpcl = Project(name="HPCL", slug="hpcl", state=PROJECT_STATE_ENDED, started_by="t",
                       started_at=NOW - timedelta(days=30), ended_at=NOW - timedelta(days=2))
        dev = Project(name="Dev", slug="dev", state=PROJECT_STATE_ACTIVE, started_by="t",
                      started_at=NOW - timedelta(days=1))
        db.add_all([hpcl, dev])
        await db.flush()
        device = Device(vas_device_id=f"vas-{uuid.uuid4()}", name="CAM", is_active=True, enabled=True)
        db.add(device)
        await db.flush()
        await db.commit()
        return {"hpcl": hpcl, "dev": dev, "device": device}


async def test_background_sessions_are_unscoped(factory) -> None:
    async with factory() as db:
        assert session_scope(db) is None


async def test_sweepers_expire_past_projects_too(factory, world, tmp_path) -> None:
    from app.services.report.job import sweep_customer_reports
    from app.services.violation_export_job import sweep_expired

    zip_file, pdf_file = tmp_path / "old.zip", tmp_path / "old.pdf"
    zip_file.write_bytes(b"z")
    pdf_file.write_bytes(b"p")
    async with factory() as db:
        export = ViolationExport(project_id=world["hpcl"].id, status=EXPORT_READY, request={},
                                 file_path=str(zip_file), expires_at=NOW - timedelta(hours=1),
                                 created_at=NOW - timedelta(days=2), updated_at=NOW - timedelta(days=2))
        report = CustomerReport(project_id=world["hpcl"].id, status=EXPORT_READY, preset="custom",
                                mode="all", period_start=NOW - timedelta(days=9), period_end=NOW - timedelta(days=8),
                                period_label="x", options={}, file_path=str(pdf_file),
                                expires_at=NOW - timedelta(hours=1),
                                created_at=NOW - timedelta(days=2), updated_at=NOW - timedelta(days=2))
        db.add_all([export, report])
        await db.commit()

    await sweep_customer_reports(factory)
    await sweep_expired(factory)

    async with factory() as db:
        assert (await db.get(ViolationExport, export.id)).status == EXPORT_EXPIRED
        assert (await db.get(CustomerReport, report.id)).status == EXPORT_EXPIRED
    assert not zip_file.exists() and not pdf_file.exists()


async def test_clip_sync_finds_clips_of_past_projects(factory, world) -> None:
    from app.services.clip_status_sync import pending_clips_query

    async with factory() as db:
        v = Violation(project_id=world["hpcl"].id, device_id=world["device"].id,
                      type=ViolationType.PPE_VIOLATION, status=ViolationStatus.OPEN, confidence=0.9,
                      timestamp=NOW - timedelta(days=3), camera_name="CAM", model_id="ppe", model_version="1")
        db.add(v)
        await db.flush()
        clip = Evidence(project_id=world["hpcl"].id, violation_id=v.id, evidence_type=EvidenceType.BOOKMARK,
                        status=EvidenceStatus.PROCESSING, vas_bookmark_id="bm-1",
                        requested_at=NOW - timedelta(minutes=5), retry_count=0)
        db.add(clip)
        await db.commit()
        found = (await db.execute(pending_clips_query(50, timedelta(hours=24), NOW))).scalars().all()
    assert [e.id for e in found] == [clip.id]


async def test_aggregation_never_reaches_a_past_project(factory, world) -> None:
    from app.services.violation_service import ViolationService

    async with factory() as db:
        old = Violation(project_id=world["hpcl"].id, device_id=world["device"].id,
                        type=ViolationType.PPE_VIOLATION, status=ViolationStatus.OPEN, confidence=0.9,
                        timestamp=NOW - timedelta(days=3), camera_name="CAM", model_id="ppe", model_version="1")
        db.add(old)
        await db.commit()
        service = ViolationService(db)
        assert session_scope(db) is None  # unscoped, like a background task
        found = await service.get_open_violation(
            device_id=world["device"].id, stream_session_id=None, violation_type=ViolationType.PPE_VIOLATION
        )
        assert found is None

        new = Violation(device_id=world["device"].id, type=ViolationType.PPE_VIOLATION,
                        status=ViolationStatus.OPEN, confidence=0.9, timestamp=NOW,
                        camera_name="CAM", model_id="ppe", model_version="1")
        db.add(new)
        await db.commit()
        found = await service.get_open_violation(
            device_id=world["device"].id, stream_session_id=None, violation_type=ViolationType.PPE_VIOLATION
        )
        assert found is not None and found.id == new.id and found.project_id == world["dev"].id

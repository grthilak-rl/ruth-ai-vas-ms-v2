"""The archive, against a real Postgres.

What these protect, in rough order of how expensive the bug would be:

1. `events.violation_id` survives. The FK is ON DELETE SET NULL, so deleting
   violations before copying events would silently blank every event's link
   to its violation — the archive would still *look* complete.
2. Evidence is not cascaded away. `evidence.violation_id` is ON DELETE
   CASCADE; getting the order wrong loses the rows entirely.
3. The live tables really are empty afterwards, because that is the whole
   point: every dashboard number is a live aggregate.
4. Nothing is destroyed — the archive round-trips.
5. The refusals actually refuse.
"""

import pytest
from sqlalchemy import func, select, text

from app.core.config import Settings
from app.models import (
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_ARCHIVED,
    Device,
    Event,
    EventArchive,
    Evidence,
    EvidenceArchive,
    Project,
    StreamSession,
    Violation,
    ViolationArchive,
)
from app.services.project_service import (
    InferenceActiveError,
    ProjectError,
    ProjectNameInUseError,
    ProjectService,
)

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)


def _service(db, backup_dir) -> ProjectService:
    return ProjectService(
        db,
        settings=Settings(project_backup_dir=str(backup_dir), project_pg_dump_path="sh"),
    )


async def _count(db, model) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar() or 0)


# -----------------------------------------------------------------------------
# Happy path
# -----------------------------------------------------------------------------


async def test_archive_empties_live_tables(db, seeder, backup_dir) -> None:
    await seeder.seed(violations=3)
    service = _service(db, backup_dir)

    result = await service.start_new_project(
        name="Campaign Two",
        confirm_name="Campaign Two",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()

    assert await _count(db, Violation) == 0
    assert await _count(db, Event) == 0
    assert await _count(db, Evidence) == 0
    assert await _count(db, StreamSession) == 0
    assert result.counts["violations"] == 3


async def test_the_open_alerts_query_returns_zero(db, seeder, backup_dir) -> None:
    """The actual dashboard query, not a proxy for it.

    `SELECT count(*) FROM violations WHERE status='open'` with no time bound
    is what the Open Alerts card runs (app/api/v1/violations.py).
    """
    await seeder.seed(violations=5)
    before = (
        await db.execute(text("SELECT count(*) FROM violations WHERE status = 'open'"))
    ).scalar()
    assert before == 5

    await _service(db, backup_dir).start_new_project(
        name="Fresh", confirm_name="Fresh", started_by="tester", backup_path=None
    )
    await db.commit()

    after = (
        await db.execute(text("SELECT count(*) FROM violations WHERE status = 'open'"))
    ).scalar()
    assert after == 0


async def test_devices_are_not_archived(db, seeder, backup_dir) -> None:
    """Cameras stay. An archived violation must still resolve its device."""
    await seeder.seed(violations=2)
    device_id = seeder.device.id

    await _service(db, backup_dir).start_new_project(
        name="Keeps Cameras",
        confirm_name="Keeps Cameras",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()

    assert await _count(db, Device) == 1
    archived = (
        await db.execute(
            select(ViolationArchive.device_id).where(
                ViolationArchive.device_id == device_id
            )
        )
    ).scalars().all()
    assert len(archived) == 2


# -----------------------------------------------------------------------------
# The FK-ordering hazards
# -----------------------------------------------------------------------------


async def test_event_violation_links_survive_archiving(db, seeder, backup_dir) -> None:
    """The bug this whole ordering exists to prevent.

    events.violation_id is ON DELETE SET NULL. Delete violations before the
    events are copied and every archived event has violation_id = NULL, with
    no error anywhere.
    """
    await seeder.seed(violations=4)
    expected_linked = sum(1 for e in seeder.events if e.violation_id is not None)
    assert expected_linked == 4

    await _service(db, backup_dir).start_new_project(
        name="Links Intact",
        confirm_name="Links Intact",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()

    linked = (
        await db.execute(
            select(func.count())
            .select_from(EventArchive)
            .where(EventArchive.violation_id.is_not(None))
        )
    ).scalar()
    assert linked == expected_linked

    # And the unlinked one is still there, still unlinked.
    unlinked = (
        await db.execute(
            select(func.count())
            .select_from(EventArchive)
            .where(EventArchive.violation_id.is_(None))
        )
    ).scalar()
    assert unlinked == 1


async def test_evidence_is_not_cascaded_away(db, seeder, backup_dir) -> None:
    """evidence.violation_id is ON DELETE CASCADE.

    Deleting violations before copying evidence loses the evidence rows and
    the per-violation count would silently come out at zero.
    """
    await seeder.seed(violations=3)

    await _service(db, backup_dir).start_new_project(
        name="Evidence Kept",
        confirm_name="Evidence Kept",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()

    assert await _count(db, EvidenceArchive) == 3
    assert await _count(db, Evidence) == 0


async def test_session_counters_leave_with_their_rows(db, seeder, backup_dir) -> None:
    """The only stored counters in the product. They are moved, not zeroed."""
    await seeder.seed(violations=2)

    await _service(db, backup_dir).start_new_project(
        name="Counters", confirm_name="Counters", started_by="tester", backup_path=None
    )
    await db.commit()

    frames = (
        await db.execute(text("SELECT sum(frames_processed) FROM stream_sessions_archive"))
    ).scalar()
    assert frames == 1234


# -----------------------------------------------------------------------------
# Enum handling
# -----------------------------------------------------------------------------


async def test_enums_are_archived_as_text(db, seeder, backup_dir) -> None:
    """So removing an enum value later cannot invalidate the archive."""
    await seeder.seed(violations=1)

    await _service(db, backup_dir).start_new_project(
        name="Text Enums",
        confirm_name="Text Enums",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()

    column_type = (
        await db.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'violations_archive' AND column_name = 'status'"
            )
        )
    ).scalar()
    assert column_type == "character varying"

    value = (await db.execute(text("SELECT status FROM violations_archive"))).scalar()
    assert value == "open"


# -----------------------------------------------------------------------------
# Project bookkeeping
# -----------------------------------------------------------------------------


async def test_first_run_synthesises_a_baseline_project(db, seeder, backup_dir) -> None:
    """Data predating the feature still gets attributed to something."""
    await seeder.seed(violations=2)
    assert await _count(db, Project) == 0

    result = await _service(db, backup_dir).start_new_project(
        name="Second", confirm_name="Second", started_by="tester", backup_path=None
    )
    await db.commit()

    assert result.archived_project.name == "Initial data (before projects)"
    assert result.archived_project.state == PROJECT_STATE_ARCHIVED
    assert result.new_project.state == PROJECT_STATE_ACTIVE
    # started_at describes the data, not the moment the button was pressed.
    assert result.archived_project.started_at <= seeder.violations[0].timestamp


async def test_only_one_active_project(db, seeder, backup_dir) -> None:
    await seeder.seed(violations=1)
    service = _service(db, backup_dir)

    await service.start_new_project(
        name="One", confirm_name="One", started_by="tester", backup_path=None
    )
    await db.commit()
    await service.start_new_project(
        name="Two", confirm_name="Two", started_by="tester", backup_path=None
    )
    await db.commit()

    active = (
        await db.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.state == PROJECT_STATE_ACTIVE)
        )
    ).scalar()
    assert active == 1


async def test_archived_counts_are_recorded_on_the_project(db, seeder, backup_dir) -> None:
    """The project row is the audit record; the counts must be in it."""
    await seeder.seed(violations=3)

    result = await _service(db, backup_dir).start_new_project(
        name="Audited", confirm_name="Audited", started_by="alice", backup_path=None
    )
    await db.commit()

    assert result.archived_project.archived_counts["violations"] == 3
    assert result.archived_project.ended_by == "alice"
    assert result.new_project.started_by == "alice"


async def test_duplicate_slug_is_refused(db, seeder, backup_dir) -> None:
    await seeder.seed(violations=1)
    service = _service(db, backup_dir)

    await service.start_new_project(
        name="Q4 2026", confirm_name="Q4 2026", started_by="tester", backup_path=None
    )
    await db.commit()

    with pytest.raises(ProjectNameInUseError):
        await service.start_new_project(
            name="Q4-2026",
            confirm_name="Q4-2026",
            started_by="tester",
            backup_path=None,
        )
    await db.rollback()


# -----------------------------------------------------------------------------
# Refusals
# -----------------------------------------------------------------------------


async def test_live_inference_blocks_preflight(db, seeder, backup_dir) -> None:
    await seeder.seed(violations=1, live=True)

    pre = await _service(db, backup_dir).preflight()
    assert "inference_active" in pre.blockers
    assert pre.can_proceed is False
    assert [c.camera_name for c in pre.live_cameras] == ["CAM-TEST-01"]


async def test_live_inference_refused_even_under_the_lock(db, seeder, backup_dir) -> None:
    """Preflight runs before the operator types a confirmation.

    A camera started in between must still stop the archive, which is why
    the check is repeated inside start_new_project.
    """
    await seeder.seed(violations=1, live=True)

    with pytest.raises(InferenceActiveError) as excinfo:
        await _service(db, backup_dir).start_new_project(
            name="Races",
            confirm_name="Races",
            started_by="tester",
            backup_path=None,
        )
    await db.rollback()
    assert excinfo.value.details["cameras"][0]["camera_name"] == "CAM-TEST-01"

    # And nothing moved.
    assert await _count(db, Violation) == 1
    assert await _count(db, ViolationArchive) == 0


async def test_preflight_allows_live_when_stopping_is_requested(
    db, seeder, backup_dir
) -> None:
    await seeder.seed(violations=1, live=True)
    pre = await _service(db, backup_dir).preflight(allow_stop_inference=True)
    assert "inference_active" not in pre.blockers


async def test_empty_database_still_opens_a_project(db, backup_dir) -> None:
    """Nothing to archive is not an error; the project still starts."""
    service = _service(db, backup_dir)
    result = await service.start_new_project(
        name="Greenfield",
        confirm_name="Greenfield",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()

    assert result.archive_batch_id is None
    assert result.new_project.state == PROJECT_STATE_ACTIVE
    assert sum(result.counts.values()) == 0


# -----------------------------------------------------------------------------
# Restore
# -----------------------------------------------------------------------------


async def test_archive_restore_round_trip_is_lossless(db, seeder, backup_dir) -> None:
    await seeder.seed(violations=4)
    service = _service(db, backup_dir)

    before_violations = await _count(db, Violation)
    before_events = await _count(db, Event)
    before_evidence = await _count(db, Evidence)
    before_linked = (
        await db.execute(
            select(func.count()).select_from(Event).where(Event.violation_id.is_not(None))
        )
    ).scalar()

    result = await service.start_new_project(
        name="Round Trip",
        confirm_name="Round Trip",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()
    batch = result.archive_batch_id

    restored = await service.restore_batch(batch)
    await db.commit()

    assert restored["violations"] == before_violations
    assert await _count(db, Violation) == before_violations
    assert await _count(db, Event) == before_events
    assert await _count(db, Evidence) == before_evidence

    after_linked = (
        await db.execute(
            select(func.count()).select_from(Event).where(Event.violation_id.is_not(None))
        )
    ).scalar()
    assert after_linked == before_linked

    # Enums came back as enums, and the FKs resolve.
    joined = (
        await db.execute(
            text(
                "SELECT count(*) FROM evidence e JOIN violations v ON v.id = e.violation_id"
            )
        )
    ).scalar()
    assert joined == before_evidence


async def test_restore_refuses_into_non_empty_tables(db, seeder, backup_dir) -> None:
    """Merging an archived project into a running one cannot be undone."""
    await seeder.seed(violations=2)
    service = _service(db, backup_dir)

    result = await service.start_new_project(
        name="First", confirm_name="First", started_by="tester", backup_path=None
    )
    await db.commit()
    batch = result.archive_batch_id

    await service.restore_batch(batch)
    await db.commit()

    with pytest.raises(ProjectError, match="non-empty live tables"):
        await service.restore_batch(batch)
    await db.rollback()


# -----------------------------------------------------------------------------
# Verification gate
# -----------------------------------------------------------------------------


async def test_verification_failure_deletes_nothing(db, seeder, backup_dir, monkeypatch) -> None:
    """If the copy does not verify, the live data must survive untouched.

    Simulated by making the verification itself fail — what matters is that
    the delete never runs, and the caller's rollback restores everything.
    """
    await seeder.seed(violations=3)
    service = _service(db, backup_dir)

    async def boom(_batch_id):
        raise ProjectError("simulated verification failure")

    monkeypatch.setattr(service, "_verify_copy", boom)

    with pytest.raises(ProjectError, match="simulated"):
        await service.start_new_project(
            name="Fails",
            confirm_name="Fails",
            started_by="tester",
            backup_path=None,
        )
    await db.rollback()

    assert await _count(db, Violation) == 3
    assert await _count(db, Event) == 4
    assert await _count(db, Evidence) == 3
    assert await _count(db, ViolationArchive) == 0
    assert await _count(db, Project) == 0

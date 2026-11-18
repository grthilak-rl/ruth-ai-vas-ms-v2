"""Project scoping against a real Postgres.

The scope is one ``do_orm_execute`` hook rather than ~90 hand-written
filters, so what needs proving is that the hook reaches every query shape
the code base actually uses: plain selects, ``count()`` over
``select_from``, column/aggregate selects, counts over subqueries, joins
through another tagged table, ORM UPDATE, and ``session.get``. Plus the
database default that tags new rows, and the escape hatches.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import selectinload

from app.core.project_scope import (
    ALL_PROJECTS,
    scope_session,
    site_project,
)
from app.models import (
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_ENDED,
    Device,
    Event,
    EventType,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    Project,
    Violation,
    ViolationStatus,
    ViolationType,
)

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)

NOW = datetime.now(timezone.utc)


async def _project(db, name, state, days_ago) -> Project:
    p = Project(
        name=name,
        slug=name.lower().replace(" ", "-"),
        state=state,
        started_at=NOW - timedelta(days=days_ago),
        started_by="tester",
        ended_at=NOW - timedelta(days=days_ago - 1) if state == PROJECT_STATE_ENDED else None,
    )
    db.add(p)
    await db.flush()
    return p


async def _device(db) -> Device:
    d = Device(vas_device_id=f"vas-{uuid.uuid4()}", name="CAM-1", is_active=True, enabled=True)
    db.add(d)
    await db.flush()
    return d


def _violation(device, project_id=None, status=ViolationStatus.OPEN) -> Violation:
    v = Violation(
        device_id=device.id,
        type=ViolationType.PPE_VIOLATION,
        status=status,
        confidence=0.9,
        timestamp=NOW,
        camera_name=device.name,
        model_id="ppe",
        model_version="1",
    )
    if project_id is not None:
        v.project_id = project_id
    return v


@pytest.fixture
async def world(db):
    """HPCL (ended, 2 violations) and Dev (current, 3 violations)."""
    await db.execute(text("UPDATE projects SET state = 'ended'"))  # the fixture's Initial project
    hpcl = await _project(db, "HPCL", PROJECT_STATE_ENDED, 30)
    dev = await _project(db, "Post HPCL Dev", PROJECT_STATE_ACTIVE, 2)
    device = await _device(db)
    old = [_violation(device, hpcl.id) for _ in range(2)]
    new = [_violation(device) for _ in range(3)]  # tagged by the DB default
    db.add_all(old + new)
    await db.flush()
    for v in old + new:
        db.add(Evidence(
            violation_id=v.id,
            project_id=v.project_id,
            evidence_type=EvidenceType.FRAME,
            status=EvidenceStatus.READY,
            requested_at=NOW,
            retry_count=0,
        ))
    db.add(Event(
        device_id=device.id, violation_id=old[0].id, project_id=hpcl.id,
        event_type=EventType.PPE_VIOLATION, confidence=0.9, timestamp=NOW,
        model_id="ppe", model_version="1",
    ))
    await db.commit()
    return {"hpcl": hpcl, "dev": dev, "old": old, "new": new, "device": device}


async def test_database_default_tags_with_the_current_project(db, world) -> None:
    assert {v.project_id for v in world["new"]} == {world["dev"].id}
    # eager_defaults: readable after flush without a lazy load.
    v = _violation(world["device"])
    db.add(v)
    await db.flush()
    assert v.project_id == world["dev"].id


async def test_default_falls_back_to_the_last_project_between_end_and_start(db, world) -> None:
    world["dev"].state = PROJECT_STATE_ENDED
    await db.commit()
    tagged = (await db.execute(text("SELECT ruth_current_project_id()"))).scalar()
    assert tagged == world["dev"].id
    assert (await site_project(db)).id == world["dev"].id


async def test_plain_select_and_counts_are_scoped(db, world) -> None:
    scope_session(db, world["hpcl"].id)
    rows = (await db.execute(select(Violation))).scalars().all()
    assert {v.id for v in rows} == {v.id for v in world["old"]}

    assert (await db.execute(select(func.count()).select_from(Violation))).scalar() == 2
    assert (await db.execute(select(func.count(Violation.id)))).scalar() == 2
    grouped = (await db.execute(select(Violation.type, func.count()).group_by(Violation.type))).all()
    assert sum(c for _, c in grouped) == 2
    sub = select(Violation).where(Violation.status == ViolationStatus.OPEN).subquery()
    assert (await db.execute(select(func.count()).select_from(sub))).scalar() == 2

    scope_session(db, world["dev"].id)
    assert (await db.execute(select(func.count()).select_from(Violation))).scalar() == 3


async def test_other_tagged_tables_and_joins_are_scoped(db, world) -> None:
    scope_session(db, world["dev"].id)
    assert (await db.execute(select(func.count()).select_from(Evidence))).scalar() == 3
    assert (await db.execute(select(func.count()).select_from(Event))).scalar() == 0
    joined = await db.execute(
        select(func.count()).select_from(Evidence).join(Violation, Violation.id == Evidence.violation_id)
    )
    assert joined.scalar() == 3


async def test_get_by_id_respects_the_scope(db, world) -> None:
    scope_session(db, world["dev"].id)
    db.expunge_all()
    assert await db.get(Violation, world["old"][0].id) is None
    assert await db.get(Violation, world["new"][0].id) is not None


async def test_orm_update_is_scoped(db, world) -> None:
    scope_session(db, world["hpcl"].id)
    await db.execute(update(Violation).values(status=ViolationStatus.DISMISSED))
    await db.commit()
    scope_session(db, None)
    rows = (await db.execute(select(Violation.project_id, Violation.status))).all()
    for project_id, status in rows:
        expected = ViolationStatus.DISMISSED if project_id == world["hpcl"].id else ViolationStatus.OPEN
        assert status == expected


async def test_all_projects_option_and_unscoped_session_see_everything(db, world) -> None:
    scope_session(db, world["hpcl"].id)
    every = await db.execute(
        select(func.count()).select_from(Violation), execution_options={ALL_PROJECTS: True}
    )
    assert every.scalar() == 5
    scope_session(db, None)
    assert (await db.execute(select(func.count()).select_from(Violation))).scalar() == 5


async def test_relationship_loads_are_not_filtered(db, world) -> None:
    """An unscoped by-id read eager-loads its evidence even in another scope."""
    scope_session(db, None)
    db.expunge_all()
    v = (
        await db.execute(
            select(Violation).where(Violation.id == world["old"][0].id).options(selectinload(Violation.evidence))
        )
    ).scalars().one()
    assert len(v.evidence) == 1

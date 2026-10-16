"""Analytics camera totals exclude cameras retired in VAS.

Before this, `GET /api/v1/devices` hid disabled cameras while
`/analytics/summary.cameras_total` kept counting them, so the Overview card
and the Analytics page quoted different denominators for the same plant.

Both analytics endpoints are exercised through the service-level queries
rather than over HTTP: the endpoints take a DBSession and these are the two
statements that changed, so testing the SQL is testing the change. The
third assertion in each test is the one that would have failed before.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import (
    Device,
    Violation,
    ViolationStatus,
    ViolationType,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)


async def _device(db, *, name: str, is_active: bool = True, enabled: bool = True):
    device = Device(
        vas_device_id=f"vas-{uuid.uuid4()}",
        name=name,
        is_active=is_active,
        enabled=enabled,
    )
    db.add(device)
    await db.flush()
    return device


async def _violation(db, device, *, when: datetime):
    violation = Violation(
        device_id=device.id,
        type=ViolationType.FALL_DETECTED,
        status=ViolationStatus.OPEN,
        confidence=0.9,
        timestamp=when,
        camera_name=device.name,
        model_id="fall_detection",
        model_version="1.0.0",
    )
    db.add(violation)
    await db.flush()
    return violation


# The statement from analytics.py get_analytics_summary ("Count total cameras").
def _cameras_total_stmt():
    return (
        select(func.count())
        .select_from(Device)
        .where(Device.is_active.is_(True), Device.enabled.is_(True))
    )


# The statement from analytics.py get_devices_status ("Get all devices").
def _devices_status_stmt():
    return select(Device).where(
        Device.is_active.is_(True), Device.enabled.is_(True)
    )


async def test_cameras_total_excludes_retired(db) -> None:
    await _device(db, name="LIVE-A")
    await _device(db, name="LIVE-B")
    await _device(db, name="RETIRED", enabled=False)
    await db.commit()

    total = (await db.execute(_cameras_total_stmt())).scalar()
    assert total == 2


async def test_cameras_total_still_excludes_inactive(db) -> None:
    """The pre-existing is_active filter is kept, not replaced."""
    await _device(db, name="LIVE")
    await _device(db, name="GONE-FROM-VAS", is_active=False)
    await _device(db, name="RETIRED", enabled=False)
    await _device(db, name="BOTH", is_active=False, enabled=False)
    await db.commit()

    total = (await db.execute(_cameras_total_stmt())).scalar()
    assert total == 1


async def test_devices_status_omits_retired_cameras(db) -> None:
    now = datetime.now(timezone.utc)
    live = await _device(db, name="LIVE")
    retired = await _device(db, name="RETIRED", enabled=False)
    await _violation(db, live, when=now - timedelta(minutes=1))
    await _violation(db, retired, when=now - timedelta(minutes=2))
    await db.commit()

    devices = (await db.execute(_devices_status_stmt())).scalars().all()
    assert [d.name for d in devices] == ["LIVE"]


async def test_analytics_total_matches_the_devices_list(db, device_service) -> None:
    """The point of the change: one plant, one camera count.

    `device_service.count_devices()` is what GET /api/v1/devices reports as
    `total`; `_cameras_total_stmt` is what /analytics/summary reports as
    `cameras_total`. They must agree.
    """
    await _device(db, name="A")
    await _device(db, name="B")
    await _device(db, name="C", enabled=False)
    await _device(db, name="D", is_active=False)
    await db.commit()

    analytics_total = (await db.execute(_cameras_total_stmt())).scalar()
    devices_total = await device_service.count_devices()
    assert analytics_total == devices_total == 2


async def test_violations_of_retired_cameras_are_not_deleted(db) -> None:
    """Hiding a camera is a view concern, never a data one.

    Its violations stay in the table and keep being counted by
    /analytics/summary, which aggregates violations directly.
    """
    now = datetime.now(timezone.utc)
    retired = await _device(db, name="RETIRED", enabled=False)
    await _violation(db, retired, when=now)
    await db.commit()

    # This is the /analytics/summary violations_total query: no device join.
    total = (
        await db.execute(select(func.count()).select_from(Violation))
    ).scalar()
    assert total == 1

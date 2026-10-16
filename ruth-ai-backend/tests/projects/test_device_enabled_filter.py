"""Hiding cameras an operator retired in VAS.

Uses the same Postgres fixture as the archive tests because the behaviour is
a DB filter and the `items`/`total` agreement is the thing most likely to
drift.
"""

import os
import uuid

import pytest

from app.models import Device
from app.services.device_service import DeviceService

pytestmark = pytest.mark.skipif(
    not os.environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)


async def _seed(db, *, enabled: bool, active: bool = True, name: str = "CAM") -> Device:
    device = Device(
        vas_device_id=f"vas-{uuid.uuid4()}",
        name=name,
        is_active=active,
        enabled=enabled,
    )
    db.add(device)
    await db.flush()
    return device


@pytest.fixture
def device_service(db) -> DeviceService:
    # list/count never touch VAS, so the client can be None. Note the
    # positional order: DeviceService takes (vas_client, db).
    return DeviceService(None, db)


async def test_disabled_cameras_hidden_by_default(db, device_service) -> None:
    await _seed(db, enabled=True, name="LIVE-CAM")
    await _seed(db, enabled=False, name="RETIRED-CAM")
    await db.commit()

    devices = await device_service.list_devices()
    assert [d.name for d in devices] == ["LIVE-CAM"]


async def test_include_disabled_returns_everything(db, device_service) -> None:
    await _seed(db, enabled=True, name="LIVE-CAM")
    await _seed(db, enabled=False, name="RETIRED-CAM")
    await db.commit()

    devices = await device_service.list_devices(include_disabled=True)
    assert sorted(d.name for d in devices) == ["LIVE-CAM", "RETIRED-CAM"]


async def test_count_matches_list_in_both_modes(db, device_service) -> None:
    """items and total come from two queries; they must agree.

    A total that counted retired cameras while the list omitted them would
    make the UI claim cameras it never showed.
    """
    await _seed(db, enabled=True, name="A")
    await _seed(db, enabled=True, name="B")
    await _seed(db, enabled=False, name="C")
    await db.commit()

    for include in (False, True):
        listed = await device_service.list_devices(include_disabled=include)
        total = await device_service.count_devices(include_disabled=include)
        assert total == len(listed), f"mismatch with include_disabled={include}"

    assert await device_service.count_devices() == 2
    assert await device_service.count_devices(include_disabled=True) == 3


async def test_enabled_and_active_are_independent(db, device_service) -> None:
    """A camera can be enabled-but-offline, or disabled-but-momentarily-live.

    is_active is VAS's transient liveness (reset on every VAS boot); enabled
    is durable policy. Filtering on one must not filter on the other.
    """
    await _seed(db, enabled=True, active=False, name="ENABLED-OFFLINE")
    await _seed(db, enabled=False, active=True, name="DISABLED-ONLINE")
    await db.commit()

    # Default: active only, enabled only -> neither qualifies.
    assert await device_service.list_devices() == []

    # Enabled but inactive shows up once active_only is relaxed.
    relaxed = await device_service.list_devices(active_only=False)
    assert [d.name for d in relaxed] == ["ENABLED-OFFLINE"]

    # Disabled but active shows up only with include_disabled.
    with_disabled = await device_service.list_devices(include_disabled=True)
    assert [d.name for d in with_disabled] == ["DISABLED-ONLINE"]

    both = await device_service.list_devices(active_only=False, include_disabled=True)
    assert sorted(d.name for d in both) == ["DISABLED-ONLINE", "ENABLED-OFFLINE"]


async def test_enabled_defaults_true_for_new_rows(db) -> None:
    """The column's server default. A synced camera is enabled unless VAS
    says otherwise, so a backfill never hides a working camera."""
    device = Device(vas_device_id=f"vas-{uuid.uuid4()}", name="DEFAULTED", is_active=True)
    db.add(device)
    await db.commit()
    await db.refresh(device)
    assert device.enabled is True

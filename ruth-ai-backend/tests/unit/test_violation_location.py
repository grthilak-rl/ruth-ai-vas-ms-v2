"""Violations keep the location where the camera WAS (camera reuse across
manways): stamping at write time, readers preferring stored values, reports,
and the backfill helpers."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services import violation_location as vl

T0 = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)


def _device(manway="MW03 PF COLUMN", in_out="OUT", name="75129"):
    return SimpleNamespace(
        id=uuid4(), vas_device_id=str(uuid4()), name=name, manway=manway,
        in_out=in_out, display_name=f"{manway}_{in_out}_{name}" if manway else name,
        location=None,
    )


def _violation(**kw):
    base = dict(
        area=None, in_out=None, camera_display_name=None,
        location_stamped_at=None, location_source=None, camera_name="75129",
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _clear_cache():
    vl.invalidate()
    yield
    vl.invalidate()


# --- readers ---------------------------------------------------------------


def test_stamped_violation_ignores_where_the_camera_is_now():
    moved = _device(manway="MW03 PF COLUMN")  # camera since moved to MW03
    v = _violation(area="MW01 PF COLUMN", in_out="OUT",
                   camera_display_name="MW01 PF COLUMN_OUT_75129",
                   location_stamped_at=T0)
    assert vl.camera_fields(moved, v) == {
        "camera_display_name": "MW01 PF COLUMN_OUT_75129",
        "camera_area": "MW01 PF COLUMN",
        "camera_in_out": "OUT",
    }
    assert vl.area_of(v, moved) == "MW01 PF COLUMN"


def test_stamped_unplaced_violation_has_no_area_not_the_current_one():
    v = _violation(location_stamped_at=T0, camera_display_name="75129")
    assert vl.area_of(v, _device()) is None
    assert vl.camera_fields(_device(), v)["camera_area"] is None


def test_unstamped_row_falls_back_to_live_device():
    d = _device()
    assert vl.camera_fields(d, _violation())["camera_area"] == "MW03 PF COLUMN"
    assert vl.camera_fields(d)["camera_area"] == "MW03 PF COLUMN"
    assert vl.area_of(_violation(), d) == "MW03 PF COLUMN"


def test_area_filter_compiles_with_both_branches():
    sql = str(vl.area_filter(" MW01 ").compile(compile_kwargs={"literal_binds": True}))
    assert "violations.area = 'MW01'" in sql
    assert "location_stamped_at IS NOT NULL" in sql and "location_stamped_at IS NULL" in sql


# --- stamping ----------------------------------------------------------------


def _vas_answer(location="MW01 PF COLUMN", in_out="OUT", name="75129",
                start=T0 - timedelta(days=1), end=None):
    return {
        "placement": {
            "location": location, "in_out": in_out,
            "valid_from": start.isoformat(),
            "valid_to": end.isoformat() if end else None,
        },
        "display_name": f"{location}_{in_out}_{name}",
    }


async def test_stamp_uses_vas_placement_at_that_time():
    client = SimpleNamespace(get_placement_at=AsyncMock(return_value=_vas_answer()))
    d, v = _device(manway="MW03 PF COLUMN"), _violation()
    with patch("app.deps.services.get_vas_client_optional", return_value=client):
        await vl.stamp_location(v, d, T0)
    assert (v.area, v.in_out, v.location_source) == ("MW01 PF COLUMN", "OUT", "vas")
    assert v.camera_display_name == "MW01 PF COLUMN_OUT_75129"
    assert v.location_stamped_at is not None
    kwargs = client.get_placement_at.call_args.kwargs
    assert kwargs["retries"] == 0 and kwargs["timeout"] == vl.VAS_TIMEOUT


async def test_cache_reused_inside_window_and_refetched_outside():
    end = T0 + timedelta(hours=1)
    client = SimpleNamespace(get_placement_at=AsyncMock(return_value=_vas_answer(end=end)))
    d = _device()
    with patch("app.deps.services.get_vas_client_optional", return_value=client):
        await vl.stamp_location(_violation(), d, T0)
        await vl.stamp_location(_violation(), d, T0 + timedelta(minutes=5))
        assert client.get_placement_at.await_count == 1
        await vl.stamp_location(_violation(), d, end + timedelta(minutes=1))
        assert client.get_placement_at.await_count == 2


async def test_vas_down_falls_back_to_mirror_and_never_raises():
    client = SimpleNamespace(get_placement_at=AsyncMock(side_effect=RuntimeError("down")))
    d, v = _device(), _violation()
    with patch("app.deps.services.get_vas_client_optional", return_value=client):
        await vl.stamp_location(v, d, T0)
    assert (v.area, v.location_source) == ("MW03 PF COLUMN", "mirror")


async def test_unplaced_answer_is_stamped_without_area():
    client = SimpleNamespace(get_placement_at=AsyncMock(
        return_value={"placement": None, "display_name": "75129"}))
    v = _violation()
    with patch("app.deps.services.get_vas_client_optional", return_value=client):
        await vl.stamp_location(v, _device(), T0)
    assert v.area is None and v.camera_display_name == "75129" and v.location_source == "vas"


# --- reports -----------------------------------------------------------------


def test_report_camera_for_row_uses_stored_location():
    from app.services.report.data import UNASSIGNED_AREA, Camera, camera_from_row

    current = Camera(name="MW03 PF COLUMN_OUT_75129", area="MW03 PF COLUMN")
    stamped = _violation(area="MW01 PF COLUMN", camera_display_name="MW01 PF COLUMN_OUT_75129",
                         location_stamped_at=T0)
    assert camera_from_row(stamped, current) == Camera(
        name="MW01 PF COLUMN_OUT_75129", area="MW01 PF COLUMN")
    unplaced = _violation(location_stamped_at=T0)
    assert camera_from_row(unplaced, current).area == UNASSIGNED_AREA
    assert camera_from_row(_violation(), current) == current


# --- backfill helpers ----------------------------------------------------------


def test_windows_and_verification_from_vas_history():
    hist = [
        {"location": "MW03", "in_out": "OUT", "valid_from": (T0 + timedelta(days=5)).isoformat(),
         "valid_to": None, "source": "move", "verified": True, "display_name": "MW03_OUT_x"},
        {"location": "MW01", "in_out": "IN", "valid_from": T0.isoformat(),
         "valid_to": (T0 + timedelta(days=5)).isoformat(), "source": "seed", "verified": False,
         "display_name": "MW01_IN_x"},
    ]
    w = vl.windows_from_placements(hist)
    assert [s.area for _, _, s in w] == ["MW01", "MW03"]
    assert w[0][1] == T0 + timedelta(days=5) and w[1][1] is None
    assert vl.unverified(hist)
    assert not vl.unverified(hist[:1])

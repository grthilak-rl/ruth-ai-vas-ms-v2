"""video_live and camera-health fields come from VAS's measured health.

Camera 74004 was unreachable for an hour while VAS's stream row still said
"live", so Ruth reported live video (and blamed the AI: NOT MONITORED). VAS
now reports video_state from decoded frames; Ruth must prefer it.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.integrations.vas import VASError
from app.integrations.vas.models import Device as VASDevice
from app.services.stream_service import HEALTH_FIELDS, StreamService

LAST_SEG = datetime(2026, 10, 19, 10, 21, 56, tzinfo=timezone.utc)


def _vas_device(vid, **health):
    return VASDevice(id=vid, name=vid, **health)


def _stream(camera_id, state="live"):
    return SimpleNamespace(id=uuid.uuid4(), camera_id=camera_id, state=SimpleNamespace(value=state))


class _Rows:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DB:
    """No active sessions and no past ones."""

    async def execute(self, stmt):
        return _Rows()


def _service(vas_devices, streams, *, devices_error=None):
    vas = SimpleNamespace(
        get_streams=AsyncMock(return_value=SimpleNamespace(streams=streams)),
        get_devices=AsyncMock(side_effect=devices_error, return_value=vas_devices),
    )
    return StreamService(vas, _DB())


def _ruth_device(vas_id):
    return SimpleNamespace(id=uuid.uuid4(), vas_device_id=vas_id)


async def test_offline_camera_is_not_video_live_despite_live_stream_state():
    dead, ok = _ruth_device("74004"), _ruth_device("75080")
    svc = _service(
        [
            _vas_device("74004", video_state="offline", recording_state="stopped",
                        last_segment_at=LAST_SEG, segments_today=6213),
            _vas_device("75080", video_state="live", recording_state="recording", segments_today=6997),
        ],
        [_stream("74004"), _stream("75080")],
    )
    out = await svc.get_combined_status_bulk([dead, ok])

    assert out[dead.id]["video_live"] is False
    assert out[dead.id]["video_state"] == "offline"
    assert out[dead.id]["recording_state"] == "stopped"
    assert out[dead.id]["last_segment_at"] == LAST_SEG
    assert out[dead.id]["segments_today"] == 6213
    assert out[ok.id]["video_live"] is True
    assert set(HEALTH_FIELDS) <= set(out[ok.id])


async def test_falls_back_to_stream_state_without_health():
    cam = _ruth_device("75080")
    svc = _service([_vas_device("75080")], [_stream("75080")])  # older VAS: no fields
    out = await svc.get_combined_status_bulk([cam])
    assert out[cam.id]["video_live"] is True
    assert out[cam.id]["video_state"] is None


async def test_device_fetch_failure_keeps_stream_state_path():
    cam = _ruth_device("75080")
    svc = _service([], [_stream("75080")], devices_error=VASError("down"))
    out = await svc.get_combined_status_bulk([cam])
    assert out[cam.id]["video_live"] is True

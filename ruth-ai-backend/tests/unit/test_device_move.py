"""Ruth's manway edit is a Move camera in VAS (not a local edit)."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import devices as devices_api
from app.integrations.vas import VASError
from app.schemas.device import DeviceNamingUpdateRequest


def _deps(manway="MW01 PF COLUMN", in_out="OUT"):
    ruth_device = SimpleNamespace(id=uuid4(), vas_device_id="vas-1")
    service = SimpleNamespace(
        get_device_by_id=AsyncMock(return_value=ruth_device),
        apply_naming_from_vas=AsyncMock(),
    )
    vas = SimpleNamespace(
        get_device=AsyncMock(return_value=SimpleNamespace(name="75129", manway=manway, in_out=in_out)),
        move_device=AsyncMock(return_value={
            "device_id": "vas-1", "display_name": "MW03 PF COLUMN_OUT_75129",
            "manway": "MW03 PF COLUMN", "in_out": "OUT", "placement": {},
        }),
        update_device=AsyncMock(),
    )
    return ruth_device, service, vas


async def test_manway_change_calls_vas_move_keeping_side():
    dev, service, vas = _deps()
    when = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)
    req = DeviceNamingUpdateRequest(manway="MW03 PF COLUMN", effective_at=when, note="reinstalled")
    with patch.object(devices_api, "cache_delete", AsyncMock()), \
         patch("app.services.violation_location.invalidate") as inval:
        resp = await devices_api.update_device_naming(dev.id, req, service, vas)

    vas.move_device.assert_awaited_once_with(
        "vas-1", "MW03 PF COLUMN", "OUT", effective_at=when, note="reinstalled"
    )
    vas.update_device.assert_not_awaited()
    service.apply_naming_from_vas.assert_awaited_once()
    inval.assert_called_once_with("vas-1")
    assert resp.display_name == "MW03 PF COLUMN_OUT_75129" and resp.manway == "MW03 PF COLUMN"


async def test_vas_refusal_leaves_ruth_mirror_untouched():
    dev, service, vas = _deps()
    vas.move_device.side_effect = VASError("effective_at must be after...", status_code=422)
    with patch.object(devices_api, "cache_delete", AsyncMock()):
        with pytest.raises(HTTPException) as e:
            await devices_api.update_device_naming(
                dev.id, DeviceNamingUpdateRequest(manway="MW03"), service, vas
            )
    assert e.value.status_code == 422
    service.apply_naming_from_vas.assert_not_awaited()


async def test_no_fields_is_rejected():
    dev, service, vas = _deps()
    with pytest.raises(HTTPException) as e:
        await devices_api.update_device_naming(
            dev.id, DeviceNamingUpdateRequest(note="x"), service, vas
        )
    assert e.value.status_code == 400

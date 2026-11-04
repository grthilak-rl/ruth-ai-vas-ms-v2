"""Settings -> System footage retention: a view of VAS, never a copy."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.footage_retention import (
    FootageRetentionUpdate,
    get_footage_retention,
    update_footage_retention,
)
from app.integrations.vas import VASError

VAS_CONFIG = {
    "footage_deletion": "off",
    "cleanup_enabled": False,
    "retention_paused": False,
    "hot_retention_days": 7,
    "hot_retention_days_set": False,
    "snapshot_retention_days": 365,
    "bookmark_retention_days": 365,
    "disk_alert_enabled": True,
    "disk_usage_percent": 11.2,
    "disk_free_bytes": 15 * 10**12,
    "disk_alert_level": "ok",
    "hot_storage_path": "/mnt/storage/hot",  # not exposed
}


class FakeVAS:
    def __init__(self, fail_with=None):
        self.config = dict(VAS_CONFIG)
        self.updates = []
        self.fail_with = fail_with

    async def get_storage_config(self):
        return self.config

    async def update_storage_config(self, updates):
        if self.fail_with:
            raise self.fail_with
        self.updates.append(updates)
        self.config.update(updates)
        self.config["footage_deletion"] = (
            "paused" if self.config["retention_paused"] else "on" if self.config["cleanup_enabled"] else "off"
        )
        return self.config


ADMIN = SimpleNamespace(username="admin")


async def test_read_shows_vas_state():
    view = await get_footage_retention(FakeVAS())
    assert view.footage_deletion == "off"
    assert view.cleanup_enabled is False and view.retention_paused is False
    assert view.disk_alert_level == "ok"
    assert "hot_storage_path" not in view.model_dump()


async def test_update_forwards_only_given_fields():
    vas = FakeVAS()
    view = await update_footage_retention(FootageRetentionUpdate(retention_paused=True), vas, ADMIN)
    assert vas.updates == [{"retention_paused": True}]
    assert view.footage_deletion == "paused"


async def test_empty_update_rejected():
    with pytest.raises(HTTPException) as e:
        await update_footage_retention(FootageRetentionUpdate(), FakeVAS(), ADMIN)
    assert e.value.status_code == 422


async def test_vas_refusal_is_reported_not_swallowed():
    vas = FakeVAS(fail_with=VASError("Set hot_retention_days explicitly", status_code=400))
    with pytest.raises(HTTPException) as e:
        await update_footage_retention(FootageRetentionUpdate(cleanup_enabled=True), vas, ADMIN)
    assert e.value.status_code == 422
    assert "hot_retention_days" in e.value.detail["message"]


async def test_vas_down_is_502():
    class Down(FakeVAS):
        async def get_storage_config(self):
            raise VASError("connection refused")

    with pytest.raises(HTTPException) as e:
        await get_footage_retention(Down())
    assert e.value.status_code == 502

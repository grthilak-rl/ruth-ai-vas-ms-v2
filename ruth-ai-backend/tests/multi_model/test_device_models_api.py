"""HTTP tests for /api/v1/devices/{id}/models and /detections (Postgres).

    MULTI_MODEL_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
"""

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.services.inference_loop as il
from app.deps.db import get_db
from app.deps.services import get_device_service, get_stream_service
from app.main import create_application
from app.models import Device, StreamSession
from app.services.device_service import DeviceService
from app.services.stream_service import StreamService
from tests.multi_model.fakes import FakeVAS

DATABASE_URL = os.environ.get("MULTI_MODEL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="MULTI_MODEL_TEST_DATABASE_URL not set")


BUILTINS = ["fall_detection", "ppe_detection", "geo_fencing"]


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    """These tests run a deployment with the built-ins on the unified runtime
    (in use), so their IDs are installed. ``installed(store, in_use, unified)``
    reconfigures it."""
    from types import SimpleNamespace

    from app.services import model_availability as ma

    def apply(store=(), in_use=True, unified=BUILTINS):
        monkeypatch.setattr(ma, "enabled_store_models", lambda: {m: object() for m in store})
        monkeypatch.setattr(ma, "get_unified_runtime_config", lambda: SimpleNamespace(unified_runtime_in_use=in_use))

        async def catalog():
            return [{"model_id": m} for m in unified]

        monkeypatch.setattr(ma, "_refresh_catalog", catalog)
        ma._cache.update(models=None, expires_at=0.0)

    apply()
    yield apply
    ma._cache.update(models=None, expires_at=0.0)


@pytest.fixture
async def sm():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE violations, stream_sessions, devices CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def client(sm) -> AsyncGenerator[AsyncClient, None]:
    app = create_application()

    async def db_override():
        async with sm() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def streams_override(db=Depends(get_db)):
        yield StreamService(FakeVAS(), db)

    async def devices_override(db=Depends(get_db)):
        yield DeviceService(FakeVAS(), db)

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_stream_service] = streams_override
    app.dependency_overrides[get_device_service] = devices_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def device_id(sm) -> uuid.UUID:
    async with sm() as db:
        device = Device(vas_device_id=str(uuid.uuid4()), name="cam", is_active=True)
        db.add(device)
        await db.commit()
        return device.id


async def test_add_list_patch_remove_lifecycle(client, sm, device_id):
    base = f"/api/v1/devices/{device_id}/models"
    assert (await client.get(base)).json()["models"] == []

    first = await client.post(base, json={"model_id": "fall_detection", "config": {"a": 1}})
    assert first.status_code == 201
    assert first.json()["session_id"] is not None
    again = await client.post(base, json={"model_id": "fall_detection"})
    assert again.status_code == 200  # already running: no-op
    assert (await client.post(base, json={"model_id": "ppe_detection"})).status_code == 201

    listed = (await client.get(base)).json()
    assert [m["model_id"] for m in listed["models"]] == ["fall_detection", "ppe_detection"]
    assert listed["models_revision"] == 2

    patched = await client.patch(f"{base}/ppe_detection", json={"fps_override": 1.5})
    assert patched.status_code == 200
    ppe = next(m for m in patched.json()["models"] if m["model_id"] == "ppe_detection")
    assert ppe["fps_override"] == 1.5 and ppe["target_fps"] == 1.5
    cleared = await client.patch(f"{base}/ppe_detection", json={"fps_override": None})
    assert next(m for m in cleared.json()["models"] if m["model_id"] == "ppe_detection")["fps_override"] is None

    # devices list carries every model
    devices = (await client.get("/api/v1/devices")).json()
    entry = next(d for d in devices["items"] if d["id"] == str(device_id))
    assert entry["streaming"]["models"] == ["fall_detection", "ppe_detection"]
    assert entry["streaming"]["model_id"] == "fall_detection"

    removed = await client.delete(f"{base}/fall_detection")
    assert [m["model_id"] for m in removed.json()["models"]] == ["ppe_detection"]
    async with sm() as db:
        row = (await db.execute(select(StreamSession).where(StreamSession.device_id == device_id))).scalar_one()
    assert row.model_id == "ppe_detection"  # legacy column mirrors models[0]

    last = await client.delete(f"{base}/ppe_detection")
    assert last.json()["session_id"] is None
    assert (await client.get(base)).json()["models"] == []


async def test_existing_start_inference_unchanged_and_convertible(client, device_id):
    started = await client.post(f"/api/v1/devices/{device_id}/start-inference", json={"model_id": "fall_detection"})
    assert started.status_code == 200
    listed = (await client.get(f"/api/v1/devices/{device_id}/models")).json()
    assert [m["model_id"] for m in listed["models"]] == ["fall_detection"]  # legacy session shown
    assert listed["models_revision"] == 0
    added = await client.post(f"/api/v1/devices/{device_id}/models", json={"model_id": "geo_fencing"})
    assert [m["model_id"] for m in added.json()["models"]] == ["fall_detection", "geo_fencing"]
    stopped = await client.post(f"/api/v1/devices/{device_id}/stop-inference")
    assert stopped.status_code == 200  # stops every model, as before


async def test_errors(client, device_id):
    base = f"/api/v1/devices/{device_id}/models"
    assert (await client.patch(f"{base}/nope", json={"config": {}})).status_code == 404
    assert (await client.delete(f"{base}/nope")).status_code == 404
    await client.post(base, json={"model_id": "fall_detection"})
    assert (await client.patch(f"{base}/fall_detection", json={})).status_code == 422
    assert (await client.post(base, json={"model_id": "x", "fps_override": 99})).status_code == 400
    missing = await client.post(f"/api/v1/devices/{uuid.uuid4()}/models", json={"model_id": "fall_detection"})
    assert missing.status_code == 404


async def test_detections_endpoint(client, device_id, monkeypatch):
    url = f"/api/v1/devices/{device_id}/detections"
    assert (await client.get(url)).json()["detections"] == []  # no loop running

    class Loop:
        def get_latest_detections(self, dev):
            return [{"model_id": "fall_detection", "model_version": "1.0.0", "result": {"k": 1},
                     "frame_width": 1, "frame_height": 2, "age_ms": 5, "device_id": str(dev)}]

    monkeypatch.setattr(il, "get_inference_loop", lambda: Loop())
    body = (await client.get(url)).json()
    assert [d["model_id"] for d in body["detections"]] == ["fall_detection"]


# ---------------------------------------------------------------------------
# Models that are not installed (built-ins retired: unified runtime not in use)
# ---------------------------------------------------------------------------


async def test_stale_tab_add_of_a_retired_model_is_refused_and_starts_nothing(client, sm, device_id, installed):
    installed(store=["geofence", "hard_hat"], in_use=False)
    zone = {"zones": [{"id": "zone_1", "type": "restricted", "points": [[830, 892], [1163, 916], [1247, 1057]]}]}
    r = await client.post(f"/api/v1/devices/{device_id}/models", json={"model_id": "geo_fencing", "config": zone})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "model_retired" and r.json()["detail"]["replacement"] == "geofence"
    async with sm() as db:
        assert (await db.execute(select(StreamSession).where(StreamSession.device_id == device_id))).first() is None
    started = await client.post(f"/api/v1/devices/{device_id}/start-inference", json={"model_id": "geo_fencing"})
    assert started.status_code == 422


async def test_saved_model_left_out_is_reported_and_removable(client, sm, device_id, installed, monkeypatch):
    """A camera resumed without its retired model: the API shows it as not
    started (unavailable), System Health's statuses include it, and Remove
    deletes it from the saved list only."""
    from app.models import DeviceInferenceIntent
    from app.services import camera_model_status as cms

    installed(store=["fall_detection"], in_use=False)  # an installed model to run
    base = f"/api/v1/devices/{device_id}/models"
    assert (await client.post(base, json={"model_id": "fall_detection"})).status_code == 201
    async with sm() as db:
        intent = (await db.execute(
            select(DeviceInferenceIntent).where(DeviceInferenceIntent.device_id == device_id))).scalar_one()
        intent.models = intent.models + [{"model_id": "ppe_detection", "model_version": None, "config": None}]
        await db.commit()

    listed = (await client.get(base)).json()
    assert [(m["model_id"], m["status"]) for m in listed["models"]] == [("fall_detection", "running")]
    assert [(m["model_id"], m["status"], m["reason"]) for m in listed["not_started"]] == [
        ("ppe_detection", "unavailable", "model_retired")]

    async with sm() as db:
        statuses = await cms.camera_model_statuses(db)
    assert [(s.model_id, s.status, s.in_session) for s in statuses if s.device_id == device_id] == [
        ("fall_detection", "running", True), ("ppe_detection", "unavailable", False)]

    # An operator edit keeps it saved; Remove deletes it, and only it.
    assert (await client.patch(f"{base}/fall_detection", json={"fps_override": 1.0})).status_code == 200
    async with sm() as db:
        intent = (await db.execute(
            select(DeviceInferenceIntent).where(DeviceInferenceIntent.device_id == device_id))).scalar_one()
        assert [e["model_id"] for e in intent.models] == ["fall_detection", "ppe_detection"]
    removed = await client.delete(f"{base}/ppe_detection")
    assert removed.status_code == 200 and removed.json()["not_started"] == []
    assert [m["model_id"] for m in removed.json()["models"]] == ["fall_detection"]
    async with sm() as db:
        intent = (await db.execute(
            select(DeviceInferenceIntent).where(DeviceInferenceIntent.device_id == device_id))).scalar_one()
        assert [e["model_id"] for e in intent.models] == ["fall_detection"]


async def test_failing_model_shows_in_the_api(client, device_id, installed, monkeypatch):
    from app.services import camera_model_status as cms

    clock = {"t": 1000.0}
    tracker = cms.CameraModelTracker(clock=lambda: clock["t"])
    monkeypatch.setattr(cms, "tracker", tracker)
    base = f"/api/v1/devices/{device_id}/models"
    await client.post(base, json={"model_id": "fall_detection"})
    tracker.record_failure(device_id, "fall_detection", "Model not found: fall_detection:latest")
    clock["t"] += 61
    m = (await client.get(base)).json()["models"][0]
    assert m["status"] == "failing" and m["reason"] == "inference_failing"
    assert "Model not found" in m["message"] and m["failing_since"]

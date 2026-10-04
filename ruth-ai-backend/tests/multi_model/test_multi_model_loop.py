"""Multi-model sessions: golden legacy behaviour and single <-> multi handovers.

Real InferenceLoopService + Postgres (migrated to head), fake runtime/VAS:

    MULTI_MODEL_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

Gaps are asserted from the third call on: the first ticks open DB pool
connections (first counter update ~100-170 ms, first violation write ~300 ms
here), which is the same for the legacy loop and not what these tests probe.

G0  a legacy session's trace equals the pre-M1 golden trace
G1  legacy -> multi mid-violation-streak: no gap, no double run, one violation
G2  multi(2) -> multi(1): streak continues, removed model stops, no duplicate
G3  removing the primary model: model_id and /detections/latest follow
G4  PATCH config / fps_override on a 1-model session takes effect
G5  concurrent adds (with and without an existing session) lose nothing
G6  a legacy camera next to a multi-model camera is never handed over
"""

import asyncio
import json
import os
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.services.inference_loop as il
from app.models import Device, StreamSession, StreamState, Violation
from app.services.session_models import SessionModelsService
from app.services.stream_service import StreamService
from tests.multi_model.fakes import (
    FakeRuntime,
    FakeVAS,
    result,
    session_factory_for,
    stop_loop,
    wait_for,
)
from tests.multi_model.legacy_scenario import run_legacy_scenario

DATABASE_URL = os.environ.get("MULTI_MODEL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="MULTI_MODEL_TEST_DATABASE_URL not set")

GOLDEN = Path(__file__).with_name("golden_legacy_trace.json")
FAST_FPS = 50.0  # default pace in these tests: 20 ms intervals


@pytest.fixture
async def sm():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE violations, stream_sessions, devices CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture(autouse=True)
def fast_budget(monkeypatch):
    monkeypatch.setattr(il, "TARGET_FPS", FAST_FPS)
    monkeypatch.setattr(il, "MAX_GPU_UTILIZATION", 100.0)


async def make_device(sm) -> uuid.UUID:
    async with sm() as db:
        device = Device(vas_device_id=str(uuid.uuid4()), name="cam", is_active=True)
        db.add(device)
        await db.commit()
        return device.id


async def make_legacy_session(sm, device_id, model_id="fall_detection", config=None) -> uuid.UUID:
    async with sm() as db:
        session = StreamSession(
            device_id=device_id,
            model_id=model_id,
            model_version="1.0.0",
            model_config=config,
            state=StreamState.LIVE,
            vas_stream_id=str(uuid.uuid4()),
            started_at=datetime.now(timezone.utc),
        )
        db.add(session)
        await db.commit()
        return session.id


async def edit(sm, action: str, device_id, *args, start_delay: float = 0.0):
    """Run one SessionModelsService call in its own transaction (like a request)."""
    async with sm() as db:
        service = SessionModelsService(StreamService(FakeVAS(start_delay), db), db)
        outcome = await getattr(service, action)(device_id, *args)
        await db.commit()
        return outcome


async def violations_for(sm, model_id: str) -> int:
    async with sm() as db:
        return (
            await db.execute(select(func.count()).select_from(Violation).where(Violation.model_id == model_id))
        ).scalar_one()


def make_loop(sm, runtime) -> il.InferenceLoopService:
    return il.InferenceLoopService(
        runtime_router=runtime,
        vas_client=FakeVAS(),
        db_session_factory=session_factory_for(sm),
        loop_interval=0.02,
    )


def max_gap(calls) -> float:
    times = [c["t"] for c in calls]
    return max((b - a for a, b in zip(times, times[1:], strict=False)), default=0.0)


# =============================================================================
# G0: legacy sessions behave exactly as before M1
# =============================================================================


async def test_g0_legacy_trace_matches_pre_m1_golden(sm):
    trace = await run_legacy_scenario(sm)
    expected = json.loads(GOLDEN.read_text())
    assert trace == expected


# =============================================================================
# G1: legacy -> multi while the legacy model is in a violation streak
# =============================================================================


async def test_g1_legacy_to_multi_no_gap_no_double_run_one_violation(sm):
    device_id = await make_device(sm)
    await make_legacy_session(sm, device_id, "fall_detection", {"v": 1})
    runtime = FakeRuntime(
        lambda m, n: result(True, label="fall_detected") if m == "fall_detection" else result(False)
    )
    loop = make_loop(sm, runtime)
    await loop.start()
    try:
        await wait_for(lambda: runtime.count["fall_detection"] >= 5)
        added_at = asyncio.get_event_loop().time()
        await edit(sm, "add", device_id, {"model_id": "ppe_detection", "config": {"p": 1}})
        await wait_for(lambda: len([c for c in runtime.calls_for("fall_detection") if c["kind"] == "multi"]) >= 5)
        await wait_for(lambda: runtime.count["ppe_detection"] >= 3)
    finally:
        await stop_loop(loop)

    fall = runtime.calls_for("fall_detection")
    kinds = [c["kind"] for c in fall]
    first_multi = kinds.index("multi")
    assert all(k == "legacy" for k in kinds[:first_multi])
    assert all(k == "multi" for k in kinds[first_multi:])  # never back, never interleaved
    assert runtime.max_in_flight["fall_detection"] == 1  # no double run
    # No gap beyond one interval + one tick, across the handover. The first
    # calls are excluded: they include cold DB connections (first counter
    # update and violation write), which the legacy loop pays identically.
    assert max_gap(fall[3:]) < 0.3
    assert runtime.calls_for("ppe_detection")[0]["t"] - added_at < 0.5
    assert fall[first_multi]["config"] == {"v": 1}  # legacy config carried into models[0]
    assert await violations_for(sm, "fall_detection") == 1  # one continuous streak
    # Shared frames: both models ran on the same frame read at least once.
    frames = {}
    for c in runtime.calls:
        if c["kind"] == "multi":
            frames.setdefault(c["frame"], set()).add(c["model_id"])
    assert any(models == {"fall_detection", "ppe_detection"} for models in frames.values())
    assert all(
        sum(1 for c in runtime.calls if c["frame"] == f and c["model_id"] == m) == 1
        for f, models in frames.items() for m in models
    )  # no model ran twice on one frame
    assert len(runtime.fetches) < len([c for c in runtime.calls if c["kind"] == "multi"])


# =============================================================================
# G2: multi(2) -> multi(1)
# =============================================================================


async def test_g2_remove_down_to_one_streak_continues(sm):
    device_id = await make_device(sm)
    await edit(sm, "add", device_id, {"model_id": "fall_detection"})
    await edit(sm, "add", device_id, {"model_id": "ppe_detection"})
    runtime = FakeRuntime(lambda m, n: result(True, label=m))
    loop = make_loop(sm, runtime)
    await loop.start()
    try:
        await wait_for(lambda: runtime.count["ppe_detection"] >= 3 and runtime.count["fall_detection"] >= 3)
        await edit(sm, "remove", device_id, "ppe_detection")
        removed_at = asyncio.get_event_loop().time()
        ppe_before = runtime.count["ppe_detection"]
        fall_before = runtime.count["fall_detection"]
        await wait_for(lambda: runtime.count["fall_detection"] >= fall_before + 6)
    finally:
        await stop_loop(loop)

    late_ppe = [c for c in runtime.calls_for("ppe_detection") if c["t"] > removed_at + 0.3]
    assert late_ppe == []
    assert runtime.count["ppe_detection"] <= ppe_before + 2  # at most in-flight ticks
    assert runtime.max_in_flight["fall_detection"] == 1
    assert runtime.max_in_flight["ppe_detection"] == 1
    fall = runtime.calls_for("fall_detection")
    around_handover = [c for c in fall if c["t"] >= removed_at - 0.1]
    assert max_gap(around_handover) < 0.3  # the handover itself leaves no gap
    assert max_gap(fall[3:]) < 0.3  # steady state (cold-start ticks excluded, see G1)
    assert await violations_for(sm, "fall_detection") == 1
    assert await violations_for(sm, "ppe_detection") == 1


# =============================================================================
# G3: removing the primary model
# =============================================================================


async def test_g3_remove_primary_model_id_and_latest_follow(sm):
    device_id = await make_device(sm)
    await edit(sm, "add", device_id, {"model_id": "fall_detection"})
    await edit(sm, "add", device_id, {"model_id": "geo_fencing"})
    runtime = FakeRuntime(lambda m, n: result(False))
    loop = make_loop(sm, runtime)
    await loop.start()
    try:
        await wait_for(lambda: (loop.get_latest_detection(device_id) or {}).get("model_id") == "fall_detection")
        session = await edit(sm, "remove", device_id, "fall_detection")
        assert session.model_id == "geo_fencing"
        await wait_for(lambda: (loop.get_latest_detection(device_id) or {}).get("model_id") == "geo_fencing")
        await wait_for(lambda: [d["model_id"] for d in loop.get_latest_detections(device_id)] == ["geo_fencing"])
    finally:
        await stop_loop(loop)
    async with sm() as db:
        row = (await db.execute(select(StreamSession).where(StreamSession.device_id == device_id))).scalar_one()
    assert row.model_id == "geo_fencing"
    assert [e["model_id"] for e in row.models] == ["geo_fencing"]


# =============================================================================
# G4: PATCH on a 1-model session takes effect (config and fps_override)
# =============================================================================


async def test_g4_patch_one_model_session_takes_effect(sm):
    device_id = await make_device(sm)
    await edit(sm, "add", device_id, {"model_id": "fall_detection", "config": {"v": 1}})
    runtime = FakeRuntime(lambda m, n: result(False))
    loop = make_loop(sm, runtime)
    await loop.start()
    try:
        await wait_for(lambda: runtime.count["fall_detection"] >= 3)
        await edit(sm, "update", device_id, "fall_detection", {"config": {"v": 2}})
        await wait_for(lambda: runtime.calls_for("fall_detection")[-1]["config"] == {"v": 2}, timeout=1.0)

        await edit(sm, "update", device_id, "fall_detection", {"fps_override": 5.0})
        switched = asyncio.get_event_loop().time() + 0.3
        await wait_for(lambda: len([c for c in runtime.calls_for("fall_detection") if c["t"] > switched]) >= 4)
    finally:
        await stop_loop(loop)

    slow = [c["t"] for c in runtime.calls_for("fall_detection") if c["t"] > switched]
    assert statistics.median(b - a for a, b in zip(slow, slow[1:], strict=False)) >= 0.17  # ~5 fps, not 50
    assert runtime.max_in_flight["fall_detection"] == 1


async def test_g4b_legacy_session_patched_via_models_api_takes_effect(sm):
    device_id = await make_device(sm)
    await make_legacy_session(sm, device_id, "fall_detection", {"v": 1})
    runtime = FakeRuntime(lambda m, n: result(False))
    loop = make_loop(sm, runtime)
    await loop.start()
    try:
        await wait_for(lambda: runtime.count["fall_detection"] >= 3)
        await edit(sm, "update", device_id, "fall_detection", {"config": {"v": 2}})
        await wait_for(lambda: runtime.calls_for("fall_detection")[-1]["config"] == {"v": 2}, timeout=1.0)
    finally:
        await stop_loop(loop)
    assert runtime.max_in_flight["fall_detection"] == 1


# =============================================================================
# G5: concurrent adds
# =============================================================================


async def test_g5_concurrent_adds_on_running_session(sm):
    device_id = await make_device(sm)
    await edit(sm, "add", device_id, {"model_id": "fall_detection"})
    await asyncio.gather(
        edit(sm, "add", device_id, {"model_id": "ppe_detection"}),
        edit(sm, "add", device_id, {"model_id": "geo_fencing"}),
    )
    async with sm() as db:
        row = (await db.execute(select(StreamSession).where(StreamSession.device_id == device_id))).scalar_one()
    assert sorted(e["model_id"] for e in row.models) == ["fall_detection", "geo_fencing", "ppe_detection"]
    assert row.models_revision == 3


async def test_g5b_concurrent_adds_with_no_session_yet(sm):
    device_id = await make_device(sm)
    await asyncio.gather(
        edit(sm, "add", device_id, {"model_id": "fall_detection"}, start_delay=0.3),
        edit(sm, "add", device_id, {"model_id": "ppe_detection"}, start_delay=0.3),
    )
    async with sm() as db:
        rows = (await db.execute(select(StreamSession).where(StreamSession.device_id == device_id))).scalars().all()
    assert len(rows) == 1  # the unique index picked one starter
    assert sorted(e["model_id"] for e in rows[0].models) == ["fall_detection", "ppe_detection"]


# =============================================================================
# G6: a legacy camera beside a multi-model camera stays legacy
# =============================================================================


async def test_g6_legacy_camera_untouched_by_neighbour(sm):
    legacy_device = await make_device(sm)
    legacy_session = await make_legacy_session(sm, legacy_device, "fall_detection")
    multi_device = await make_device(sm)
    await edit(sm, "add", multi_device, {"model_id": "ppe_detection"})
    await edit(sm, "add", multi_device, {"model_id": "geo_fencing"})
    runtime = FakeRuntime(lambda m, n: result(False))
    loop = make_loop(sm, runtime)
    await loop.start()
    try:
        await wait_for(lambda: runtime.count["fall_detection"] >= 5 and runtime.count["geo_fencing"] >= 5)
        assert loop._task_meta[legacy_session]["kind"] == "legacy"
    finally:
        await stop_loop(loop)
    assert {c["kind"] for c in runtime.calls_for("fall_detection")} == {"legacy"}
    assert runtime.fetches  # the multi camera used the shared-frame path

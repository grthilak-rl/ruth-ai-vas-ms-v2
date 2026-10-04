"""Real InferenceLoopService.stop() with several running sessions (Postgres).

    MULTI_MODEL_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

Two legacy sessions and one multi-model session, all actively inferring,
then stop(): it must not raise, and every task including the main loop ends.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.services.inference_loop as il
from tests.multi_model.fakes import FakeRuntime, result, wait_for
from tests.multi_model.test_multi_model_loop import edit, make_device, make_legacy_session, make_loop

DATABASE_URL = os.environ.get("MULTI_MODEL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="MULTI_MODEL_TEST_DATABASE_URL not set")


@pytest.fixture
async def sm():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE violations, stream_sessions, devices CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_stop_with_active_legacy_and_multi_sessions(sm, monkeypatch):
    monkeypatch.setattr(il, "TARGET_FPS", 50.0)
    monkeypatch.setattr(il, "MAX_GPU_UTILIZATION", 100.0)
    for model in ("fall_detection", "ppe_detection"):
        await make_legacy_session(sm, await make_device(sm), model)
    multi_device = await make_device(sm)
    await edit(sm, "add", multi_device, {"model_id": "geo_fencing"})
    await edit(sm, "add", multi_device, {"model_id": "tank_overflow_monitoring"})

    runtime = FakeRuntime(lambda _m, _n: result(False))
    loop = make_loop(sm, runtime)
    await loop.start()
    await wait_for(lambda: all(runtime.count[m] >= 3 for m in (
        "fall_detection", "ppe_detection", "geo_fencing", "tank_overflow_monitoring")))
    tasks = list(loop._session_tasks.values())
    assert len(tasks) == 3

    await loop.stop()  # raised RuntimeError before the fix

    assert all(t.done() for t in tasks)
    assert loop._session_tasks == {}
    assert loop._task.done()

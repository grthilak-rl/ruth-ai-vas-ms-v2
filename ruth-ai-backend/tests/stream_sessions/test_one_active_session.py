"""One active stream session per device: the partial unique index, end to end.

Needs a throwaway Postgres already migrated to head (alembic upgrade head):

    STREAM_SESSIONS_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

Skipped when unset. Covers the index definition, the DB-level guarantee, the
partial predicate (inactive sessions never block), and the HTTP race:
two concurrent start-inference calls for one device -> one 200, one 409.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.deps.db import get_db
from app.deps.services import get_stream_service
from app.main import create_application
from app.models import Device, StreamSession, StreamState
from app.services.stream_service import StreamService

DATABASE_URL = os.environ.get("STREAM_SESSIONS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="STREAM_SESSIONS_TEST_DATABASE_URL not set"
)

INDEX = "uq_stream_sessions_device_active"


class SlowVAS:
    """Fake VAS whose start_stream takes a while, widening the race window."""

    def __init__(self, delay: float = 0.5) -> None:
        self.delay = delay
        self.calls = 0

    async def start_stream(self, _vas_device_id: str):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return SimpleNamespace(v2_stream_id=str(uuid.uuid4()))


@pytest.fixture
async def session_factory():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stream_sessions, devices CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def device(session_factory) -> Device:
    async with session_factory() as db:
        row = Device(vas_device_id=str(uuid.uuid4()), name="race-test camera", is_active=True)
        db.add(row)
        await db.commit()
        return row


def _active(device_id, model_id="fall_detection", state=StreamState.LIVE) -> StreamSession:
    return StreamSession(
        device_id=device_id,
        model_id=model_id,
        state=state,
        started_at=datetime.now(timezone.utc),
    )


async def test_index_definition(session_factory):
    async with session_factory() as db:
        definition = (
            await db.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": INDEX}
            )
        ).scalar_one()
    assert "UNIQUE INDEX" in definition
    assert "(device_id)" in definition
    for state in ("starting", "live", "stopping"):
        assert f"'{state}'" in definition


async def test_database_rejects_second_active_session(session_factory, device):
    async with session_factory() as db:
        db.add(_active(device.id))
        await db.commit()
    async with session_factory() as db:
        db.add(_active(device.id, model_id="ppe_detection", state=StreamState.STARTING))
        with pytest.raises(IntegrityError, match=INDEX):
            await db.commit()


async def test_inactive_sessions_never_block(session_factory, device):
    async with session_factory() as db:
        for state in (StreamState.STOPPED, StreamState.STOPPED, StreamState.ERROR):
            db.add(_active(device.id, state=state))
        db.add(_active(device.id, state=StreamState.LIVE))
        await db.commit()  # many inactive + one active is fine


@pytest.fixture
def app(session_factory):
    application = create_application()
    vas = SlowVAS()

    async def db_override() -> AsyncGenerator:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def stream_service_override(db=Depends(get_db)):
        yield StreamService(vas, db)

    application.dependency_overrides[get_db] = db_override
    application.dependency_overrides[get_stream_service] = stream_service_override
    application.state.vas = vas
    return application


async def test_concurrent_start_inference_one_wins_one_409(app, session_factory, device):
    url = f"/api/v1/devices/{device.id}/start-inference"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first, second = await asyncio.gather(
            client.post(url, json={"model_id": "fall_detection"}),
            client.post(url, json={"model_id": "ppe_detection"}),
        )

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 409], (first.text, second.text)
    loser = first if first.status_code == 409 else second
    winner = second if loser is first else first
    assert loser.json()["detail"]["error"] == "stream_already_active"
    assert loser.json()["detail"]["details"]["session_id"] == winner.json()["session_id"]
    assert app.state.vas.calls == 1  # the loser never reached VAS

    async with session_factory() as db:
        active = (
            await db.execute(
                select(StreamSession).where(
                    StreamSession.device_id == device.id,
                    StreamSession.state.in_(
                        [StreamState.STARTING, StreamState.LIVE, StreamState.STOPPING]
                    ),
                )
            )
        ).scalars().all()
    assert len(active) == 1
    assert str(active[0].id) == winner.json()["session_id"]


async def test_sequential_start_is_still_idempotent(app, device):
    url = f"/api/v1/devices/{device.id}/start-inference"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(url, json={"model_id": "fall_detection"})
        second = await client.post(url, json={"model_id": "ppe_detection"})
    assert first.status_code == 200
    # Unchanged behaviour: a non-racing second start returns the existing session.
    assert second.status_code == 200
    assert second.json()["session_id"] == first.json()["session_id"]
    assert second.json()["model_id"] == "fall_detection"

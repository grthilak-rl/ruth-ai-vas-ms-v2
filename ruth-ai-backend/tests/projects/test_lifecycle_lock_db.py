"""The lifecycle lock against real Postgres.

17 Nov 2026: End left its advisory lock on a pooled connection (the lock was
taken on the request session, whose connection went back to the pool at the
first commit, so the unlock ran on another connection and did nothing). The
Start that followed waited on the lock until nginx gave up (504), and so
would every later Stop/End/Resume until the backend restarted.

These run the real service, one session per action like one request each,
on a pool with several idle connections (FIFO), which is what made the
unlock land on a different connection in production. A guard timeout turns
a regression into a failure instead of a hung test run.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Device, Project
from app.models.project import (
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_ENDED,
    PROJECT_STATE_STOPPED,
    ProjectCamera,
)
from app.services.project_lifecycle import (
    LIFECYCLE_BUSY,
    LIFECYCLE_LOCK_KEY,
    CameraState,
    LifecycleError,
    LifecycleLock,
    ProjectLifecycleService,
)

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)

GUARD_S = 15
NOW = datetime.now(timezone.utc)


class FakeVAS:
    def __init__(self, enabled: dict[str, bool]):
        self.enabled = enabled
        self.calls: list[tuple[str, bool]] = []

    async def set_device_enabled(self, vas_id, enabled):
        self.calls.append((vas_id, enabled))
        self.enabled[vas_id] = enabled

    async def update_storage_config(self, updates):
        return {"retention_paused": updates.get("retention_paused")}

    async def get_storage_config(self):
        return {"retention_paused": True}


class FakeStreams:
    async def stop_inference(self, device_id):
        return None


@pytest.fixture
async def pooled(engine):
    """A second engine on the same DB with a FIFO pool of idle connections."""
    eng = create_async_engine(engine.url, pool_size=4, max_overflow=0)
    conns = [await eng.connect() for _ in range(4)]
    for c in conns:
        await c.execute(text("SELECT 1"))
    for c in conns:
        await c.close()
    yield eng
    await eng.dispose()


@pytest.fixture
async def site(pooled, monkeypatch):
    """HPCL active with one camera (75080), and three demo cameras, all known to Ruth."""
    factory = async_sessionmaker(pooled, expire_on_commit=False)
    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'ended'"))
        names = ["75080", "DEMO-CAMERA", "DEMO-CAMERA2", "DEMO-CAMERA3"]
        devices = {n: Device(vas_device_id=f"vas-{n}", name=n, is_active=True, enabled=True) for n in names}
        db.add_all(devices.values())
        hpcl = Project(name="HPCL", slug="hpcl", state=PROJECT_STATE_ACTIVE, started_by="t",
                       started_at=NOW - timedelta(days=30))
        db.add(hpcl)
        await db.commit()
        ids = {n: str(d.id) for n, d in devices.items()}
    vas = FakeVAS({"vas-75080": True, "vas-DEMO-CAMERA": False, "vas-DEMO-CAMERA2": False,
                   "vas-DEMO-CAMERA3": False})

    async def cameras(self):
        return [CameraState(f"vas-{n}", n, vas.enabled[f"vas-{n}"], "live", ids[n], intent="off")
                for n in ids]

    monkeypatch.setattr(ProjectLifecycleService, "cameras", cameras)
    return factory, vas


async def lock_holders(engine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted"
            " AND ((classid::bigint << 32) | objid::bigint) = :k"), {"k": LIFECYCLE_LOCK_KEY})).scalar()


async def act(factory, vas, fn):
    """One action in its own session, like one HTTP request."""
    async with factory() as db:
        svc = ProjectLifecycleService(db, vas, FakeStreams())
        return await asyncio.wait_for(fn(svc), GUARD_S)


async def state_of(factory, slug):
    async with factory() as db:
        return (await db.execute(select(Project.state).where(Project.slug == slug))).scalar_one()


async def test_end_then_start_back_to_back(site, pooled) -> None:
    factory, vas = site
    await act(factory, vas, lambda s: s.stop("admin", end=True, confirm_name="HPCL"))
    assert await state_of(factory, "hpcl") == PROJECT_STATE_ENDED
    assert await lock_holders(pooled) == 0, "End left the lifecycle lock held"

    demos = ["vas-DEMO-CAMERA", "vas-DEMO-CAMERA2", "vas-DEMO-CAMERA3"]
    result = await act(factory, vas, lambda s: s.start(
        "admin", name="Post HPCL Dev", confirm_name="Post HPCL Dev", camera_ids=demos))
    assert result.project.state == PROJECT_STATE_ACTIVE
    assert await lock_holders(pooled) == 0, "Start left the lifecycle lock held"
    assert {k for k, on in vas.enabled.items() if on} == set(demos)
    async with factory() as db:
        picked = (await db.execute(select(ProjectCamera.device_id).where(
            ProjectCamera.project_id == result.project.id))).scalars().all()
    assert len(picked) == 3


async def test_stop_resume_stop(site, pooled) -> None:
    factory, vas = site
    await act(factory, vas, lambda s: s.stop("admin"))
    assert await state_of(factory, "hpcl") == PROJECT_STATE_STOPPED
    assert vas.enabled["vas-75080"] is False
    await act(factory, vas, lambda s: s.resume("admin"))
    assert await state_of(factory, "hpcl") == PROJECT_STATE_ACTIVE
    assert vas.enabled["vas-75080"] is True
    await act(factory, vas, lambda s: s.stop("admin"))
    assert await state_of(factory, "hpcl") == PROJECT_STATE_STOPPED
    assert await lock_holders(pooled) == 0


async def test_a_second_action_is_refused_at_once_not_queued(site, pooled) -> None:
    factory, vas = site
    lock = LifecycleLock(pooled)
    async with lock.held():
        async with factory() as db:
            svc = ProjectLifecycleService(db, vas, FakeStreams())
            assert await svc.busy()
            started = asyncio.get_running_loop().time()
            with pytest.raises(LifecycleError) as err:
                await asyncio.wait_for(svc.stop("admin"), GUARD_S)
            assert err.value.code == LIFECYCLE_BUSY
            assert asyncio.get_running_loop().time() - started < 2
    assert await state_of(factory, "hpcl") == PROJECT_STATE_ACTIVE  # nothing changed
    assert vas.calls == []
    assert await lock_holders(pooled) == 0
    async with factory() as db:
        assert not await ProjectLifecycleService(db, vas, FakeStreams()).busy()


async def test_a_failed_action_releases_the_lock(site, pooled) -> None:
    factory, vas = site
    with pytest.raises(LifecycleError):
        await act(factory, vas, lambda s: s.stop("admin", end=True, confirm_name="wrong"))
    assert await lock_holders(pooled) == 0
    await act(factory, vas, lambda s: s.stop("admin", end=True, confirm_name="HPCL"))
    assert await state_of(factory, "hpcl") == PROJECT_STATE_ENDED


async def test_api_answers_409_while_an_action_runs(site, pooled, monkeypatch) -> None:
    """Start is refused before its backup; Stop before touching anything."""
    from httpx import ASGITransport, AsyncClient

    import app.deps.db as deps_db
    from app.api.v1.admin import projects as projects_api
    from app.core import database
    from app.core.admin_auth import AdminPrincipal, require_admin
    from app.deps import services as deps_services
    from app.main import create_application

    factory, vas = site

    async def sessions():
        async with factory() as s:
            yield s

    monkeypatch.setattr(deps_db, "get_db_session", sessions)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    monkeypatch.setattr(deps_services, "_vas_client", vas)
    backups: list[str] = []

    async def no_backup(self, slug, **_):
        backups.append(slug)
        raise AssertionError("backup must not run while another action holds the lock")

    monkeypatch.setattr(projects_api.ProjectService, "run_backup", no_backup)
    app = create_application()
    app.dependency_overrides[require_admin] = lambda: AdminPrincipal("admin", "admin", NOW + timedelta(hours=1))
    from app.deps.services import get_vas_client
    app.dependency_overrides[get_vas_client] = lambda: vas

    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'ended' WHERE slug = 'hpcl'"))
        await db.commit()

    async with LifecycleLock(pooled).held():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            r = await asyncio.wait_for(client.post("/api/v1/admin/projects/start", json={
                "name": "Post HPCL Dev", "confirm_name": "Post HPCL Dev", "camera_ids": []}), GUARD_S)
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["error"] == LIFECYCLE_BUSY
            assert "Another project action is running" in r.json()["detail"]["message"]
    assert backups == []
    async with factory() as db:
        assert (await db.execute(select(Project).where(Project.slug == "post-hpcl-dev"))).first() is None


"""Project actions as background jobs, against real Postgres (and real pg_dump).

The cases that matter in production:

- Start runs backup -> project -> cameras and records each stage.
- A restart in the middle of Start leaves the job "interrupted"; Retry
  finishes it without a second backup or a second project.
- One action at a time, enforced by the database.
- A camera VAS will not switch fails the job naming it; Retry finishes.
- Stop / End / Resume as jobs, and an End cut short in "stopping".
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Device, Project
from app.models.project import PROJECT_STATE_ACTIVE, PROJECT_STATE_ENDED, PROJECT_STATE_STOPPING, ProjectCamera
from app.models.project_job import ProjectJob
from app.services import project_jobs as jobs
from app.services.project_service import ProjectService

pytestmark = pytest.mark.skipif(
    not os.environ.get("PROJECT_TEST_DATABASE_URL"), reason="PROJECT_TEST_DATABASE_URL not set"
)

NOW = datetime.now(timezone.utc)
GUARD_S = 60
DEMOS = ["vas-DEMO-CAMERA", "vas-DEMO-CAMERA2", "vas-DEMO-CAMERA3"]


class FakeVAS:
    """VAS's devices and enabled flags; optionally fails or blocks on some."""

    def __init__(self, enabled: dict[str, bool]):
        self.enabled = enabled
        self.calls: list[tuple[str, bool]] = []
        self.fail_on: set[str] = set()
        self.block_on: str | None = None
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
        self.device_lists = 0

    async def get_devices(self, skip=0, limit=100):
        self.device_lists += 1
        return [SimpleNamespace(id=k, name=k.removeprefix("vas-"), enabled=v, video_state="live",
                                is_active=v, description=None, display_name=None, location=None,
                                manway=None, in_out=None)
                for k, v in self.enabled.items()]

    async def set_device_enabled(self, vas_id, enabled):
        if vas_id == self.block_on:
            self.blocked.set()
            await self.release.wait()
        if vas_id in self.fail_on:
            raise RuntimeError("VAS timeout")
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
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def site(factory, tmp_path, monkeypatch):
    """HPCL ended (74004 was its camera); four cameras known to Ruth, all disabled."""
    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'ended'"))
        db.add(Project(name="HPCL", slug="hpcl", state=PROJECT_STATE_ENDED, started_by="t",
                       started_at=NOW - timedelta(days=20), ended_at=NOW - timedelta(hours=1)))
        for n in ["74004", "DEMO-CAMERA", "DEMO-CAMERA2", "DEMO-CAMERA3"]:
            db.add(Device(vas_device_id=f"vas-{n}", name=n, is_active=True, enabled=False))
        await db.commit()
    vas = FakeVAS({"vas-74004": False, **{d: False for d in DEMOS}})

    # Real pg_dump, into tmp, of the test database.
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "project_backup_dir", str(tmp_path))
    monkeypatch.setattr(settings, "project_backup_require_mount", False)
    dsn = os.environ["PROJECT_TEST_DATABASE_URL"].replace("+asyncpg", "")
    monkeypatch.setattr(ProjectService, "_dump_dsn", lambda self: dsn)
    dumps: list[str] = []
    real_backup = ProjectService.run_backup

    async def counting_backup(self, slug, **kw):
        path = await real_backup(self, slug, **kw)
        dumps.append(str(path))
        return path

    monkeypatch.setattr(ProjectService, "run_backup", counting_backup)
    return SimpleNamespace(vas=vas, dumps=dumps, backup_dir=tmp_path)


def run(job_id, factory, site):
    return jobs.run_job(job_id, factory, vas_client=site.vas, stream_service_factory=lambda db: FakeStreams())


async def queue(factory, action, params, by="admin"):
    async with factory() as db:
        return await jobs.create_job(db, action, params, by)


async def load(factory, job_id) -> ProjectJob:
    async with factory() as db:
        return await db.get(ProjectJob, job_id)


START = {"name": "Post HPCL Dev", "confirm_name": "Post HPCL Dev", "camera_ids": DEMOS,
         "allow_no_cameras": False}


async def dev_projects(factory) -> int:
    async with factory() as db:
        return (await db.execute(select(func.count()).select_from(Project)
                                 .where(Project.slug == "post-hpcl-dev"))).scalar_one()


async def test_start_job_runs_every_stage(factory, site) -> None:
    job = await queue(factory, "start", START)
    await asyncio.wait_for(run(job.id, factory, site), GUARD_S)
    done = await load(factory, job.id)
    assert done.state == "succeeded", done.error_message
    assert [s["status"] for s in jobs.stage_list(done)] == ["done", "done", "done", "done"]
    assert done.backup_path and os.path.getsize(done.backup_path) > 0
    assert {k for k, on in site.vas.enabled.items() if on} == set(DEMOS)
    async with factory() as db:
        ruth_enabled = set((await db.execute(select(Device.name).where(Device.enabled.is_(True)))).scalars())
        assert ruth_enabled == {"DEMO-CAMERA", "DEMO-CAMERA2", "DEMO-CAMERA3"}, "Ruth's camera list not refreshed"
        project = await db.get(Project, done.project_id)
        assert project.state == PROJECT_STATE_ACTIVE and project.name == "Post HPCL Dev"
        picked = (await db.execute(select(func.count()).select_from(ProjectCamera)
                                   .where(ProjectCamera.project_id == project.id))).scalar_one()
        assert picked == 3
        hpcl = (await db.execute(select(Project).where(Project.slug == "hpcl"))).scalar_one()
        assert hpcl.backup_path == done.backup_path


async def test_restart_mid_start_then_retry_finishes_it(factory, site) -> None:
    """Cut short while switching cameras: one backup, one project, all cameras right."""
    site.vas.block_on = "vas-DEMO-CAMERA2"
    job = await queue(factory, "start", START)
    task = asyncio.create_task(run(job.id, factory, site))
    await asyncio.wait_for(site.vas.blocked.wait(), GUARD_S)
    mid = await load(factory, job.id)
    assert (mid.state, mid.stage) == ("running", "cameras")
    assert mid.stage_detail == "DEMO-CAMERA2 (2/3)"

    # A hard restart: the task dies without its own cleanup running, and the
    # next startup finds the row still "running".
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with factory() as db:
        await db.execute(text("UPDATE project_jobs SET state = 'running', error_code = NULL"))
        await db.commit()
    assert await jobs.recover_interrupted(factory) == 1
    cut = await load(factory, job.id)
    assert cut.state == "interrupted" and cut.stage == "cameras"
    assert 'during "Switch cameras in VAS"' in cut.error_message
    assert [s["status"] for s in jobs.stage_list(cut)] == ["done", "done", "interrupted", "pending"]
    assert await dev_projects(factory) == 1
    assert site.vas.enabled["vas-DEMO-CAMERA"] and not site.vas.enabled["vas-DEMO-CAMERA2"]

    site.vas.block_on = None
    async with factory() as db:
        again = await jobs.retry_job(db, job.id, "admin")
    assert again.state == "queued" and again.attempts == 2
    await asyncio.wait_for(run(job.id, factory, site), GUARD_S)
    done = await load(factory, job.id)
    assert done.state == "succeeded", done.error_message
    assert len(site.dumps) == 1, "Retry took a second backup"
    assert done.backup_path == site.dumps[0]
    assert await dev_projects(factory) == 1, "Retry created the project twice"
    assert {k for k, on in site.vas.enabled.items() if on} == set(DEMOS)


async def test_restart_after_backup_before_project(factory, site) -> None:
    """Cut short after the dump: Retry reuses it and creates the project once."""
    job = await queue(factory, "start", START)
    async with factory() as db:
        path = await ProjectService(db).run_backup("post-hpcl-dev")
        await db.execute(text("UPDATE project_jobs SET state = 'running', stage = 'project', "
                              "backup_path = :p"), {"p": str(path)})
        await db.commit()
    await jobs.recover_interrupted(factory)
    async with factory() as db:
        await jobs.retry_job(db, job.id, "admin")
    await asyncio.wait_for(run(job.id, factory, site), GUARD_S)
    done = await load(factory, job.id)
    assert done.state == "succeeded", done.error_message
    assert len(site.dumps) == 1 and done.backup_path == str(path)
    assert await dev_projects(factory) == 1


async def test_one_action_at_a_time(factory, site) -> None:
    first = await queue(factory, "start", START)
    with pytest.raises(jobs.JobBusyError) as busy:
        await queue(factory, "start", START)
    assert busy.value.active.id == first.id
    await asyncio.wait_for(run(first.id, factory, site), GUARD_S)
    second = await queue(factory, "stop", {})  # free again once finished
    assert second.state == "queued"


async def test_failing_camera_fails_the_job_then_retry_finishes(factory, site) -> None:
    site.vas.fail_on = {"vas-DEMO-CAMERA3"}
    job = await queue(factory, "start", START)
    await asyncio.wait_for(run(job.id, factory, site), GUARD_S)
    failed = await load(factory, job.id)
    assert failed.state == "failed" and failed.error_code == "incomplete"
    assert "DEMO-CAMERA3: VAS did not enable it" in failed.error_message
    assert failed.result["errors"] == [failed.error_message]

    site.vas.fail_on = set()
    async with factory() as db:
        await jobs.retry_job(db, job.id, "admin")
    await asyncio.wait_for(run(job.id, factory, site), GUARD_S)
    done = await load(factory, job.id)
    assert done.state == "succeeded" and len(site.dumps) == 1
    async with factory() as db:
        project = await db.get(Project, done.project_id)
        assert project.lifecycle_error is None


async def test_refused_start_fails_with_its_reason(factory, site) -> None:
    job = await queue(factory, "start", {**START, "camera_ids": []})
    await asyncio.wait_for(run(job.id, factory, site), GUARD_S)
    failed = await load(factory, job.id)
    assert failed.state == "failed" and failed.error_code == "no_cameras"
    assert await dev_projects(factory) == 0


async def test_stop_resume_end_as_jobs(factory, site) -> None:
    job = await queue(factory, "start", START)
    await asyncio.wait_for(run(job.id, factory, site), GUARD_S)

    for action, params, state, on in (
        ("stop", {}, "stopped", set()),
        ("resume", {}, "active", set(DEMOS)),
        ("end", {"confirm_name": "Post HPCL Dev"}, "ended", set()),
    ):
        j = await queue(factory, action, params)
        await asyncio.wait_for(run(j.id, factory, site), GUARD_S)
        done = await load(factory, j.id)
        assert done.state == "succeeded", (action, done.error_message)
        assert all(s["status"] == "done" for s in jobs.stage_list(done))
        assert await project_state(factory, "post-hpcl-dev") == state
        assert {k for k, v in site.vas.enabled.items() if v} == on, action


async def test_end_cut_short_in_stopping_is_finished_by_retry(factory, site) -> None:
    job = await queue(factory, "start", START)
    await asyncio.wait_for(run(job.id, factory, site), GUARD_S)
    site.vas.block_on = "vas-DEMO-CAMERA"
    end = await queue(factory, "end", {"confirm_name": "Post HPCL Dev"})
    task = asyncio.create_task(run(end.id, factory, site))
    await asyncio.wait_for(site.vas.blocked.wait(), GUARD_S)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cut = await load(factory, end.id)
    assert cut.state == "interrupted"  # the cancellation path says so itself
    assert await project_state(factory, "post-hpcl-dev") == PROJECT_STATE_STOPPING

    site.vas.block_on = None
    async with factory() as db:
        await jobs.retry_job(db, end.id, "admin")
    await asyncio.wait_for(run(end.id, factory, site), GUARD_S)
    assert (await load(factory, end.id)).state == "succeeded"
    assert await project_state(factory, "post-hpcl-dev") == PROJECT_STATE_ENDED
    assert not any(site.vas.enabled.values())


async def test_only_the_latest_job_can_be_retried(factory, site) -> None:
    old = await queue(factory, "start", {**START, "camera_ids": []})
    await asyncio.wait_for(run(old.id, factory, site), GUARD_S)  # fails: no cameras
    new = await queue(factory, "start", START)
    await asyncio.wait_for(run(new.id, factory, site), GUARD_S)
    async with factory() as db:
        with pytest.raises(jobs.JobNotRetryableError):
            await jobs.retry_job(db, old.id, "admin")
        with pytest.raises(jobs.JobNotRetryableError):
            await jobs.retry_job(db, new.id, "admin")  # succeeded


async def project_state(factory, slug):
    async with factory() as db:
        return (await db.execute(select(Project.state).where(Project.slug == slug))).scalar_one()


# ---------------------------------------------------------------------------
# API: 202 + job, polling, 409 while one runs, 422 without cameras
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(factory, site, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    import app.deps.db as deps_db
    from app.core import database
    from app.core.admin_auth import AdminPrincipal, require_admin
    from app.deps import services as deps_services
    from app.deps.services import get_vas_client
    from app.main import create_application

    async def sessions():
        async with factory() as s:
            yield s

    monkeypatch.setattr(deps_db, "get_db_session", sessions)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    monkeypatch.setattr(deps_services, "_vas_client", site.vas)
    launched: list = []
    monkeypatch.setattr(jobs, "launch", lambda job_id, f, **kw: launched.append(job_id))
    app = create_application()
    app.dependency_overrides[require_admin] = lambda: AdminPrincipal("admin", "admin", NOW + timedelta(hours=1))
    app.dependency_overrides[get_vas_client] = lambda: site.vas
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        c.launched = launched
        yield c


async def test_api_start_returns_202_and_the_job(client, factory, site) -> None:
    r = await client.post("/api/v1/admin/projects/start", json=START)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["state"] == "queued" and body["action"] == "start"
    assert [s["key"] for s in body["stages"]] == ["backup", "project", "cameras", "refresh"]
    assert client.launched == [__import__("uuid").UUID(body["id"])]

    busy = await client.post("/api/v1/admin/projects/start", json=START)
    assert busy.status_code == 409
    assert busy.json()["detail"]["error"] == "lifecycle_busy"
    assert busy.json()["detail"]["details"]["job_id"] == body["id"]

    await asyncio.wait_for(run(body["id"], factory, site), GUARD_S)
    polled = (await client.get(f"/api/v1/admin/projects/jobs/{body['id']}")).json()
    assert polled["state"] == "succeeded" and polled["project_name"] == "Post HPCL Dev"
    assert len(polled["cameras"]) == 4
    state = (await client.get("/api/v1/admin/projects/jobs/state")).json()
    assert state["active"] is None and state["latest"]["id"] == body["id"]


async def test_api_refuses_start_without_cameras(client) -> None:
    r = await client.post("/api/v1/admin/projects/start", json={**START, "camera_ids": []})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "no_cameras"
    ok = await client.post("/api/v1/admin/projects/start",
                           json={**START, "camera_ids": [], "allow_no_cameras": True})
    assert ok.status_code == 202


async def test_api_retry(client, factory, site) -> None:
    site.vas.fail_on = {"vas-DEMO-CAMERA2"}
    body = (await client.post("/api/v1/admin/projects/start", json=START)).json()
    await asyncio.wait_for(run(body["id"], factory, site), GUARD_S)
    failed = (await client.get(f"/api/v1/admin/projects/jobs/{body['id']}")).json()
    assert failed["state"] == "failed" and failed["can_retry"]
    assert failed["stages"][2]["status"] == "failed"
    site.vas.fail_on = set()
    r = await client.post(f"/api/v1/admin/projects/jobs/{body['id']}/retry")
    assert r.status_code == 202 and r.json()["attempts"] == 2

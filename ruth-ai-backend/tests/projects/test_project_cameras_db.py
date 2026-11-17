"""Cameras in a project: dated membership, "Change cameras" jobs, analytics.

Real Postgres (membership intervals, partial unique index, range_agg).

- Start opens memberships at the project's start; End closes them.
- "Change cameras" adds/removes mid-project: VAS first, then the membership
  row; a restart in the middle and Retry finish it without duplicates; a
  camera VAS refuses fails the job naming it; refused while stopped; one
  action at a time.
- Removing a camera never touches its VAS placement (location history).
- Analytics: camera totals and the per-camera list are the members during
  the period; rates are per monitored camera-hour (stream sessions).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Device, Project, StreamSession, StreamState, Violation, ViolationStatus, ViolationType
from app.models.project import PROJECT_STATE_ACTIVE, PROJECT_STATE_ENDED, ProjectCamera
from app.models.project_job import ProjectJob
from app.services import coverage
from app.services import project_jobs as jobs
from tests.projects.test_project_jobs_db import FakeStreams, FakeVAS

pytestmark = pytest.mark.skipif(
    not os.environ.get("PROJECT_TEST_DATABASE_URL"), reason="PROJECT_TEST_DATABASE_URL not set"
)

GUARD_S = 60
NOW = datetime.now(timezone.utc)


class StrictVAS(FakeVAS):
    """Only the calls a project action may make; anything else fails the test.

    FakeVAS defines exactly get_devices, set_device_enabled and the storage
    config calls. Placements (location history) live in VAS behind other
    client methods; a project action reaching for any of them lands in
    __getattr__ here and fails.
    """

    def __getattr__(self, name):
        raise AssertionError(f"project action called VAS.{name}, which it must never do")


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def dev(factory):
    """Post HPCL Dev active since 2 days, DEMO-CAMERA a member; 74004 and DEMO-CAMERA2 not."""
    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'ended', ended_at = now() - interval '3 days'"))
        project = Project(name="Post HPCL Dev", slug="post-hpcl-dev", state=PROJECT_STATE_ACTIVE,
                          started_by="t", started_at=NOW - timedelta(days=2))
        db.add(project)
        devices = {}
        for n in ["74004", "DEMO-CAMERA", "DEMO-CAMERA2"]:
            devices[n] = Device(vas_device_id=f"vas-{n}", name=n, is_active=True, enabled=n == "DEMO-CAMERA")
            db.add(devices[n])
        await db.flush()
        db.add(ProjectCamera(project_id=project.id, device_id=devices["DEMO-CAMERA"].id, source="dialog",
                             joined_at=project.started_at))
        await db.commit()
    vas = StrictVAS({"vas-74004": False, "vas-DEMO-CAMERA": True, "vas-DEMO-CAMERA2": False})
    return SimpleNamespace(project_id=project.id, devices={k: d.id for k, d in devices.items()}, vas=vas)


def run(job_id, factory, vas):
    return jobs.run_job(job_id, factory, vas_client=vas, stream_service_factory=lambda db: FakeStreams())


async def queue(factory, action, params):
    async with factory() as db:
        return await jobs.create_job(db, action, params, "admin")


async def load(factory, job_id) -> ProjectJob:
    async with factory() as db:
        return await db.get(ProjectJob, job_id)


async def memberships(factory, project_id):
    async with factory() as db:
        rows = (await db.execute(
            select(Device.name, ProjectCamera.joined_at, ProjectCamera.left_at)
            .join(Device, Device.id == ProjectCamera.device_id)
            .where(ProjectCamera.project_id == project_id)
            .order_by(Device.name, ProjectCamera.joined_at)
        )).all()
    return [(r.name, r.left_at is None) for r in rows]


# ---------------------------------------------------------------------------
# Change cameras
# ---------------------------------------------------------------------------


async def test_add_and_remove_mid_project(factory, dev) -> None:
    job = await queue(factory, "cameras", {"add": ["vas-74004"], "remove": ["vas-DEMO-CAMERA"]})
    await asyncio.wait_for(run(job.id, factory, dev.vas), GUARD_S)
    done = await load(factory, job.id)
    assert done.state == "succeeded", done.error_message
    assert [s["key"] for s in jobs.stage_list(done)] == ["cameras", "refresh"]
    assert all(s["status"] == "done" for s in jobs.stage_list(done))
    assert dev.vas.enabled == {"vas-74004": True, "vas-DEMO-CAMERA": False, "vas-DEMO-CAMERA2": False}
    # DEMO-CAMERA's interval is closed (it still counts for the time it was in); 74004 is open.
    assert await memberships(factory, dev.project_id) == [("74004", True), ("DEMO-CAMERA", False)]
    async with factory() as db:
        ruth = dict((await db.execute(select(Device.name, Device.enabled))).all())
    assert ruth["74004"] is True and ruth["DEMO-CAMERA"] is False, "Ruth's camera list not refreshed"


async def test_a_camera_can_leave_and_rejoin(factory, dev) -> None:
    for params in ({"remove": ["vas-DEMO-CAMERA"]}, {"add": ["vas-DEMO-CAMERA"]}):
        job = await queue(factory, "cameras", params)
        await asyncio.wait_for(run(job.id, factory, dev.vas), GUARD_S)
        assert (await load(factory, job.id)).state == "succeeded"
    assert await memberships(factory, dev.project_id) == [("DEMO-CAMERA", False), ("DEMO-CAMERA", True)]


async def test_only_one_open_membership_per_camera(factory, dev) -> None:
    async with factory() as db:
        db.add(ProjectCamera(project_id=dev.project_id, device_id=dev.devices["DEMO-CAMERA"],
                             source="dialog", joined_at=NOW))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_removing_never_touches_the_vas_placement(factory, dev) -> None:
    """The only VAS write is the enabled flag; placements are never called."""
    job = await queue(factory, "cameras", {"remove": ["vas-DEMO-CAMERA"]})
    await asyncio.wait_for(run(job.id, factory, dev.vas), GUARD_S)
    assert (await load(factory, job.id)).state == "succeeded"
    assert dev.vas.calls == [("vas-DEMO-CAMERA", False)]


async def test_vas_client_enabled_flag_is_the_only_request(monkeypatch) -> None:
    """The real VAS client: disabling sends PATCH .../enabled and nothing else."""
    import functools

    import httpx

    from app.integrations.vas import client as client_mod

    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        if request.url.path == "/v2/auth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(200, json={"id": "cam-1", "name": "DEMO-CAMERA", "enabled": False})

    monkeypatch.setattr(client_mod.httpx, "AsyncClient",
                        functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))
    vas = client_mod.VASClient(base_url="http://vas.test", client_id="ruth", client_secret="s")
    await vas.connect()
    try:
        await vas.set_device_enabled("cam-1", False)
    finally:
        await vas.close()
    writes = [(m, p, b) for m, p, b in seen if p != "/v2/auth/token"]
    assert writes == [("PATCH", "/api/v1/devices/cam-1/enabled", b'{"enabled":false}')]
    assert not any("placement" in p for _, p, _ in seen)


async def test_restart_mid_change_then_retry(factory, dev) -> None:
    dev.vas.block_on = "vas-DEMO-CAMERA2"
    job = await queue(factory, "cameras", {"add": ["vas-74004", "vas-DEMO-CAMERA2"]})
    task = asyncio.create_task(run(job.id, factory, dev.vas))
    await asyncio.wait_for(dev.vas.blocked.wait(), GUARD_S)
    assert (await load(factory, job.id)).stage_detail == "DEMO-CAMERA2 (2/2)"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with factory() as db:  # a hard kill: the row is still "running"
        await db.execute(text("UPDATE project_jobs SET state = 'running'"))
        await db.commit()
    await jobs.recover_interrupted(factory)
    assert (await load(factory, job.id)).state == "interrupted"
    # 74004 finished before the kill: enabled and a member.
    assert ("74004", True) in await memberships(factory, dev.project_id)

    dev.vas.block_on = None
    async with factory() as db:
        await jobs.retry_job(db, job.id, "admin")
    await asyncio.wait_for(run(job.id, factory, dev.vas), GUARD_S)
    assert (await load(factory, job.id)).state == "succeeded"
    assert await memberships(factory, dev.project_id) == [
        ("74004", True), ("DEMO-CAMERA", True), ("DEMO-CAMERA2", True)]
    assert dev.vas.calls.count(("vas-74004", True)) == 1, "Retry switched a finished camera again"


async def test_failing_camera_is_named_and_left_out_then_retry(factory, dev) -> None:
    dev.vas.fail_on = {"vas-DEMO-CAMERA2"}
    job = await queue(factory, "cameras", {"add": ["vas-74004", "vas-DEMO-CAMERA2"]})
    await asyncio.wait_for(run(job.id, factory, dev.vas), GUARD_S)
    failed = await load(factory, job.id)
    assert failed.state == "failed" and failed.error_code == "incomplete"
    assert "DEMO-CAMERA2: could not add it" in failed.error_message
    assert ("DEMO-CAMERA2", True) not in await memberships(factory, dev.project_id)
    dev.vas.fail_on = set()
    async with factory() as db:
        await jobs.retry_job(db, job.id, "admin")
    await asyncio.wait_for(run(job.id, factory, dev.vas), GUARD_S)
    assert (await load(factory, job.id)).state == "succeeded"
    assert ("DEMO-CAMERA2", True) in await memberships(factory, dev.project_id)


async def test_refused_while_stopped(factory, dev) -> None:
    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'stopped' WHERE slug = 'post-hpcl-dev'"))
        await db.commit()
    job = await queue(factory, "cameras", {"add": ["vas-74004"]})
    await asyncio.wait_for(run(job.id, factory, dev.vas), GUARD_S)
    failed = await load(factory, job.id)
    assert failed.state == "failed" and failed.error_code == "bad_state"
    assert dev.vas.calls == []


async def test_end_closes_every_open_membership(factory, dev) -> None:
    job = await queue(factory, "end", {"confirm_name": "Post HPCL Dev"})
    await asyncio.wait_for(run(job.id, factory, dev.vas), GUARD_S)
    assert (await load(factory, job.id)).state == "succeeded"
    async with factory() as db:
        project = await db.get(Project, dev.project_id)
        rows = (await db.execute(select(ProjectCamera).where(
            ProjectCamera.project_id == dev.project_id))).scalars().all()
    assert project.state == PROJECT_STATE_ENDED
    assert rows and all(r.left_at == project.ended_at for r in rows)


# ---------------------------------------------------------------------------
# API: preview, 202, 409, 422
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(factory, dev, monkeypatch):
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
    monkeypatch.setattr(deps_services, "_vas_client", dev.vas)
    monkeypatch.setattr(jobs, "launch", lambda job_id, f, **kw: None)
    app = create_application()
    app.dependency_overrides[require_admin] = lambda: AdminPrincipal("admin", "admin", NOW + timedelta(hours=1))
    app.dependency_overrides[get_vas_client] = lambda: dev.vas
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_api_preview_lists_members_and_plan(client) -> None:
    r = await client.get("/api/v1/admin/projects/cameras/preflight",
                         params={"add": "vas-74004", "remove": "vas-DEMO-CAMERA"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed"] is True
    assert [m["name"] for m in body["members"]] == ["DEMO-CAMERA"]
    plans = {c["name"]: c for c in body["cameras"]}
    assert plans["74004"]["vas_change"] and "Joins the project from now" in plans["74004"]["actions"]
    assert "Its VAS placement (location history) is not touched" in plans["DEMO-CAMERA"]["actions"]
    assert plans["DEMO-CAMERA2"]["actions"] == ["Not in the project"]


async def test_api_queues_and_refuses(client, factory, dev) -> None:
    ok = await client.post("/api/v1/admin/projects/cameras", json={"add": ["vas-74004"]})
    assert ok.status_code == 202, ok.text
    assert ok.json()["action"] == "cameras" and ok.json()["project_name"] == "Post HPCL Dev"
    busy = await client.post("/api/v1/admin/projects/cameras", json={"add": ["vas-DEMO-CAMERA2"]})
    assert busy.status_code == 409 and busy.json()["detail"]["error"] == "lifecycle_busy"
    await asyncio.wait_for(run(ok.json()["id"], factory, dev.vas), GUARD_S)

    for body, code, error in (
        ({}, 422, "no_change"),
        ({"add": ["vas-74004"]}, 409, "already_member"),
        ({"remove": ["vas-DEMO-CAMERA2"]}, 409, "not_member"),
        ({"add": ["vas-nope"]}, 409, "unknown_camera"),
    ):
        r = await client.post("/api/v1/admin/projects/cameras", json=body)
        assert (r.status_code, r.json()["detail"]["error"]) == (code, error), body


# ---------------------------------------------------------------------------
# Analytics: members during the period; per monitored camera-hour
# ---------------------------------------------------------------------------


@pytest.fixture
async def history(factory):
    """HPCL-like: A whole time, B removed on day 5, C added on day 7; sessions and violations."""
    t0 = NOW - timedelta(days=10)
    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'ended', ended_at = now() - interval '20 days'"))
        p = Project(name="Site", slug="site", state=PROJECT_STATE_ACTIVE, started_by="t", started_at=t0)
        db.add(p)
        cams = {n: Device(vas_device_id=f"vas-{n}", name=n, is_active=True, enabled=False) for n in "ABC"}
        db.add_all(cams.values())
        await db.flush()
        for n, joined, left in (("A", 0, None), ("B", 0, 5), ("C", 7, None)):
            db.add(ProjectCamera(project_id=p.id, device_id=cams[n].id, source="dialog",
                                 joined_at=t0 + timedelta(days=joined),
                                 left_at=t0 + timedelta(days=left) if left is not None else None))
        # A: 10 h on day 1, and an overlapping 2 h session (counted once) -> 10 h.
        # B: 4 h on day 2. C: 6 h on day 8.
        for n, day, start_h, hours in (("A", 1, 0, 10), ("A", 1, 8, 2), ("B", 2, 0, 4), ("C", 8, 0, 6)):
            s0 = t0 + timedelta(days=day, hours=start_h)
            db.add(StreamSession(project_id=p.id, device_id=cams[n].id, model_id="ppe",
                                 state=StreamState.STOPPED, started_at=s0, stopped_at=s0 + timedelta(hours=hours)))
        for n, day, count in (("A", 1, 5), ("B", 2, 2), ("C", 8, 3)):
            for i in range(count):
                db.add(Violation(project_id=p.id, device_id=cams[n].id, type=ViolationType.PPE_VIOLATION,
                                 status=ViolationStatus.OPEN, confidence=0.9,
                                 timestamp=t0 + timedelta(days=day, minutes=10 + i),
                                 camera_name=n, model_id="ppe", model_version="1",
                                 bounding_boxes=[{"x": 1, "y": 2, "width": 3, "height": 4}]))
        await db.commit()
    return SimpleNamespace(project_id=p.id, t0=t0, cams={k: v.id for k, v in cams.items()})


async def test_members_during_a_period(factory, history) -> None:
    t0 = history.t0
    async with factory() as db:
        first_half = await coverage.member_device_ids(db, history.project_id, t0, t0 + timedelta(days=5))
        second = await coverage.member_device_ids(db, history.project_id, t0 + timedelta(days=6), t0 + timedelta(days=10))
        whole = await coverage.member_device_ids(db, history.project_id, t0, t0 + timedelta(days=10))
    ids = {v: k for k, v in history.cams.items()}
    assert {ids[i] for i in first_half} == {"A", "B"}
    assert {ids[i] for i in second} == {"A", "C"}
    assert {ids[i] for i in whole} == {"A", "B", "C"}


async def test_monitored_hours_merge_overlaps_and_clip_to_period(factory, history) -> None:
    t0 = history.t0
    ids = {v: k for k, v in history.cams.items()}
    async with factory() as db:
        whole = await coverage.monitored_hours(db, history.project_id, t0, t0 + timedelta(days=10))
        clipped = await coverage.monitored_hours(
            db, history.project_id, t0 + timedelta(days=1, hours=5), t0 + timedelta(days=3))
    assert {ids[k]: round(v, 2) for k, v in whole.items()} == {"A": 10.0, "B": 4.0, "C": 6.0}
    assert {ids[k]: round(v, 2) for k, v in clipped.items()} == {"A": 5.0, "B": 4.0}
    assert coverage.per_camera_hour(10, 20.0) == 0.5 and coverage.per_camera_hour(3, 0.0) is None


async def test_analytics_api_uses_members_and_camera_hours(factory, history, monkeypatch) -> None:
    from httpx import ASGITransport, AsyncClient

    import app.deps.db as deps_db
    from app.core import database
    from app.main import create_application

    async def sessions():
        async with factory() as s:
            yield s

    monkeypatch.setattr(deps_db, "get_db_session", sessions)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    t0 = history.t0
    params = {"from": (t0 + timedelta(days=6)).isoformat(), "to": (t0 + timedelta(days=10)).isoformat()}
    async with AsyncClient(transport=ASGITransport(app=create_application()), base_url="http://t") as c:
        summary = (await c.get("/api/v1/analytics/summary", params=params)).json()
        devices = (await c.get("/api/v1/analytics/devices/status", params=params)).json()
        whole = (await c.get("/api/v1/analytics/devices/status",
                             params={"from": t0.isoformat(), "to": (t0 + timedelta(days=10)).isoformat()})).json()
    # Days 6-10: A (no violations, no sessions then) and C (3 violations, 6 h).
    assert summary["totals"]["cameras_total"] == 2
    assert summary["totals"]["monitored_camera_hours"] == 6.0
    assert summary["totals"]["violations_per_camera_hour"] == 0.5
    assert {d["camera_name"]: (d["violations_total"], d["monitored_hours"]) for d in devices["devices"]} == {
        "A": (0, 0.0), "C": (3, 6.0)}
    # The whole period still counts B, removed on day 5, for its time in.
    assert whole["summary"]["total_cameras"] == 3
    assert {d["camera_name"] for d in whole["devices"]} == {"A", "B", "C"}
    assert whole["summary"]["monitored_camera_hours"] == 20.0
    assert whole["summary"]["violations_per_camera_hour"] == 0.5


async def test_report_rate_per_monitored_camera_hour(factory, history) -> None:
    from app.services.report.data import load_report
    from app.services.report.insights import fmt_per_hour

    t0 = history.t0
    async with factory() as db:
        project = await db.get(Project, history.project_id)
        db.info["ruth_project_id"] = project.id
        report = await load_report(db, start=t0, end=t0 + timedelta(days=10), project=project, now=NOW)
    assert report.monitored_camera_hours == 20.0
    assert report.incidents_per_camera_hour == report.current.incidents / 20.0
    assert fmt_per_hour(0.15) == "0.15" and fmt_per_hour(2.34) == "2.3" and fmt_per_hour(12.6) == "13"
    # The report's rate is incidents, Analytics' is violations: the report says so.
    from app.services.report.pdf import _counting_note

    note = _counting_note(report)
    assert "<b>Incidents per monitored camera-hour</b>" in note
    assert "not raw detections" in note and "violations (raw detections) per monitored camera-hour" in note

"""Project view mode through the real app, against a real Postgres.

The portal sends ``X-Ruth-Project`` (or ``?project=``) while a past project
is open. These tests drive the actual routes with the actual ``get_db``
(only the session factory is pointed at the test database, and admin auth
is stubbed), so they cover the scoping wiring, not just the hook.

Past-mode writes (the user's rule): reports, violation/training exports and
labelling exports from dismissals must carry the VIEWED project explicitly,
never the database default (which is the current project). Every such write
has a test here that would fail if it fell back to the default.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.project_scope import resolve_scope, scope_session
from app.models import (
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_ENDED,
    CustomerReport,
    Device,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    Project,
    Violation,
    ViolationExport,
    ViolationStatus,
    ViolationType,
)

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def world(factory, tmp_path):
    """HPCL (ended): 2 violations with saved frames. Dev (current): 3."""
    frames = tmp_path / "frames"
    frames.mkdir()
    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'ended'"))
        hpcl = Project(name="HPCL", slug="hpcl", state=PROJECT_STATE_ENDED, started_by="t",
                       started_at=NOW - timedelta(days=30), ended_at=NOW - timedelta(days=3))
        dev = Project(name="Post HPCL Dev", slug="post-hpcl-dev", state=PROJECT_STATE_ACTIVE,
                      started_by="t", started_at=NOW - timedelta(days=2))
        db.add_all([hpcl, dev])
        await db.flush()
        device = Device(vas_device_id=f"vas-{uuid.uuid4()}", name="CAM-1", is_active=True, enabled=True)
        db.add(device)
        await db.flush()
        rows = {"hpcl": [], "dev": []}
        for key, project, n, when in (("hpcl", hpcl, 2, NOW - timedelta(days=5)), ("dev", dev, 3, NOW - timedelta(hours=1))):
            for i in range(n):
                v = Violation(
                    project_id=project.id, device_id=device.id, type=ViolationType.PPE_VIOLATION,
                    status=ViolationStatus.OPEN, confidence=0.9, timestamp=when + timedelta(minutes=i),
                    camera_name=device.name, model_id="ppe", model_version="1",
                    bounding_boxes=[{"x": 1, "y": 2, "width": 3, "height": 4}],
                )
                db.add(v)
                await db.flush()
                name = f"{v.id}.jpg"
                (frames / name).write_bytes(b"\xff\xd8\xff\xd9")
                db.add(Evidence(
                    project_id=project.id, violation_id=v.id, evidence_type=EvidenceType.FRAME,
                    status=EvidenceStatus.READY, file_path=name, requested_at=v.timestamp, retry_count=0,
                ))
                rows[key].append(v.id)
        await db.commit()
        return {"hpcl": hpcl, "dev": dev, "device": device, "frames": frames, **{f"{k}_ids": v for k, v in rows.items()}}


@pytest.fixture
async def client(factory, world, tmp_path, monkeypatch):
    import app.deps.db as deps_db
    from app.api.v1.admin import customer_reports as reports_api
    from app.api.v1.admin import violation_exports as exports_api
    from app.core import database
    from app.core.admin_auth import AdminPrincipal, require_admin
    from app.core.config import get_settings
    from app.main import create_application

    async def test_sessions():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(deps_db, "get_db_session", test_sessions)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)

    settings = get_settings()
    monkeypatch.setattr(settings, "evidence_frame_dir", str(world["frames"]))
    monkeypatch.setattr(settings, "labelling_root", str(tmp_path / "labelling"))

    built: list = []
    monkeypatch.setattr(reports_api, "_start_build", lambda report_id: built.append(report_id))
    captured: dict = {}

    async def fake_run_job(export_id, stmt, options, session_factory):
        captured["stmt"] = stmt

    monkeypatch.setattr(exports_api, "run_job", fake_run_job)

    from unittest.mock import AsyncMock

    from app.deps import get_vas_client

    app = create_application()
    app.dependency_overrides[require_admin] = lambda: AdminPrincipal("admin", "admin", NOW + timedelta(hours=1))
    app.dependency_overrides[get_vas_client] = lambda: AsyncMock()
    import app.deps.services as deps_services

    monkeypatch.setattr(deps_services, "_vas_client", AsyncMock())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        c.captured = captured
        yield c


def past(world) -> dict:
    return {"X-Ruth-Project": world["hpcl"].slug}


async def _get(factory, model, row_id):
    async with factory() as db:
        return await db.get(model, row_id)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def test_violations_default_to_the_current_project(client, world) -> None:
    body = (await client.get("/api/v1/violations")).json()
    assert body["total"] == 3
    assert {i["project_id"] for i in body["items"]} == {str(world["dev"].id)}


@pytest.mark.parametrize("how", ["slug_header", "id_header", "query"])
async def test_violations_in_a_past_project(client, world, how) -> None:
    hpcl = world["hpcl"]
    if how == "slug_header":
        r = await client.get("/api/v1/violations", headers={"X-Ruth-Project": hpcl.slug})
    elif how == "id_header":
        r = await client.get("/api/v1/violations", headers={"X-Ruth-Project": str(hpcl.id)})
    else:
        r = await client.get("/api/v1/violations", params={"project": hpcl.slug})
    body = r.json()
    assert body["total"] == 2
    assert {i["id"] for i in body["items"]} == {str(i) for i in world["hpcl_ids"]}


async def test_unknown_project_is_404(client) -> None:
    r = await client.get("/api/v1/violations", headers={"X-Ruth-Project": "no-such-project"})
    assert r.status_code == 404 and r.json()["detail"]["error"] == "project_not_found"


async def test_type_counts_are_scoped(client, world) -> None:
    def total(body):
        return sum(o.get("count", 0) for o in body["items"])

    assert total((await client.get("/api/v1/violations/types")).json()) == 3
    assert total((await client.get("/api/v1/violations/types", headers=past(world))).json()) == 2


async def test_by_id_opens_any_project_and_says_which(client, world) -> None:
    """A link to an HPCL alert works without the header (and from Dev mode)."""
    vid = world["hpcl_ids"][0]
    r = await client.get(f"/api/v1/violations/{vid}")
    assert r.status_code == 200 and r.json()["project_id"] == str(world["hpcl"].id)


async def test_live_paths_ignore_the_header(factory, world) -> None:
    async with factory() as db:
        scope = await resolve_scope(db, "/api/v1/devices", world["hpcl"].slug)
        assert scope.project_id == world["dev"].id and scope.is_current and scope.filtered
        scope = await resolve_scope(db, "/api/v1/violations", world["hpcl"].slug)
        assert scope.project_id == world["hpcl"].id and not scope.is_current
        scope = await resolve_scope(db, f"/api/v1/violations/{uuid.uuid4()}/frame/image", world["hpcl"].slug)
        assert not scope.filtered


async def test_project_list_and_cameras(client, world) -> None:
    body = (await client.get("/api/v1/projects")).json()
    assert body["current"]["slug"] == "post-hpcl-dev"
    assert {"hpcl", "post-hpcl-dev"} <= {i["slug"] for i in body["items"]}
    cams = (await client.get("/api/v1/projects/hpcl/cameras")).json()
    assert [c["name"] for c in cams] == ["CAM-1"]


async def test_no_project_is_current_between_end_and_start(client, world, factory) -> None:
    """After End and before Start nothing is "Current", not even the last project."""
    async with factory() as db:
        await db.execute(text("UPDATE projects SET state = 'ended' WHERE slug = 'post-hpcl-dev'"))
        await db.commit()
    body = (await client.get("/api/v1/projects")).json()
    assert body["current"] is None
    assert not any(i["is_current"] for i in body["items"])
    assert {i["slug"]: i["state"] for i in body["items"]}["post-hpcl-dev"] == "ended"


# ---------------------------------------------------------------------------
# Past-mode writes: explicit project, never the default
# ---------------------------------------------------------------------------

REPORT = {"preset": "custom", "start": None, "end": None, "gallery": False}


def _report_body():
    day = (NOW - timedelta(days=1)).date().isoformat()
    return {**REPORT, "start": day, "end": day}


async def test_report_built_in_a_past_project_belongs_to_it(client, factory, world) -> None:
    r = await client.post("/api/v1/admin/customer-reports", json=_report_body(), headers=past(world))
    assert r.status_code == 202, r.text
    assert r.json()["project_id"] == str(world["hpcl"].id)
    assert (await _get(factory, CustomerReport, uuid.UUID(r.json()["id"]))).project_id == world["hpcl"].id

    # The same request in current mode belongs to Dev.
    r2 = await client.post("/api/v1/admin/customer-reports", json=_report_body())
    assert r2.json()["project_id"] == str(world["dev"].id)

    # Recent reports are per project.
    listed = (await client.get("/api/v1/admin/customer-reports", headers=past(world))).json()
    assert [i["id"] for i in listed["items"]] == [r.json()["id"]]


async def test_regenerate_keeps_the_original_project(client, factory, world) -> None:
    from app.models.violation_export import EXPORT_READY

    r = await client.post("/api/v1/admin/customer-reports", json=_report_body(), headers=past(world))
    rid = uuid.UUID(r.json()["id"])
    async with factory() as db:
        row = await db.get(CustomerReport, rid)
        row.status = EXPORT_READY
        await db.commit()
    # By-id path, sent from current mode (no header).
    again = await client.post(f"/api/v1/admin/customer-reports/{rid}/regenerate")
    assert again.status_code in (200, 201, 202), again.text
    assert again.json()["project_id"] == str(world["hpcl"].id)


async def test_report_job_reads_only_its_project(factory, world, monkeypatch) -> None:
    """The build job owns its session; it must scope it to the row's project."""
    from app.services.report import job

    async with factory() as db:
        row = CustomerReport(
            project_id=world["hpcl"].id, preset="custom", mode="all",
            period_start=NOW - timedelta(days=60), period_end=NOW, period_label="x",
            options={"gallery": False}, created_at=NOW, updated_at=NOW,
        )
        db.add(row)
        await db.commit()

    seen = {}

    async def spy_load_report(db, **kw):
        seen["violations"] = (await db.execute(select(func.count()).select_from(Violation))).scalar()
        seen["project"] = kw["project"].name
        raise RuntimeError("stop here")

    monkeypatch.setattr(job, "load_report", spy_load_report)
    await job.run_report_job(row.id, factory)
    assert seen == {"violations": 2, "project": "HPCL"}


async def test_auto_report_is_tagged_explicitly(factory, world) -> None:
    from app.services.report.auto import AutoReportScheduler, Occurrence

    occ = Occurrence(day=NOW.date(), shift="A", start=NOW - timedelta(hours=8), end=NOW)
    async with factory() as db:
        # Pass a project that is NOT the default, to prove it is honoured.
        await AutoReportScheduler()._enqueue(db, [occ], NOW, world["hpcl"].id)
        rows = (await db.execute(select(CustomerReport.project_id))).scalars().all()
    assert rows == [world["hpcl"].id]


async def test_violation_export_in_a_past_project(client, factory, world) -> None:
    body = {"filters": {}}
    preview = (await client.post("/api/v1/admin/violation-exports/preview", json=body, headers=past(world))).json()
    assert preview["violations_matching_filters"] == 2

    r = await client.post("/api/v1/admin/violation-exports", json=body, headers=past(world))
    assert r.status_code == 202, r.text
    assert r.json()["project_id"] == str(world["hpcl"].id)
    assert (await _get(factory, ViolationExport, uuid.UUID(r.json()["id"]))).project_id == world["hpcl"].id

    # The build job's session is NOT scoped: the statement it is handed must
    # carry the project itself.
    async with factory() as db:
        rows = (await db.execute(client.captured["stmt"])).scalars().all()
    assert {v.project_id for v in rows} == {world["hpcl"].id} and len(rows) == 2


async def test_training_export_sidecars_name_the_project(factory, world, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.services.false_positive_export import build_sidecar
    from app.services.violation_export import ExportOptions
    from app.services.violation_export_job import resolve_plan

    monkeypatch.setattr(get_settings(), "evidence_frame_dir", str(world["frames"]))
    stmt = select(Violation).where(Violation.project_id == world["hpcl"].id)
    async with factory() as db:
        plan = await resolve_plan(db, stmt, ExportOptions(scope="all", annotated=False, include_snapshots=False))
    assert plan.total == 2
    for p in plan.items:
        assert p.item.project_id == world["hpcl"].id and p.item.project_name == "HPCL"
        sidecar = build_sidecar(p.item, image_name="x.jpg", width=1, height=1)
        assert sidecar["project"] == {"id": str(world["hpcl"].id), "name": "HPCL"}


def _sidecars(root) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(root.rglob("*.json"))]


async def test_dismissal_labels_the_frame_with_the_viewed_project(client, world, tmp_path) -> None:
    """Dismissing an HPCL false positive (by-id, sent with the HPCL view) labels it HPCL."""
    vid = world["hpcl_ids"][0]
    r = await client.patch(
        f"/api/v1/violations/{vid}",
        json={"status": "dismissed", "dismiss_reason": "object", "reviewed_by": "op"},
        headers=past(world),
    )
    assert r.status_code == 200, r.text
    sidecars = _sidecars(tmp_path / "labelling")
    assert len(sidecars) == 1
    assert sidecars[0]["project"] == {"id": str(world["hpcl"].id), "name": "HPCL"}


async def test_bulk_dismissal_in_a_past_project(client, world, tmp_path) -> None:
    r = await client.post(
        "/api/v1/violations/bulk",
        json={"ids": [str(i) for i in world["hpcl_ids"]], "action": "dismiss", "dismiss_reason": "object"},
        headers=past(world),
    )
    assert r.status_code == 200, r.text
    sidecars = _sidecars(tmp_path / "labelling")
    assert len(sidecars) == 2
    assert {s["project"]["id"] for s in sidecars} == {str(world["hpcl"].id)}


async def test_bulk_dismissal_cannot_reach_another_project(client, world) -> None:
    """In HPCL mode, Dev ids are not in scope: nothing of Dev changes."""
    r = await client.post(
        "/api/v1/violations/bulk",
        json={"ids": [str(i) for i in world["dev_ids"]], "action": "dismiss", "dismiss_reason": "object"},
        headers=past(world),
    )
    body = (await client.get("/api/v1/violations", params={"status": "open"})).json()
    assert body["total"] == 3, (r.status_code, r.text)


async def test_scoped_session_hides_other_projects_from_raw_orm_reads(factory, world) -> None:
    async with factory() as db:
        scope_session(db, world["hpcl"].id)
        assert (await db.execute(select(func.count()).select_from(Evidence))).scalar() == 2

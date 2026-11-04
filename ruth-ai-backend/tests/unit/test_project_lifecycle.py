"""Project Stop / Resume / End: plans, allowed transitions, executor, guards.

End is covered here only (never run on the live project): from active, from
stopped, the typed-name confirmation, and that an ended project cannot be
resumed or stopped again.
"""

import uuid
from types import SimpleNamespace

import pytest

from app.services import project_lifecycle as pl
from app.services.inference_reconciler import InferenceReconciler
from app.services.project_lifecycle import (
    CameraState,
    LifecycleError,
    ProjectLifecycleService,
    ProjectNotRunningError,
    check_allowed,
    ensure_running,
    is_running,
    plan_resume,
    plan_stop,
    snapshot_of,
)

DEV_A = str(uuid.uuid4())


def cams():
    """75080 running with inference off; 75081 already disabled; a demo cam."""
    return [
        CameraState("vas-80", "75080", True, "live", DEV_A, intent="off", intent_models=3, live_session=False),
        CameraState("vas-81", "75081", False, None, str(uuid.uuid4()), intent="suspended", intent_models=3),
        CameraState("vas-demo", "DEMO", False, None, None),
    ]


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------


def test_plan_stop_lists_each_change():
    plans = {p.name: p for p in plan_stop(cams())}
    assert plans["75080"].vas_change is True
    assert any("Disable in VAS" in a for a in plans["75080"].actions)
    assert any("kept as is (off, 3 models)" in a for a in plans["75080"].actions)
    assert plans["75081"].vas_change is False
    assert any("stays disabled on Resume" in a for a in plans["75081"].actions)


def test_plan_stop_ends_live_sessions():
    c = CameraState("v", "cam", True, "live", DEV_A, intent="active", intent_models=2, live_session=True)
    assert plan_stop([c])[0].actions[0] == "End the inference session"


def test_plan_resume_restores_exactly_the_snapshot():
    from datetime import datetime, timezone

    snap = snapshot_of(cams(), datetime.now(timezone.utc), "admin")
    after_stop = [CameraState(c.vas_device_id, c.name, False, None, c.device_id, c.intent, c.intent_models)
                  for c in cams()]
    after_stop.append(CameraState("vas-new", "NEW", False, None, None))
    plans = {p.name: p for p in plan_resume(after_stop, snap)}
    assert plans["75080"].vas_change is True
    assert "No inference" in plans["75080"].actions[1]
    assert plans["75081"].vas_change is False
    assert "disabled before Stop" in plans["75081"].actions[0]
    assert "added after Stop" in plans["NEW"].actions[0]


# --------------------------------------------------------------------------
# Allowed transitions (End included)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action, state, ok",
    [
        ("stop", "active", True), ("stop", "stopping", True), ("stop", "stopped", False),
        ("stop", "ended", False), ("resume", "stopped", True), ("resume", "resuming", True),
        ("resume", "active", False), ("resume", "ended", False),
        ("end", "active", True), ("end", "stopping", True), ("end", "stopped", True),
        ("end", "ended", False), ("stop", None, False),
    ],
)
def test_allowed_transitions(action, state, ok):
    kwargs = {"project_name": "HPCL", "confirm_name": "HPCL"}
    if ok:
        check_allowed(action, state, **kwargs)
    else:
        with pytest.raises(LifecycleError):
            check_allowed(action, state, **kwargs)


def test_ended_project_cannot_be_resumed_message():
    with pytest.raises(LifecycleError, match="cannot be resumed"):
        check_allowed("resume", "ended")


@pytest.mark.parametrize("typed", [None, "", "hpcl", "HPCL "])
def test_end_needs_the_exact_name(typed):
    with pytest.raises(LifecycleError) as e:
        check_allowed("end", "active", project_name="HPCL", confirm_name=typed)
    assert e.value.code == "confirmation_mismatch"


# --------------------------------------------------------------------------
# Executor (fake VAS, fake session)
# --------------------------------------------------------------------------


class FakeDB:
    def __init__(self):
        self.commits = 0

    async def execute(self, *_a, **_k):
        return None

    async def commit(self):
        self.commits += 1


class FakeVAS:
    def __init__(self, fail_on=()):
        self.enabled_calls: list[tuple[str, bool]] = []
        self.storage_calls: list[dict] = []
        self.fail_on = set(fail_on)

    async def set_device_enabled(self, vas_id, enabled):
        if vas_id in self.fail_on:
            raise RuntimeError("VAS timeout")
        self.enabled_calls.append((vas_id, enabled))

    async def update_storage_config(self, updates):
        self.storage_calls.append(updates)
        return {"retention_paused": updates.get("retention_paused")}


class FakeStreams:
    def __init__(self):
        self.stopped: list[uuid.UUID] = []

    async def stop_inference(self, device_id):
        self.stopped.append(device_id)


def project(state="active"):
    return SimpleNamespace(
        name="HPCL", state=state, stopped_at=None, stopped_by=None, resumed_at=None,
        resumed_by=None, ended_at=None, ended_by=None, lifecycle_snapshot=None, lifecycle_error=None,
    )


def service(monkeypatch, proj, cameras, vas=None):
    vas = vas or FakeVAS()
    streams = FakeStreams()
    svc = ProjectLifecycleService(FakeDB(), vas, streams)

    async def fake_current(_db):
        return proj

    async def fake_cameras():
        return cameras()

    monkeypatch.setattr(pl, "current_project", fake_current)
    monkeypatch.setattr(svc, "cameras", fake_cameras)
    return svc, vas, streams


async def test_stop_disables_snapshots_pauses_and_keeps_intents(monkeypatch):
    proj = project()
    live = lambda: [CameraState("v1", "cam1", True, "live", DEV_A, "active", 2, live_session=True),
                    CameraState("v2", "cam2", False, None, None)]
    svc, vas, streams = service(monkeypatch, proj, live)
    result = await svc.stop("admin")
    assert result.complete and proj.state == "stopped" and proj.stopped_by == "admin"
    assert vas.enabled_calls == [("v1", False)]  # already-disabled cam2 untouched
    assert vas.storage_calls == [{"retention_paused": True}]
    assert streams.stopped == [uuid.UUID(DEV_A)]  # session ended; no set_off anywhere
    assert {c["vas_device_id"]: c["vas_enabled"] for c in proj.lifecycle_snapshot["cameras"]} == {
        "v1": True, "v2": False}


async def test_failed_stop_stays_stopping_and_a_retry_finishes_it(monkeypatch):
    proj = project()
    state = {"enabled": True}
    cams_now = lambda: [CameraState("v1", "cam1", state["enabled"], None, None)]
    svc, vas, _ = service(monkeypatch, proj, cams_now, FakeVAS(fail_on={"v1"}))
    result = await svc.stop("admin")
    assert not result.complete and proj.state == "stopping" and "cam1" in proj.lifecycle_error
    snapshot = proj.lifecycle_snapshot

    vas.fail_on.clear()
    result = await svc.stop("admin")
    assert result.complete and proj.state == "stopped" and proj.lifecycle_error is None
    assert proj.lifecycle_snapshot is snapshot  # the retry keeps the pre-Stop truth


async def test_resume_reenables_only_snapshot_cameras(monkeypatch):
    from datetime import datetime, timezone

    proj = project("stopped")
    before = [CameraState("v1", "cam1", True, None, None), CameraState("v2", "cam2", False, None, None)]
    proj.lifecycle_snapshot = snapshot_of(before, datetime.now(timezone.utc), "admin")
    now_off = lambda: [CameraState("v1", "cam1", False, None, None), CameraState("v2", "cam2", False, None, None)]
    svc, vas, _ = service(monkeypatch, proj, now_off)
    result = await svc.resume("admin")
    assert result.complete and proj.state == "active" and proj.resumed_by == "admin"
    assert vas.enabled_calls == [("v1", True)]
    assert vas.storage_calls == [{"retention_paused": False}]


async def test_end_from_active(monkeypatch):
    proj = project()
    svc, vas, _ = service(monkeypatch, proj, lambda: [CameraState("v1", "cam1", True, None, None)])
    result = await svc.stop("admin", end=True, confirm_name="HPCL")
    assert result.complete and proj.state == "ended" and proj.ended_by == "admin"
    assert vas.enabled_calls == [("v1", False)]
    assert vas.storage_calls == [{"retention_paused": True}]


async def test_end_from_stopped_changes_no_camera(monkeypatch):
    proj = project("stopped")
    svc, vas, _ = service(monkeypatch, proj, lambda: [CameraState("v1", "cam1", False, None, None)])
    await svc.stop("admin", end=True, confirm_name="HPCL")
    assert proj.state == "ended" and vas.enabled_calls == []


async def test_end_with_wrong_name_changes_nothing(monkeypatch):
    proj = project()
    svc, vas, _ = service(monkeypatch, proj, lambda: [CameraState("v1", "cam1", True, None, None)])
    with pytest.raises(LifecycleError):
        await svc.stop("admin", end=True, confirm_name="hpcl")
    assert proj.state == "active" and vas.enabled_calls == [] and vas.storage_calls == []


async def test_ended_project_cannot_be_resumed_or_stopped(monkeypatch):
    proj = project("ended")
    svc, vas, _ = service(monkeypatch, proj, lambda: [])
    for run in (lambda: svc.resume("admin"), lambda: svc.stop("admin")):
        with pytest.raises(LifecycleError):
            await run()
    assert proj.state == "ended" and vas.enabled_calls == []


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------


@pytest.mark.parametrize("state, running", [
    (None, True), ("active", True), ("stopping", False), ("stopped", False),
    ("resuming", False), ("ended", False),
])
def test_is_running(state, running):
    assert is_running(state) is running


async def test_start_is_refused_while_stopped(monkeypatch):
    async def stopped(_db):
        return "stopped"

    monkeypatch.setattr(pl, "site_state", stopped)
    with pytest.raises(ProjectNotRunningError):
        await ensure_running(FakeDB())


def test_not_running_maps_to_409():
    from app.core.errors import map_domain_exception

    assert map_domain_exception(ProjectNotRunningError("stopped")).http_status == 409


async def test_reconciler_skips_whole_cycle_while_stopped(monkeypatch):
    async def stopped(_db):
        return "stopped"

    monkeypatch.setattr(pl, "site_state", stopped)

    class NoVAS:
        def __getattr__(self, name):
            raise AssertionError(f"VAS touched while stopped: {name}")

    async def factory():
        yield FakeDB()

    rec = InferenceReconciler(factory, lambda db: None, NoVAS())
    out = await rec.reconcile_once()
    assert out.skipped_project == "stopped"


# --------------------------------------------------------------------------
# Evidence while a camera is stopped
# --------------------------------------------------------------------------


class _Rows:
    def __init__(self, first=None, scalar=None):
        self._first, self._scalar = first, scalar

    def first(self):
        return self._first

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self


class _EvidenceDB:
    """Answers queries in order: [no session row, no live session, latest session]."""

    def __init__(self, answers):
        self.answers = list(answers)

    async def execute(self, _stmt):
        return self.answers.pop(0)


async def test_stopped_camera_uses_historical_footage():
    from app.services.evidence_service import EvidenceService

    violation = SimpleNamespace(id=uuid.uuid4(), device_id=uuid.uuid4(), stream_session_id=None)
    svc = EvidenceService(vas_client=None, db=_EvidenceDB([_Rows(first=None)]))
    assert await svc._capture_source(violation) == "historical"
    svc = EvidenceService(vas_client=None, db=_EvidenceDB([_Rows(first=(uuid.uuid4(),))]))
    assert await svc._capture_source(violation) == "live"


async def test_stream_lookup_falls_back_to_latest_session_when_stopped():
    from app.services.evidence_service import EvidenceService

    violation = SimpleNamespace(id=uuid.uuid4(), device_id=uuid.uuid4(), stream_session_id=None)
    latest = SimpleNamespace(vas_stream_id="vas-stream-1")
    db = _EvidenceDB([_Rows(scalar=None), _Rows(first=latest)])
    assert await EvidenceService(vas_client=None, db=db)._resolve_vas_stream_id(violation) == "vas-stream-1"


def test_database_check_constraint_allows_every_state():
    """The first live Stop hit ck_projects_state: keep the two lists equal."""
    import importlib.util
    from pathlib import Path

    from app.models.project import PROJECT_STATES

    path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "2026_11_05_project_states_check.py"
    spec = importlib.util.spec_from_file_location("project_states_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from app.models.project import CURRENT_PROJECT_STATES

    assert set(module.STATES) == set(PROJECT_STATES)
    assert set(module.CURRENT_STATES) == set(CURRENT_PROJECT_STATES)


async def test_reconciler_logs_the_skip_once_per_state_change(monkeypatch):
    import app.services.inference_reconciler as rec_mod

    states = iter(["stopped", "stopped", "stopped", "ended", None])

    async def next_state(_db):
        return next(states)

    logged = []
    monkeypatch.setattr(pl, "site_state", next_state)
    monkeypatch.setattr(rec_mod.logger, "info", lambda event, **kw: logged.append((event, kw)))

    async def factory():
        yield FakeDB()

    rec = InferenceReconciler(factory, lambda db: None, None)
    for _ in range(4):
        await rec.reconcile_once()
    assert [kw.get("project_state") for e, kw in logged] == ["stopped", "ended"]

    # Running again: one "active again" line, then the normal cycle (no intents here).
    async def no_intents(*_a, **_k):
        return SimpleNamespace(all=lambda: [])

    class DB(FakeDB):
        execute = staticmethod(no_intents)

    async def factory2():
        yield DB()

    rec._db_session_factory = factory2
    await rec.reconcile_once()
    assert logged[-1][0] == "Inference reconciler active again"


def test_stop_response_allows_no_session():
    from app.schemas.device import InferenceStopResponse

    r = InferenceStopResponse(session_id=None, device_id=uuid.uuid4(), state="stopped")
    assert r.session_id is None

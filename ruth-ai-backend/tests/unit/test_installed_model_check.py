"""Models that are not installed: refused on entry, never resumed, and seen
when they fail.

On 2026-11-19 a Cameras tab opened before the deploy added the retired
geo_fencing to a camera. The backend accepted it, and it failed on every
frame for 22 minutes while System Health, the tile and the badge all read
fine. These pin the three fixes:

1. one installed-model check (store manifests, plus the unified runtime only
   while UNIFIED_RUNTIME_IN_USE), used by model add, start-inference,
   /ai/inference and bookmark analyses; retired IDs name the replacement;
2. a resume starts only installed models and names the rest;
3. a model failing on every frame shows as failing after 60 s (API, System
   Health).
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.integrations.unified_runtime.client import UnifiedRuntimeError
from app.services import camera_model_status as cms
from app.services import model_availability as ma

STORE = ["hard_hat", "gloves_2", "geofence", "fall_pose"]
ZONE = {"zones": [{"id": "zone_1", "name": "Restricted Zone", "type": "restricted",
                   "points": [[830, 892], [1163, 916], [1247, 1057], [792, 1066]]}]}


@pytest.fixture
def installed(monkeypatch):
    """Configure what is installed: store models, and the unified runtime
    (in use or not; its models, or an exception when asked)."""
    calls = {"unified": 0}

    def apply(store=STORE, in_use=False, unified=()):
        monkeypatch.setattr(ma, "enabled_store_models", lambda: {m: object() for m in store})
        monkeypatch.setattr(ma, "get_unified_runtime_config",
                            lambda: SimpleNamespace(unified_runtime_in_use=in_use))

        async def catalog():
            calls["unified"] += 1
            if isinstance(unified, Exception):
                raise unified
            return [{"model_id": m} for m in unified]

        monkeypatch.setattr(ma, "_refresh_catalog", catalog)
        ma._cache.update(models=None, expires_at=0.0)
        return calls

    yield apply
    ma._cache.update(models=None, expires_at=0.0)


# ---------------------------------------------------------------------------
# 1. The check
# ---------------------------------------------------------------------------


async def test_installed_store_model_passes(installed):
    installed()
    await ma.assert_model_available("hard_hat")


@pytest.mark.parametrize(
    "model_id, replacement",
    [("geo_fencing", "geofence"), ("fall_detection", "fall_pose"), ("ppe_detection", "store PPE models")],
)
async def test_retired_model_names_its_replacement(installed, model_id, replacement):
    installed()
    with pytest.raises(ma.ModelNotAvailableError) as exc:
        await ma.assert_model_available(model_id)
    assert exc.value.code == "model_retired"
    assert replacement in exc.value.replacement and replacement in exc.value.message
    assert exc.value.detail()["error"] == "model_retired"


async def test_retired_model_without_replacement(installed):
    installed()
    with pytest.raises(ma.ModelNotAvailableError) as exc:
        await ma.assert_model_available("tank_overflow_monitoring")
    assert exc.value.code == "model_retired" and exc.value.replacement is None
    assert "no replacement" in exc.value.message


async def test_unknown_model_is_not_installed(installed):
    installed()
    with pytest.raises(ma.ModelNotAvailableError) as exc:
        await ma.assert_model_available("forklift")
    assert exc.value.code == "model_not_installed"
    assert exc.value.detail() == {"error": "model_not_installed", "message": "forklift is not installed",
                                  "model_id": "forklift"}


async def test_unified_runtime_not_asked_when_not_in_use(installed):
    calls = installed(in_use=False, unified=["geo_fencing"])
    with pytest.raises(ma.ModelNotAvailableError):
        await ma.assert_model_available("geo_fencing")
    assert calls["unified"] == 0


async def test_unified_runtime_models_count_while_in_use(installed):
    """Rollback: built-ins back on the unified runtime are installed again."""
    installed(in_use=True, unified=["geo_fencing"])
    await ma.assert_model_available("geo_fencing")


async def test_store_model_does_not_need_the_unified_runtime(installed):
    calls = installed(in_use=True, unified=UnifiedRuntimeError("down"))
    await ma.assert_model_available("geofence")
    assert calls["unified"] == 0


async def test_unreachable_unified_runtime_in_use_cannot_decide(installed):
    installed(in_use=True, unified=UnifiedRuntimeError("down"))
    with pytest.raises(UnifiedRuntimeError):
        await ma.assert_model_available("geo_fencing")


async def test_unavailable_models_lists_only_the_missing(installed):
    installed()
    missing = await ma.unavailable_models(["hard_hat", "geo_fencing", "forklift"])
    assert {m: e.code for m, e in missing.items()} == {"geo_fencing": "model_retired",
                                                       "forklift": "model_not_installed"}


async def test_unavailable_models_never_raises_on_a_runtime_blip(installed):
    installed(in_use=True, unified=UnifiedRuntimeError("down"))
    assert await ma.unavailable_models(["hard_hat", "geo_fencing"]) == {}


async def test_unreadable_store_installs_nothing(monkeypatch, installed):
    installed()

    def boom():
        raise OSError("store unreadable")

    monkeypatch.setattr(ma, "enabled_store_models", boom)
    with pytest.raises(ma.ModelNotAvailableError):
        await ma.assert_model_available("hard_hat")


# ---------------------------------------------------------------------------
# 1. The endpoints
# ---------------------------------------------------------------------------


class _NeverCalled:
    def __init__(self, *a, **kw):
        raise AssertionError("must not get this far")


async def test_stale_tab_adding_a_retired_model_is_refused(installed, monkeypatch):
    """The 19:59 request, replayed: the retired geo_fencing with a pixel zone."""
    from app.api.v1 import device_models

    installed()
    monkeypatch.setattr(device_models, "SessionModelsService", _NeverCalled)
    body = device_models.ModelEntryIn(model_id="geo_fencing", config=ZONE)
    with pytest.raises(HTTPException) as exc:
        await device_models.add_model(uuid4(), body, SimpleNamespace(status_code=None), None, None)
    assert exc.value.status_code == 422
    assert exc.value.detail == {
        "error": "model_retired", "message": "geo_fencing is retired; use geofence",
        "model_id": "geo_fencing", "replacement": "geofence",
    }


async def test_adding_an_installed_model_reaches_the_session(installed, monkeypatch):
    from app.api.v1 import device_models

    installed()
    added = []

    class FakeService:
        def __init__(self, *_a):
            pass

        async def add(self, device_id, entry):
            added.append(entry["model_id"])
            return SimpleNamespace(session=None, changed=True)

    class FakeDB:
        async def commit(self):
            pass

    async def out(device_id, session, db):
        return "out"

    async def no_cache(*_k):
        pass

    monkeypatch.setattr(device_models, "SessionModelsService", FakeService)
    monkeypatch.setattr(device_models, "_out", out)
    monkeypatch.setattr(device_models, "cache_delete", no_cache)
    body = device_models.ModelEntryIn(model_id="hard_hat")
    response = SimpleNamespace(status_code=None)
    assert await device_models.add_model(uuid4(), body, response, None, FakeDB()) == "out"
    assert added == ["hard_hat"] and response.status_code == 201


async def test_start_inference_refuses_a_retired_model(installed):
    from app.api.v1 import devices
    from app.schemas.device import InferenceStartRequest

    installed()

    class NoStreams:
        def __getattr__(self, name):
            raise AssertionError("must not touch the stream service")

    with pytest.raises(HTTPException) as exc:
        await devices.start_inference(uuid4(), NoStreams(), None, InferenceStartRequest(model_id="ppe_detection"))
    assert exc.value.status_code == 422 and exc.value.detail["error"] == "model_retired"


async def test_ai_inference_refuses_with_422_not_500(installed, monkeypatch):
    from app.api.v1 import ai

    installed()
    monkeypatch.setattr(ai, "UnifiedRuntimeClient", _NeverCalled)
    with pytest.raises(HTTPException) as exc:
        await ai.submit_inference(ai.InferenceRequest(model_id="geo_fencing", frame="QUJD"))
    assert exc.value.status_code == 422 and exc.value.detail["replacement"] == "geofence"


async def test_endpoint_503_when_the_check_cannot_be_decided(installed, monkeypatch):
    from app.api.v1 import ai

    installed(in_use=True, unified=UnifiedRuntimeError("down"))
    monkeypatch.setattr(ai, "UnifiedRuntimeClient", _NeverCalled)
    with pytest.raises(HTTPException) as exc:
        await ai.submit_inference(ai.InferenceRequest(model_id="geo_fencing", frame="QUJD"))
    assert exc.value.status_code == 503 and exc.value.detail["error"] == "ai_runtime_unreachable"


TANK = {"tank_corners": [[0, 0], [10, 0], [10, 10], [0, 10]]}


def _fake_submit(api, monkeypatch):
    submitted, scheduled = [], []

    class FakeService:
        def __init__(self, db):
            pass

        async def submit(self, request):
            submitted.append(request.model_id)
            return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(api, "BookmarkAnalysisService", FakeService)
    monkeypatch.setattr(api, "BookmarkAnalysisResponse", SimpleNamespace(model_validate=lambda a: a))
    return submitted, scheduled, SimpleNamespace(add_task=lambda fn, *a: scheduled.append(fn))


async def test_bookmark_analysis_accepts_an_installed_fill_level_model(installed, monkeypatch):
    """The check no longer asks only the unified runtime (which refused every
    model once the built-ins were retired): an installed fill-level model,
    here the tank model back on the unified runtime, is accepted."""
    from app.api.v1 import bookmark_analyses as api
    from app.schemas.bookmark_analysis import BookmarkAnalysisSubmitRequest

    installed(in_use=True, unified=["tank_overflow_monitoring"])
    submitted, scheduled, tasks = _fake_submit(api, monkeypatch)
    request = BookmarkAnalysisSubmitRequest(vas_bookmark_id="bm-1", model_id="tank_overflow_monitoring",
                                            parameters=TANK)
    await api.submit_analysis(request, None, tasks)
    assert submitted == ["tank_overflow_monitoring"] and scheduled == [api.run_analysis]


async def test_bookmark_analysis_refuses_a_store_model_it_cannot_summarise(installed, monkeypatch):
    """Option B: an installed store detection model reports no fill level, so
    it is refused up front instead of running to "no fill data" (BL-38)."""
    from app.api.v1 import bookmark_analyses as api
    from app.schemas.bookmark_analysis import BookmarkAnalysisSubmitRequest

    installed()
    monkeypatch.setattr(api, "BookmarkAnalysisService", _NeverCalled)
    request = BookmarkAnalysisSubmitRequest(vas_bookmark_id="bm-1", model_id="hard_hat")
    with pytest.raises(HTTPException) as exc:
        await api.submit_analysis(request, None, None)
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "model_not_supported"
    assert "hard_hat does not report one" in exc.value.detail["message"]


async def test_bookmark_analysis_refuses_a_retired_model(installed, monkeypatch):
    from app.api.v1 import bookmark_analyses as api
    from app.schemas.bookmark_analysis import BookmarkAnalysisSubmitRequest

    installed()
    monkeypatch.setattr(api, "BookmarkAnalysisService", _NeverCalled)
    request = BookmarkAnalysisSubmitRequest(
        vas_bookmark_id="bm-1", model_id="tank_overflow_monitoring", parameters=TANK,
    )
    with pytest.raises(HTTPException) as exc:
        await api.submit_analysis(request, None, None)
    assert exc.value.status_code == 422 and exc.value.detail["error"] == "model_retired"


async def test_bookmark_analysis_runs_a_store_model_on_the_store_runtime(monkeypatch, tmp_path):
    """The worker sends a store model to the store runtime (it sent every
    model to the unified runtime). Submit refuses non-fill-level models; this
    pins the routing for when one is (BL-38)."""
    from app.api.v1 import ai
    from app.services import bookmark_analysis_worker as worker

    store_url = "http://model-store-runtime:8000"
    monkeypatch.setattr(ai, "get_unified_runtime_config", lambda: SimpleNamespace(model_store_runtime_url=store_url))
    monkeypatch.setattr(ai, "enabled_store_models", lambda: {"hard_hat": object()})

    class FakeDownload:
        async def aiter_bytes(self, chunk_size):
            yield b"video"

    class FakeVAS:
        @asynccontextmanager
        async def download_bookmark_video(self, _id):
            yield FakeDownload()

    seen = {"urls": [], "models": []}

    class FakeRuntime:
        def __init__(self, runtime_url=None):
            seen["urls"].append(runtime_url)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def submit_inference(self, **kw):
            seen["models"].append(kw["model_id"])
            return SimpleNamespace(status="success", result={"violation_detected": False}, error=None)

    monkeypatch.setattr(worker, "get_vas_client_optional", lambda: FakeVAS())
    monkeypatch.setattr(worker, "_extract_frames_list", lambda path, fps: [(0.0, b"jpg"), (1.0, b"jpg")])
    monkeypatch.setattr(worker, "UnifiedRuntimeClient", FakeRuntime)
    with pytest.raises(RuntimeError, match="no fill data"):
        await worker._run_pipeline(analysis_id=uuid4(), vas_bookmark_id="bm-1", model_id="hard_hat",
                                   model_version=None, parameters={}, temp_video=tmp_path / "v.mp4")
    assert seen == {"urls": [store_url], "models": ["hard_hat", "hard_hat"]}


# ---------------------------------------------------------------------------
# 2. Resume starts only installed models
# ---------------------------------------------------------------------------


async def _reconciler_with(monkeypatch, models, missing_ids, running=()):
    from tests.unit import test_inference_reconciler as rt

    async def no_project(_db):
        return None

    async def missing(ids):
        return {m: ma.not_installed_error(m) for m in ids if m in missing_ids}

    monkeypatch.setattr("app.services.project_lifecycle.site_state", no_project)
    monkeypatch.setattr("app.services.inference_reconciler.unavailable_models", missing)
    d = rt.device()
    i = rt.intent(device_id=d.id, models=[{"model_id": m, "model_version": None, "config": None} for m in models])
    rec, db, streams = rt.build([(i, d)], running=[d.id] if running else [])
    return rec, i, streams


async def test_resume_starts_only_installed_models(monkeypatch):
    saved = ["geo_fencing", "hard_hat", "gloves_2"]
    rec, i, streams = await _reconciler_with(monkeypatch, saved, {"geo_fencing"})
    out = await rec.reconcile_once()
    assert out.resumed == ["75096"]
    (_device, kw), = streams.started
    assert kw["model_id"] == "hard_hat"  # the first installed model, not the retired one
    assert i.models == [{"model_id": m, "model_version": None, "config": None} for m in saved]  # untouched
    assert i.consecutive_failures == 0
    assert i.last_error == "Not started, not installed: geo_fencing is retired; use geofence"
    assert out.left_out == ["75096: geo_fencing"]


async def test_resume_with_nothing_installed_fails_and_counts(monkeypatch):
    rec, i, streams = await _reconciler_with(monkeypatch, ["ppe_detection"], {"ppe_detection"})
    out = await rec.reconcile_once()
    assert streams.started == [] and out.failed == ["75096"]
    assert i.consecutive_failures == 1
    assert "none of the saved models is installed: ppe_detection" in i.last_error


async def test_running_camera_keeps_naming_its_missing_model(monkeypatch):
    rec, i, streams = await _reconciler_with(monkeypatch, ["hard_hat", "geo_fencing"], {"geo_fencing"}, running=True)
    out = await rec.reconcile_once()
    assert streams.started == []
    assert i.last_error == "Not started, not installed: geo_fencing is retired; use geofence"
    assert out.left_out == ["75096: geo_fencing"]


async def test_running_camera_note_clears_once_installed(monkeypatch):
    rec, i, _streams = await _reconciler_with(monkeypatch, ["hard_hat", "geo_fencing"], set(), running=True)
    i.last_error = "Not started, not installed: geo_fencing is retired; use geofence"
    await rec.reconcile_once()
    assert i.last_error is None


async def test_resume_with_everything_installed_is_unchanged(monkeypatch):
    rec, i, streams = await _reconciler_with(monkeypatch, ["hard_hat", "gloves_2"], set())
    await rec.reconcile_once()
    assert streams.started[0][1]["model_id"] == "hard_hat" and i.last_error is None


# ---------------------------------------------------------------------------
# 3. Failing models
# ---------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _tracker():
    clock = Clock()
    return cms.CameraModelTracker(clock=clock), clock


def test_a_failure_is_not_failing_for_60_seconds():
    t, clock = _tracker()
    d = uuid4()
    t.record_failure(d, "geo_fencing", "Model not found: geo_fencing:latest")
    clock.t += 59
    assert t.health(d, "geo_fencing").status == "running"
    clock.t += 1
    h = t.health(d, "geo_fencing")
    assert (h.status, h.last_error, h.errors) == ("failing", "Model not found: geo_fencing:latest", 1)


def test_a_success_resets_the_clock():
    t, clock = _tracker()
    d = uuid4()
    t.record_failure(d, "hard_hat", "timeout")
    clock.t += 50
    t.record_success(d, "hard_hat")
    clock.t += 50
    t.record_failure(d, "hard_hat", "timeout")
    clock.t += 30
    assert t.health(d, "hard_hat").status == "running"


def test_failures_count_until_a_success():
    t, clock = _tracker()
    d = uuid4()
    for _ in range(5):
        t.record_failure(d, "m", "boom")
        clock.t += 15
    assert t.health(d, "m").errors == 5 and t.health(d, "m").status == "failing"
    assert t.health(uuid4(), "m").status == "running"  # another camera is unaffected


async def test_loop_reports_each_model_outcome(monkeypatch):
    from unittest.mock import MagicMock

    from app.services import inference_loop as il

    t, clock = _tracker()
    monkeypatch.setattr(il, "model_status_tracker", t)
    loop = il.InferenceLoopService(runtime_router=MagicMock(), vas_client=MagicMock(), db_session_factory=MagicMock())

    async def run_model(session_id, device_id, vas_stream_id, entry, frame, fetch_seconds):
        if entry["model_id"] == "geo_fencing":
            raise RuntimeError("Model not found: geo_fencing:latest")
        if entry["model_id"] == "empty":
            return {"status": "error", "error": "bad frame"}
        return {"status": "success", "result": {"violation_detected": False}}

    monkeypatch.setattr(loop, "_run_model", run_model)
    monkeypatch.setattr(loop, "_publish_model_result", lambda d, m, p, r: r.get("status") == "success")

    async def no_rules(*a):
        return None

    monkeypatch.setattr(loop, "_apply_violation_rules", no_rules)
    d = uuid4()
    due = [{"model_id": m} for m in ("hard_hat", "geo_fencing", "empty")]
    await loop._run_tick_models(uuid4(), d, str(uuid4()), due, "hard_hat", b"f", 0.0, 0.7)
    clock.t += 60
    assert t.health(d, "hard_hat").status == "running"
    assert t.health(d, "geo_fencing").status == "failing"
    assert t.health(d, "empty").last_error == "bad frame"


def _cam(session_models=(), intent_models=()):
    return cms._Camera(uuid4(), "THILAKCABIN_OUT_DEMO-CAMERA", list(session_models), list(intent_models))


async def _statuses(monkeypatch, cams, missing_ids, t=None):
    async def cameras(db, device_id=None):
        return cams

    async def missing(ids):
        return {m: ma.not_installed_error(m) for m in ids if m in missing_ids}

    monkeypatch.setattr(cms, "_cameras", cameras)
    monkeypatch.setattr(cms, "unavailable_models", missing)
    return await cms.camera_model_statuses(None, model_tracker=t or _tracker()[0])


async def test_statuses_running_failing_unavailable(monkeypatch):
    t, clock = _tracker()
    cam = _cam(["gloves_2", "fall_pose", "geo_fencing"], ["gloves_2", "fall_pose", "geo_fencing"])
    t.record_failure(cam.device_id, "fall_pose", "timeout")
    clock.t += 61
    got = {s.model_id: s for s in await _statuses(monkeypatch, [cam], {"geo_fencing"}, t)}
    assert got["gloves_2"].status == "running"
    assert got["fall_pose"].status == "failing" and got["fall_pose"].reason == "inference_failing"
    assert "timeout" in got["fall_pose"].message
    # Not installed is known at once: no 60 s wait.
    assert got["geo_fencing"].status == "unavailable" and got["geo_fencing"].reason == "model_retired"
    assert got["geo_fencing"].replacement == "geofence" and got["geo_fencing"].in_session is True


async def test_statuses_include_saved_models_a_resume_left_out(monkeypatch):
    cam = _cam(["hard_hat"], ["hard_hat", "ppe_detection", "gloves_2"])
    got = await _statuses(monkeypatch, [cam], {"ppe_detection"})
    assert [(s.model_id, s.status, s.in_session) for s in got] == [
        ("hard_hat", "running", True), ("ppe_detection", "unavailable", False)]


async def test_health_camera_models_healthy_and_degraded(monkeypatch):
    from app.core import database
    from app.services.health_service import HealthService

    @asynccontextmanager
    async def session():
        yield None

    monkeypatch.setattr(database, "get_session_factory", lambda: session)
    rows = []

    async def statuses(db):
        return rows

    monkeypatch.setattr(cms, "camera_model_statuses", statuses)
    d = uuid4()
    rows[:] = [cms.CameraModelStatus(d, "CAM", "hard_hat", "running", True)]
    ok = await HealthService().check_camera_models()
    assert ok.status == "healthy" and ok.details["models"] == 1 and ok.details["problems"] == []

    rows.append(cms.CameraModelStatus(d, "CAM", "geo_fencing", "unavailable", True, "model_retired",
                                      "geo_fencing is retired; use geofence", "geofence"))
    bad = await HealthService().check_camera_models()
    assert bad.status == "degraded" and bad.details["unavailable"] == 1
    assert bad.error == "CAM: geo_fencing unavailable: geo_fencing is retired; use geofence"
    assert bad.details["problems"][0]["replacement"] == "geofence"


async def test_health_overall_degraded_by_a_failing_camera_model():
    from app.schemas.health import ComponentHealth
    from app.services.health_service import HealthService

    components = {"database": ComponentHealth(status="healthy"),
                  "ai_runtime": ComponentHealth(status="disabled"),
                  "camera_models": ComponentHealth(status="degraded")}
    assert HealthService().determine_overall_status(components) == "degraded"


async def test_device_models_api_reports_status_and_not_started(monkeypatch):
    from app.api.v1 import device_models
    from app.services import inference_intent

    d = uuid4()
    session = SimpleNamespace(id=uuid4(), models_revision=3, models=[
        {"model_id": "hard_hat", "model_version": None, "config": None, "fps_override": None},
        {"model_id": "geofence", "model_version": None, "config": ZONE, "fps_override": None},
    ])
    since = datetime.now(timezone.utc) - timedelta(minutes=2)

    async def statuses(db, device_id=None):
        return [
            cms.CameraModelStatus(d, "CAM", "hard_hat", "running", True),
            cms.CameraModelStatus(d, "CAM", "geofence", "failing", True, "inference_failing",
                                  "No result for 2 min 0 s: timeout", failing_since=since, errors=8),
            cms.CameraModelStatus(d, "CAM", "geo_fencing", "unavailable", False, "model_retired",
                                  "geo_fencing is retired; use geofence", "geofence"),
        ]

    class FakeIntents:
        def __init__(self, db):
            pass

        async def get(self, device_id):
            return SimpleNamespace(models=session.models + [{"model_id": "geo_fencing", "config": ZONE}])

    monkeypatch.setattr(cms, "camera_model_statuses", statuses)
    monkeypatch.setattr(inference_intent, "InferenceIntentService", FakeIntents)
    out = await device_models._out(d, session, None)
    assert [(m.model_id, m.status) for m in out.models] == [("hard_hat", "running"), ("geofence", "failing")]
    assert out.models[1].failing_since == since and out.models[1].reason == "inference_failing"
    assert [(m.model_id, m.status, m.replacement) for m in out.not_started] == [
        ("geo_fencing", "unavailable", "geofence")]


# ---------------------------------------------------------------------------
# Saved models a resume left out survive operator edits; Remove deletes them
# ---------------------------------------------------------------------------


class _Intents:
    def __init__(self, models):
        self.intent = SimpleNamespace(models=models, desired_state="active", updated_at=None, updated_by=None)
        self.set_active_with = None
        self.off = False

    async def get(self, device_id):
        return self.intent

    async def set_active(self, device_id, models, **kw):
        self.set_active_with = models

    async def set_off(self, device_id, **kw):
        self.off = True


async def test_operator_edit_carries_forward_a_saved_unavailable_model(monkeypatch):
    from app.services.session_models import SessionModelsService

    async def missing(ids):
        return {m: ma.not_installed_error(m) for m in ids if m == "geo_fencing"}

    monkeypatch.setattr(ma, "unavailable_models", missing)
    intents = _Intents([{"model_id": "hard_hat"}, {"model_id": "geo_fencing", "config": ZONE}])
    svc = SessionModelsService(None, None)
    kept = await svc._with_saved_unavailable(intents, uuid4(), [{"model_id": "hard_hat"}, {"model_id": "gloves_2"}])
    assert [e["model_id"] for e in kept] == ["hard_hat", "gloves_2", "geo_fencing"]
    assert kept[2]["config"] == ZONE


async def test_remove_deletes_a_saved_only_model(monkeypatch):
    from app.services import inference_intent
    from app.services.session_models import SessionModelsService

    intents = _Intents([{"model_id": "hard_hat"}, {"model_id": "geo_fencing"}])
    monkeypatch.setattr(inference_intent, "InferenceIntentService", lambda db: intents)

    class DB:
        async def flush(self):
            pass

    svc = SessionModelsService(None, DB())
    assert await svc._remove_saved(uuid4(), "geo_fencing") is True
    assert intents.intent.models == [{"model_id": "hard_hat"}]
    assert await svc._remove_saved(uuid4(), "forklift") is False

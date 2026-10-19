"""Model store runtime integration (Step 5, pieces 1-2).

Built-in models must route, list and report health exactly as before; store
models go to the store runtime and are appended after the built-ins.
No database or runtime needed: both are faked.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.v1 import device_models as device_models_api
from app.api.v1 import models as models_api
from app.integrations.unified_runtime import client as runtime_client
from app.integrations.unified_runtime import config as runtime_config
from app.integrations.unified_runtime.frame_fetcher import FrameData
from app.integrations.unified_runtime.router import RuntimeRouter
from app.integrations.unified_runtime.store_router import StoreAwareRouter
from app.models.enums import ViolationType, resolve_violation_type
from app.schemas import ModelsStatusResponse
from app.services.model_store import enabled as enabled_mod
from app.services.model_store import runtime_probe
from app.services.model_store.enabled import StoreModelInfo, read_enabled_models

BUILTIN_CAPS = {
    "models": [
        {"model_id": "fall_detection", "version": "1.0.0", "state": "ready", "health": "healthy"},
        {"model_id": "ppe_detection", "version": "1.0.0", "state": "ready", "health": "healthy"},
        {"model_id": "geo_fencing", "version": "1.0.0", "state": "loading", "health": "unknown"},
        {"model_id": "test_dummy", "version": "1.0.0", "state": "ready", "health": "healthy"},
    ]
}
STORE_CAPS = {
    "models": [
        {"model_id": "hard_hat", "version": "1.0.0", "state": "ready", "health": "healthy"},
        {"model_id": "safety_vest", "version": "1.0.0", "state": "ready", "health": "healthy"},
        {"model_id": "gloves", "version": "1.0.0", "state": "failed", "health": "unhealthy"},
        {"model_id": "ppe_detection", "version": "9.9.9", "state": "ready", "health": "healthy"},
        {"model_id": "not_installed", "version": "1.0.0", "state": "ready", "health": "healthy"},
    ]
}
BUILTIN_URL = "http://unified-ai-runtime:8000"
STORE_URL = "http://model-store-runtime:8000"


class FakeClient:
    """Stands in for UnifiedRuntimeClient; records inference calls."""

    def __init__(self, name, caps=None, fail=False):
        self.name, self.caps, self.fail = name, caps or {"models": []}, fail
        self.capability_calls = 0
        self.inferred = []

    async def get_capabilities(self):
        self.capability_calls += 1
        if self.fail:
            raise ConnectionError("down")
        return self.caps

    async def submit_inference(self, model_id, **kwargs):
        self.inferred.append(model_id)
        return SimpleNamespace(
            request_id=uuid.uuid4(), status="success", model_id=model_id, model_version="1.0.0",
            inference_time_ms=1.0, result={"violation_detected": False}, error=None,
        )


FRAME = FrameData(base64_data="AAAA", format="jpeg", width=1280, height=720, size_bytes=3)


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


async def test_default_router_sends_everything_to_the_one_runtime():
    builtin = FakeClient("builtin")
    router = RuntimeRouter(vas_client=None, unified_runtime_client=builtin)
    assert await router.client_for("hard_hat") is builtin
    await router.submit_inference_with_frame(model_id="fall_detection", frame_data=FRAME, stream_id=uuid.uuid4())
    assert builtin.inferred == ["fall_detection"]


async def test_store_router_routes_store_ids_and_never_builtins():
    builtin, store = FakeClient("builtin"), FakeClient("store", STORE_CAPS)
    router = StoreAwareRouter(vas_client=None, unified_runtime_client=builtin, store_runtime_client=store)
    for model_id in ("hard_hat", "safety_vest", "gloves", "not_installed"):
        assert await router.client_for(model_id) is store
    # reserved built-in ids stay on the built-in runtime even if the store reports them
    for model_id in ("fall_detection", "ppe_detection", "geo_fencing", "chane_tank_monitor"):
        assert await router.client_for(model_id) is builtin
    # ids neither runtime knows keep today's behaviour (built-in runtime -> 404 there)
    assert await router.client_for("something_else") is builtin

    stream = uuid.uuid4()
    for model_id in ("fall_detection", "hard_hat", "gloves"):
        await router.submit_inference_with_frame(model_id=model_id, frame_data=FRAME, stream_id=stream)
    assert builtin.inferred == ["fall_detection"]
    assert store.inferred == ["hard_hat", "gloves"]
    assert store.capability_calls == 1  # cached between calls


async def test_store_lookup_failure_keeps_last_known_set(monkeypatch):
    builtin, store = FakeClient("builtin"), FakeClient("store", STORE_CAPS)
    router = StoreAwareRouter(vas_client=None, unified_runtime_client=builtin,
                              store_runtime_client=store, refresh_seconds=0)
    assert await router.client_for("hard_hat") is store
    store.fail = True  # store runtime restarting for an Apply
    assert await router.client_for("hard_hat") is store


async def test_store_down_from_the_start_delegates_to_builtin():
    builtin, store = FakeClient("builtin"), FakeClient("store", fail=True)
    router = StoreAwareRouter(vas_client=None, unified_runtime_client=builtin, store_runtime_client=store)
    assert await router.client_for("hard_hat") is builtin
    assert await router.client_for("fall_detection") is builtin


# --------------------------------------------------------------------------
# /models/status
# --------------------------------------------------------------------------


class FakeDB:
    """Minimal async session double for /models/status.

    The route issues two shapes of query: scalar counts (active cameras,
    last inference) and, since the inference-rate summary was added, a
    row fetch via .all(). Both are stubbed empty — these tests are about
    how store models are merged into the response, not about rates, and
    an empty rate summary is the correct result for "no live sessions".
    """

    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(scalar=lambda: None, all=lambda: [])


INSTALLED = {
    "hard_hat": StoreModelInfo("hard_hat", "1.0.0", "Hard Hat", (), False, True),
    "safety_vest": StoreModelInfo("safety_vest", "1.0.0", "Safety Vest", (), False, True),
    "gloves": StoreModelInfo("gloves", "1.0.0", "Gloves", (), False, True),
}


@pytest.fixture
def status_env(monkeypatch):
    def client_factory(runtime_url=None, timeout=None):
        url = runtime_url or BUILTIN_URL
        caps = STORE_CAPS if url == STORE_URL else BUILTIN_CAPS
        client = FakeClient(url, caps, fail=getattr(client_factory, "store_down", False) and url == STORE_URL)

        class Ctx:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, *exc):
                return False

        return Ctx()

    monkeypatch.setattr(models_api, "UnifiedRuntimeClient", client_factory)
    monkeypatch.setattr(models_api, "enabled_store_models", lambda: INSTALLED)
    # The store path now goes through runtime_probe, which resolves the
    # client and config from their own modules at call time, so patch those
    # too. The built-in path still uses the models_api attributes above.
    monkeypatch.setattr(runtime_client, "UnifiedRuntimeClient", client_factory)

    def run(store_url="", store_down=False):
        client_factory.store_down = store_down
        cfg = runtime_config.UnifiedRuntimeConfig(MODEL_STORE_RUNTIME_URL=store_url)
        monkeypatch.setattr(models_api, "get_unified_runtime_config", lambda: cfg)
        monkeypatch.setattr(runtime_config, "get_unified_runtime_config", lambda: cfg)
        # The probe caches for PROBE_TTL_SECONDS and remembers reachability
        # across calls; without this, one test's store state leaks into the
        # next and the transition logging asserts nothing.
        runtime_probe.reset_probe_state()
        return cfg

    return run


def as_json(response):
    """What the route sends (response_model_exclude_unset=True)."""
    return json.loads(ModelsStatusResponse.model_validate(response).model_dump_json(exclude_unset=True))


ORIGINAL_FIELDS = {"model_id", "version", "status", "health", "cameras_active", "last_inference_at", "started_at"}


async def test_builtin_entries_identical_with_store_off_on_and_down(status_env):
    status_env("")
    off = as_json(await models_api.get_models_status(FakeDB()))
    status_env(STORE_URL)
    on = as_json(await models_api.get_models_status(FakeDB()))
    status_env(STORE_URL, store_down=True)
    down = as_json(await models_api.get_models_status(FakeDB()))

    assert [m["model_id"] for m in off["models"]] == ["fall_detection", "ppe_detection", "geo_fencing"]
    for entry in off["models"]:
        assert set(entry) == ORIGINAL_FIELDS  # no new keys, not even as null
    assert on["models"][:3] == off["models"]

    # The built-in entries are still byte-identical when the store is down —
    # a broken store can never degrade the built-in list.
    assert down["models"] == off["models"]

    # But the RESPONSE is no longer identical, deliberately. `down == off`
    # used to hold, and that was the silent failure encoded as a
    # requirement: a store that was configured-but-broken looked exactly
    # like no store at all, which is how it went unnoticed for twelve days.
    assert "store_runtime" not in off  # unconfigured: field omitted entirely
    assert down["store_runtime"]["reachable"] is False
    assert down["store_runtime"]["error"]
    assert on["store_runtime"]["reachable"] is True


async def test_store_entries_appended_with_their_fields(status_env):
    status_env(STORE_URL)
    out = as_json(await models_api.get_models_status(FakeDB()))
    store = out["models"][3:]
    # ppe_detection from the store runtime is a built-in id: skipped;
    # not_installed isn't in enabled/: skipped
    assert [m["model_id"] for m in store] == ["hard_hat", "safety_vest", "gloves"]
    hard_hat = store[0]
    assert hard_hat["source"] == "store" and hard_hat["display_name"] == "Hard Hat"
    assert hard_hat["status"] == "idle" and hard_hat["health"] == "healthy"
    assert hard_hat["reports_ppe"] is True and hard_hat["all_rules_need_zone"] is False
    assert (store[2]["status"], store[2]["health"]) == ("error", "unhealthy")


async def test_store_camera_count_includes_multi_model_sessions(status_env):
    status_env(STORE_URL)
    db = FakeDB()
    await models_api.get_models_status(db)
    sql = str(db.statements[-2].compile(dialect=postgresql.dialect()))
    assert "stream_sessions.models @>" in sql and "stream_sessions.model_id =" in sql


# --------------------------------------------------------------------------
# Enabled manifests, zone gate, violation type
# --------------------------------------------------------------------------


def write_manifest(root, model_id, rules, version="1.0.0"):
    d = root / model_id / version
    d.mkdir(parents=True)
    (d / "store_manifest.json").write_text(json.dumps({"model_id": model_id, "display_name": model_id.title(), "rules": rules}))


def test_read_enabled_models(tmp_path):
    write_manifest(tmp_path, "hard_hat", [{"id": "r", "violation_type": "missing_hardhat"}])
    write_manifest(tmp_path, "harness", [
        {"id": "a", "violation_type": "missing_harness", "requires_zone": "work_at_height"},
    ])
    write_manifest(tmp_path, "harness", [{"id": "b", "violation_type": "x"}], version="0.9.0")
    # A genuinely non-PPE model, for the reports_ppe=False branch. This used
    # to be `harness`, which worked only because `missing_harness` was
    # unmapped; it is now a real PPE type, so the branch needed its own case.
    write_manifest(tmp_path, "fencing", [{"id": "z", "violation_type": "zone_intrusion"}])
    (tmp_path / "broken" / "1.0.0").mkdir(parents=True)
    (tmp_path / "broken" / "1.0.0" / "store_manifest.json").write_text("{not json")

    models = read_enabled_models(tmp_path)
    assert set(models) == {"hard_hat", "harness", "fencing"}
    assert models["hard_hat"].reports_ppe is True
    assert models["harness"].version == "1.0.0"
    assert models["harness"].all_rules_need_zone is True
    assert models["harness"].zone_required_rules == ("a",)
    assert models["harness"].reports_ppe is True  # missing_harness is PPE
    assert models["fencing"].reports_ppe is False
    assert read_enabled_models(tmp_path / "missing") == {}


async def test_zone_gate_refuses_store_models_that_need_a_zone(monkeypatch):
    info = StoreModelInfo("harness", "1.0.0", "Harness", ("missing_harness",), True, False)
    monkeypatch.setattr(device_models_api, "enabled_store_models", lambda: {"harness": info})
    body = device_models_api.ModelEntryIn(model_id="harness")
    with pytest.raises(HTTPException) as exc:
        await device_models_api.add_model(uuid.uuid4(), body, None, None, None)
    assert exc.value.status_code == 422 and exc.value.detail["error"] == "zone_required"


def test_missing_gloves_is_ppe_without_warning_fallback():
    assert resolve_violation_type("missing_gloves") == (ViolationType.PPE_VIOLATION, "missing_gloves")


# --------------------------------------------------------------------------
# System health ignores the store runtime
# --------------------------------------------------------------------------


async def test_health_uses_builtin_runtime_not_store(monkeypatch):
    from app.api.internal import ai_runtime
    from app.services.health_service import HealthService

    def reg(rid, health, models):
        return ai_runtime.RuntimeRegistration(runtime_id=rid, runtime_health=health,
                                              models=[{"model_id": m} for m in models], capacity={}, summary={})

    registry = {
        "model-store-runtime": reg("model-store-runtime", "unhealthy", []),
        "unified-runtime-abc": reg("unified-runtime-abc", "healthy", ["fall_detection"]),
    }
    monkeypatch.setattr(ai_runtime, "_registered_runtimes", registry)
    result = await HealthService().check_ai_runtime()
    assert result.status == "healthy"
    assert result.details["runtime_id"] == "unified-runtime-abc"

    monkeypatch.setattr(ai_runtime, "_registered_runtimes", {"model-store-runtime": registry["model-store-runtime"]})
    assert (await HealthService().check_ai_runtime()).status == "unhealthy"


# --------------------------------------------------------------------------
# Store runtime visibility (the twelve-day silent failure)
# --------------------------------------------------------------------------


async def test_models_status_reports_store_reachable_with_counts(status_env):
    status_env(STORE_URL)
    out = as_json(await models_api.get_models_status(FakeDB()))

    store = out["store_runtime"]
    assert store["reachable"] is True
    assert store["error"] is None
    # Counts are what the RUNTIME holds, not what the picker shows: all 5
    # STORE_CAPS entries count here, including ppe_detection (a built-in id
    # the list skips) and not_installed (absent from enabled/). gloves is
    # "failed", so 4 of 5 are ready.
    assert (store["models_total"], store["models_ready"]) == (5, 4)
    assert store["checked_at"]
    assert store["last_success_at"]


async def test_models_status_reports_store_unreachable_without_losing_builtins(status_env):
    status_env(STORE_URL, store_down=True)
    out = as_json(await models_api.get_models_status(FakeDB()))

    # The built-ins still render: a broken store can never take them down.
    assert [m["model_id"] for m in out["models"]] == [
        "fall_detection",
        "ppe_detection",
        "geo_fencing",
    ]
    store = out["store_runtime"]
    assert store["reachable"] is False
    assert "down" in store["error"]
    assert (store["models_total"], store["models_ready"]) == (0, 0)
    # Never succeeded in this process, so there is no last-success to show.
    assert store["last_success_at"] is None


async def test_store_runtime_absent_from_response_when_not_configured(status_env):
    status_env("")
    out = as_json(await models_api.get_models_status(FakeDB()))
    assert "store_runtime" not in out


# --------------------------------------------------------------------------
# Health component
# --------------------------------------------------------------------------


async def _store_health(status_env, **kwargs):
    from app.services.health_service import HealthService

    status_env(**kwargs)
    return await HealthService().check_model_store_runtime()


async def test_health_store_component_disabled_when_not_configured(status_env):
    result = await _store_health(status_env, store_url="")
    # Not a fault: excluded from overall status, like a disabled NLP chat.
    assert result.status == "disabled"
    assert result.details == {"configured": False}
    assert result.error is None


async def test_health_store_component_degraded_when_some_models_not_ready(status_env):
    result = await _store_health(status_env, store_url=STORE_URL)
    # gloves is "failed" in STORE_CAPS, so 4 of 5 are ready.
    assert result.status == "degraded"
    assert result.error == "4/5 models ready"
    assert result.details["reachable"] is True
    assert result.details["models_not_ready"] == ["gloves"]
    assert result.details["models_ready"] == 4


async def test_health_store_component_healthy_when_all_ready(status_env, monkeypatch):
    all_ready = {
        "models": [
            {"model_id": "hard_hat", "version": "1.0.0", "state": "ready", "health": "healthy"},
            {"model_id": "safety_vest", "version": "1.0.0", "state": "ready", "health": "healthy"},
        ]
    }
    status_env(STORE_URL)
    monkeypatch.setitem(globals(), "_unused", None)

    async def fake_probe(*, force=False):
        from datetime import datetime, timezone

        return runtime_probe.StoreRuntimeProbe(
            configured=True,
            reachable=True,
            checked_at=datetime.now(timezone.utc),
            runtime_url=STORE_URL,
            runtime_id="model-store-runtime",
            last_success_at=datetime.now(timezone.utc),
            models=tuple(all_ready["models"]),
        )

    monkeypatch.setattr(runtime_probe, "probe_store_runtime", fake_probe)
    from app.services.health_service import HealthService

    result = await HealthService().check_model_store_runtime()
    assert result.status == "healthy"
    assert result.error is None
    assert result.details["models_ready"] == result.details["models_total"] == 2
    assert result.details["models_loaded"] == ["hard_hat", "safety_vest"]
    assert "models_not_ready" not in result.details


async def test_health_store_component_degraded_and_flagged_unreachable(status_env):
    """Unreachable is `degraded` so overall health does not go unhealthy,
    but details.reachable is False so the UI can render it red."""
    result = await _store_health(status_env, store_url=STORE_URL, store_down=True)

    assert result.status == "degraded"
    assert result.details["reachable"] is False
    assert result.details["configured"] is True
    assert "down" in result.error
    assert result.details["models_total"] == 0


async def test_unreachable_store_does_not_make_overall_status_unhealthy():
    from app.schemas.health import ComponentHealth
    from app.services.health_service import HealthService

    components = {
        "database": ComponentHealth(status="healthy"),
        "redis": ComponentHealth(status="healthy"),
        "ai_runtime": ComponentHealth(status="healthy"),
        "vas": ComponentHealth(status="healthy"),
        "nlp_chat": ComponentHealth(status="disabled"),
        "model_store_runtime": ComponentHealth(
            status="degraded", error="unreachable", details={"reachable": False}
        ),
    }
    assert HealthService().determine_overall_status(components) == "degraded"
    # And readiness is untouched: the store is not required to serve traffic.
    assert HealthService().is_ready(components) is True


# --------------------------------------------------------------------------
# Admin Model Management runtime column
# --------------------------------------------------------------------------


def _store_model(model_id):
    return SimpleNamespace(
        id=uuid.uuid4(),
        model_id=model_id,
        display_name=model_id.replace("_", " ").title(),
        state="applied",
        first_applied_at="2026-10-04T00:00:00Z",
        created_at="2026-10-04T00:00:00Z",
        created_by="admin",
    )


def _runtime_for(model_id, probe):
    from app.api.v1.admin import model_store as admin_api

    return admin_api._runtime_out(_store_model(model_id), probe, INSTALLED)


def _probe(**kwargs):
    from datetime import datetime, timezone

    kwargs.setdefault("configured", True)
    kwargs.setdefault("checked_at", datetime.now(timezone.utc))
    return runtime_probe.StoreRuntimeProbe(**kwargs)


def test_admin_runtime_column_running_for_ready_installed_model():
    probe = _probe(reachable=True, models=tuple(STORE_CAPS["models"]))
    out = _runtime_for("hard_hat", probe)
    assert out.state == "running"
    assert out.version == "1.0.0"
    assert out.detail == "ready, healthy"


def test_admin_runtime_column_not_loaded_when_runtime_reports_failed():
    probe = _probe(reachable=True, models=tuple(STORE_CAPS["models"]))
    # gloves is installed but the runtime reports it failed.
    out = _runtime_for("gloves", probe)
    assert out.state == "not_loaded"
    assert out.detail == "failed, unhealthy"


def test_admin_runtime_column_not_loaded_when_absent_from_capabilities():
    probe = _probe(reachable=True, models=())
    out = _runtime_for("hard_hat", probe)
    assert out.state == "not_loaded"
    assert out.detail == "Installed but not loaded by the runtime"


def test_admin_runtime_column_not_installed_for_uploaded_only_model():
    probe = _probe(reachable=True, models=tuple(STORE_CAPS["models"]))
    # Uploaded, but absent from enabled/ (INSTALLED).
    out = _runtime_for("never_installed", probe)
    assert out.state == "not_installed"
    assert out.detail == "Not installed in enabled/"


def test_admin_runtime_column_unreachable_for_every_row():
    probe = _probe(reachable=False, error="Name or service not known")
    for model_id in ("hard_hat", "never_installed"):
        out = _runtime_for(model_id, probe)
        # We genuinely don't know what is loaded, so don't claim otherwise.
        assert out.state == "unreachable"
        assert out.detail == "Name or service not known"


def test_admin_runtime_column_absent_when_store_not_configured():
    assert _runtime_for("hard_hat", _probe(configured=False, reachable=False)) is None

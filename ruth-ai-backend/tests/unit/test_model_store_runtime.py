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
from app.integrations.unified_runtime import config as runtime_config
from app.integrations.unified_runtime.frame_fetcher import FrameData
from app.integrations.unified_runtime.router import RuntimeRouter
from app.integrations.unified_runtime.store_router import StoreAwareRouter
from app.models.enums import ViolationType, resolve_violation_type
from app.schemas import ModelsStatusResponse
from app.services.model_store import enabled as enabled_mod
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
    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(scalar=lambda: None)


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

    def run(store_url="", store_down=False):
        client_factory.store_down = store_down
        cfg = runtime_config.UnifiedRuntimeConfig(MODEL_STORE_RUNTIME_URL=store_url)
        monkeypatch.setattr(models_api, "get_unified_runtime_config", lambda: cfg)
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
    assert down == off


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
    (tmp_path / "broken" / "1.0.0").mkdir(parents=True)
    (tmp_path / "broken" / "1.0.0" / "store_manifest.json").write_text("{not json")

    models = read_enabled_models(tmp_path)
    assert set(models) == {"hard_hat", "harness"}
    assert models["hard_hat"].reports_ppe is True
    assert models["harness"].version == "1.0.0"
    assert models["harness"].all_rules_need_zone is True
    assert models["harness"].zone_required_rules == ("a",)
    assert models["harness"].reports_ppe is False
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

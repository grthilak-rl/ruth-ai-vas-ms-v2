"""POST /api/v1/ai/inference: store models (fall_pose) go to the store runtime,
built-in models to the unified runtime, as in the inference loop."""

from types import SimpleNamespace

import pytest

from app.api.v1 import ai

STORE_URL = "http://model-store-runtime:8000"


@pytest.fixture
def configure(monkeypatch):
    def apply(store_url, installed):
        monkeypatch.setattr(
            ai, "get_unified_runtime_config",
            lambda: SimpleNamespace(model_store_runtime_url=store_url),
        )
        if isinstance(installed, Exception):
            def boom():
                raise installed
            monkeypatch.setattr(ai, "enabled_store_models", boom)
        else:
            monkeypatch.setattr(ai, "enabled_store_models", lambda: {m: object() for m in installed})
    return apply


def test_store_model_goes_to_the_store_runtime(configure):
    configure(STORE_URL, ["fall_pose", "hard_hat"])
    assert ai.runtime_url_for("fall_pose") == STORE_URL


def test_builtin_model_goes_to_the_unified_runtime(configure):
    configure(STORE_URL, ["fall_pose"])
    assert ai.runtime_url_for("fall_detection") is None
    assert ai.runtime_url_for("ppe_detection") is None


def test_no_store_runtime_configured_means_unified(configure):
    configure("", ["fall_pose"])
    assert ai.runtime_url_for("fall_pose") is None


def test_unreadable_store_falls_back_to_unified(configure):
    configure(STORE_URL, OSError("store unreadable"))
    assert ai.runtime_url_for("fall_pose") is None


@pytest.mark.asyncio
async def test_endpoint_builds_the_client_for_the_routed_runtime(configure, monkeypatch):
    configure(STORE_URL, ["fall_pose"])
    seen = {}

    class FakeClient:
        def __init__(self, runtime_url=None):
            seen["url"] = runtime_url

        async def submit_inference(self, **kwargs):
            seen["model_id"] = kwargs["model_id"]
            return SimpleNamespace(status="success", error=None, result={"violation_detected": False},
                                   inference_time_ms=1.0)

    monkeypatch.setattr(ai, "UnifiedRuntimeClient", FakeClient)
    out = await ai.submit_inference(ai.InferenceRequest(model_id="fall_pose", frame="QUJD"))
    assert out == {"violation_detected": False}
    assert seen == {"url": STORE_URL, "model_id": "fall_pose"}

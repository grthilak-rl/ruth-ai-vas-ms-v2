"""
GPU-required behaviour (added after the 24 Aug GPU outage).

A GPU runtime that has lost its GPU must fail loudly:
- GPUManager records *why* the GPU is unavailable and whether one is expected
- the loader refuses to put a model on CPU when GPU_FALLBACK_TO_CPU=false
- /health reports degraded/unhealthy with reasons and each model's device

Runs without torch or a GPU (GPU state is simulated).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.runtime.errors import LoadError
from ai.runtime.gpu_manager import GPUManager, GPUStatus, GPUDevice
from ai.runtime.loader import ModelLoader
from ai.runtime.models import (
    EntryPoints,
    HealthStatus,
    InputSpecification,
    LoadState,
    ModelVersionDescriptor,
    OutputSpecification,
    PerformanceHints,
    ResourceLimits,
)


@pytest.fixture
def descriptor():
    return ModelVersionDescriptor(
        model_id="m",
        version="1.0.0",
        display_name="M",
        description="test",
        directory_path=Path("/tmp/m/1.0.0"),
        input_spec=InputSpecification(
            min_width=224, max_width=1920, min_height=224, max_height=1080, channels=3
        ),
        output_spec=OutputSpecification(),
        limits=ResourceLimits(
            inference_timeout_ms=5000,
            preprocessing_timeout_ms=1000,
            postprocessing_timeout_ms=1000,
            max_memory_mb=2048,
        ),
        performance=PerformanceHints(warmup_iterations=0),
        entry_points=EntryPoints(inference="inference.py"),
    )


def no_gpu_manager(fallback_to_cpu: bool) -> GPUManager:
    """Real GPUManager in the state CUDA-unavailable detection leaves it in."""
    with patch.object(GPUManager, "_detect_gpus", lambda self: None):
        gm = GPUManager(enable_gpu=True, fallback_to_cpu=fallback_to_cpu)
    gm._status = GPUStatus.UNAVAILABLE
    gm._unavailable_reason = "CUDA not available (simulated)"
    return gm


def gpu_manager_with_device(fallback_to_cpu: bool, total_mb: float = 24000) -> GPUManager:
    with patch.object(GPUManager, "_detect_gpus", lambda self: None):
        gm = GPUManager(enable_gpu=True, fallback_to_cpu=fallback_to_cpu)
    gm._status = GPUStatus.AVAILABLE
    gm._devices = {0: GPUDevice(device_id=0, name="Fake GPU", total_memory_mb=total_mb)}
    gm._last_liveness_check = float("inf")  # skip NVML in tests
    return gm


# -----------------------------------------------------------------------------
# GPUManager
# -----------------------------------------------------------------------------


class TestGPUManagerReason:
    def test_disabled_gpu_is_not_expected(self):
        gm = GPUManager(enable_gpu=False)
        assert gm.gpu_expected is False
        assert "ENABLE_GPU=false" in gm.unavailable_reason
        assert gm.get_stats()["expected"] is False

    def test_missing_gpu_has_reason_and_is_expected(self):
        gm = no_gpu_manager(fallback_to_cpu=False)
        assert gm.gpu_expected is True
        assert gm.is_available is False
        assert "CUDA not available" in gm.unavailable_reason
        stats = gm.get_stats()
        assert stats["reason"] == gm.unavailable_reason
        assert stats["fallback_to_cpu"] is False

    def test_available_gpu_has_no_reason(self):
        gm = gpu_manager_with_device(fallback_to_cpu=False)
        assert gm.unavailable_reason is None

    def test_liveness_marks_lost_gpu(self):
        gm = gpu_manager_with_device(fallback_to_cpu=False)
        fake_nvml = MagicMock()
        fake_nvml.nvmlInit.side_effect = RuntimeError("Driver Not Loaded")
        with patch.dict("sys.modules", {"pynvml": fake_nvml}):
            assert gm.check_liveness(force=True) is False
        assert gm.status == GPUStatus.ERROR
        assert "GPU lost at runtime" in gm.unavailable_reason

    def test_liveness_ok_when_nvml_sees_device(self):
        gm = gpu_manager_with_device(fallback_to_cpu=False)
        fake_nvml = MagicMock()
        fake_nvml.nvmlDeviceGetCount.return_value = 1
        with patch.dict("sys.modules", {"pynvml": fake_nvml}):
            assert gm.check_liveness(force=True) is True
        assert gm.is_available


# -----------------------------------------------------------------------------
# Loader
# -----------------------------------------------------------------------------


class TestLoaderStrictGPU:
    def test_no_gpu_fallback_enabled_uses_cpu(self, descriptor):
        loader = ModelLoader(gpu_manager=no_gpu_manager(True), warmup_enabled=False)
        assert loader._allocate_device(descriptor) == "cpu"

    def test_no_gpu_fallback_disabled_refuses(self, descriptor):
        loader = ModelLoader(gpu_manager=no_gpu_manager(False), warmup_enabled=False)
        with pytest.raises(LoadError) as exc:
            loader._allocate_device(descriptor)
        assert "GPU required but unavailable" in exc.value.message
        assert "CUDA not available" in exc.value.message

    def test_gpu_full_fallback_disabled_refuses(self, descriptor):
        gm = gpu_manager_with_device(fallback_to_cpu=False, total_mb=1000)
        loader = ModelLoader(gpu_manager=gm, warmup_enabled=False)
        with pytest.raises(LoadError) as exc:
            loader._allocate_device(descriptor)
        assert "insufficient free memory" in exc.value.message

    def test_gpu_available_allocates(self, descriptor):
        gm = gpu_manager_with_device(fallback_to_cpu=False)
        loader = ModelLoader(gpu_manager=gm, warmup_enabled=False)
        assert loader._allocate_device(descriptor) == "cuda:0"

    def test_load_returns_failure_instead_of_raising(self, descriptor):
        loader = ModelLoader(gpu_manager=no_gpu_manager(False), warmup_enabled=False)
        result = loader.load(descriptor)
        assert result.success is False
        assert "GPU required" in result.error.message


# -----------------------------------------------------------------------------
# /health
# -----------------------------------------------------------------------------


def _version(model_id, state, health, last_error=None):
    return SimpleNamespace(
        model_id=model_id, version="1.0.0", state=state, health=health,
        inference_count=0, error_count=0, last_error=last_error,
    )


def _client(versions, gpu_manager, devices):
    from ai.server.routes import health as health_mod

    registry = MagicMock()
    registry.get_all_versions.return_value = versions
    sandbox_manager = MagicMock()
    sandbox_manager.get_sandbox.side_effect = lambda m, v: (
        SimpleNamespace(loaded_model=SimpleNamespace(device=devices[m])) if m in devices else None
    )

    app = FastAPI()
    app.include_router(health_mod.router, prefix="/health")
    app.state.gpu_manager = gpu_manager
    patches = [
        patch.object(health_mod, "get_registry", return_value=registry),
        patch.object(health_mod, "get_capability_publisher", return_value=None),
        patch.object(health_mod, "get_sandbox_manager", return_value=sandbox_manager),
    ]
    for p in patches:
        p.start()
    return TestClient(app), patches


@pytest.fixture
def make_client():
    started = []

    def _make(*args):
        client, patches = _client(*args)
        started.extend(patches)
        return client

    yield _make
    for p in started:
        p.stop()


class TestHealthGPU:
    def test_healthy_with_gpu(self, make_client):
        client = make_client(
            [_version("a", LoadState.READY, HealthStatus.HEALTHY)],
            gpu_manager_with_device(False),
            {"a": "cuda:0"},
        )
        body = client.get("/health", params={"verbose": "true"}).json()
        assert body["status"] == "healthy"
        assert body["reasons"] == []
        assert body["gpu_expected"] is True and body["gpu_available"] is True
        assert body["models"][0]["device"] == "cuda:0"

    def test_gpu_missing_all_models_failed_is_unhealthy(self, make_client):
        client = make_client(
            [_version("a", LoadState.FAILED, HealthStatus.UNHEALTHY, "GPU required but unavailable")],
            no_gpu_manager(False),
            {},
        )
        r = client.get("/health")
        body = r.json()
        assert r.status_code == 200  # docker healthcheck must not restart-loop
        assert body["status"] == "unhealthy"
        assert body["gpu_available"] is False  # present even without verbose
        assert any(x.startswith("gpu_unavailable: CUDA not available") for x in body["reasons"])
        assert any(x.startswith("models_failed: a:1.0.0 (GPU required") for x in body["reasons"])

    def test_gpu_missing_with_cpu_fallback_is_degraded(self, make_client):
        """Old behaviour (fallback on): models 'ready' on CPU must not look healthy."""
        client = make_client(
            [_version("a", LoadState.READY, HealthStatus.HEALTHY)],
            no_gpu_manager(True),
            {"a": "cpu"},
        )
        body = client.get("/health", params={"verbose": "true"}).json()
        assert body["status"] == "degraded"
        assert any(x.startswith("gpu_unavailable") for x in body["reasons"])
        assert "models_on_cpu: a:1.0.0" in body["reasons"]
        assert body["models"][0]["device"] == "cpu"

    def test_cpu_deployment_is_healthy(self, make_client):
        client = make_client(
            [_version("a", LoadState.READY, HealthStatus.HEALTHY)],
            GPUManager(enable_gpu=False),
            {"a": "cpu"},
        )
        body = client.get("/health").json()
        assert body["status"] == "healthy"
        assert body["gpu_expected"] is False

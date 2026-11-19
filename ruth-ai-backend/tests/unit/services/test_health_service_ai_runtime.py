"""check_ai_runtime: live probe, GPU detection, unreachable runtime.

Added after the 24 Aug GPU outage: System Health showed the AI Runtime as
healthy (registry push only, gpu_available hardcoded None) while inference
had no GPU. A missing GPU and an unreachable runtime must both be unhealthy.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.api.internal import ai_runtime as registry_mod
from app.api.internal.ai_runtime import RuntimeRegistration
from app.services.health_service import HealthService


@pytest.fixture
def registered_runtime():
    reg = RuntimeRegistration(
        runtime_id="unified-runtime-test",
        runtime_health="healthy",
        models=[{"model_id": "fall_detection"}],
        capacity={},
        summary={},
    )
    with patch.dict(registry_mod._registered_runtimes, {reg.runtime_id: reg}, clear=True):
        yield reg


def _service(probe_result):
    service = HealthService()
    service._probe_ai_runtime = AsyncMock(return_value=probe_result)
    return service


HEALTHY_BODY = {
    "status": "healthy",
    "reasons": [],
    "gpu_expected": True,
    "gpu_available": True,
    "models": [{"model_id": "fall_detection", "version": "1.0.0", "device": "cuda:0"}],
}


async def test_healthy_with_gpu(registered_runtime):
    result = await _service((True, HEALTHY_BODY, None)).check_ai_runtime()
    assert result.status == "healthy"
    assert result.details["gpu_available"] is True
    assert result.details["reachable"] is True
    assert result.details["hardware_type"] == "cuda"


async def test_gpu_missing_is_unhealthy(registered_runtime):
    body = {
        "status": "unhealthy",
        "reasons": ["gpu_unavailable: CUDA not available (no NVIDIA driver/device ...)"],
        "gpu_expected": True,
        "gpu_available": False,
        "gpu_reason": "CUDA not available (no NVIDIA driver/device ...)",
        "models": [],
    }
    result = await _service((True, body, None)).check_ai_runtime()
    assert result.status == "unhealthy"
    assert result.error.startswith("GPU unavailable")
    assert "CUDA not available" in result.error
    assert result.details["gpu_available"] is False
    assert result.details["gpu_expected"] is True


async def test_old_runtime_without_gpu_expected_field_still_flags(registered_runtime):
    """Runtimes built before gpu_expected existed: missing GPU must still alarm."""
    body = {"status": "healthy", "gpu_available": False, "models": []}
    result = await _service((True, body, None)).check_ai_runtime()
    assert result.status == "unhealthy"
    assert result.error.startswith("GPU unavailable")


async def test_cpu_deployment_not_flagged(registered_runtime):
    body = {"status": "healthy", "gpu_expected": False, "gpu_available": False,
            "models": [{"model_id": "m", "version": "1", "device": "cpu"}]}
    result = await _service((True, body, None)).check_ai_runtime()
    assert result.status == "healthy"


async def test_models_on_cpu_is_degraded(registered_runtime):
    body = dict(HEALTHY_BODY, models=[{"model_id": "fall_detection", "version": "1.0.0", "device": "cpu"}])
    result = await _service((True, body, None)).check_ai_runtime()
    assert result.status == "degraded"
    assert result.details["models_on_cpu"] == ["fall_detection:1.0.0"]


async def test_unreachable_is_unhealthy_even_if_registry_says_healthy(registered_runtime):
    result = await _service((False, {}, "ConnectError: refused")).check_ai_runtime()
    assert registered_runtime.runtime_health == "healthy"
    assert result.status == "unhealthy"
    assert result.error == "AI Runtime unreachable: ConnectError: refused"
    assert result.details["reachable"] is False


async def test_not_registered_and_unreachable_is_unhealthy():
    with patch.dict(registry_mod._registered_runtimes, {}, clear=True):
        result = await _service((False, {}, "ConnectError: refused")).check_ai_runtime()
    assert result.status == "unhealthy"
    assert result.error == "AI Runtime unreachable: ConnectError: refused (and not registered)"
    assert result.details["reachable"] is False


async def test_not_registered_but_probe_ok_is_degraded_not_unhealthy():
    """Ruth backend just restarted: in-memory registry empty for up to ~60 s
    until the runtime re-publishes. Not an outage: no red banner, no bell."""
    body = dict(HEALTHY_BODY, runtime_id="unified-runtime-live",
                models=[{"model_id": "fall_detection", "version": "1.0.0",
                         "state": "ready", "device": "cuda:0"}])
    with patch.dict(registry_mod._registered_runtimes, {}, clear=True):
        result = await _service((True, body, None)).check_ai_runtime()
    assert result.status == "degraded"
    assert "not registered yet" in result.error
    assert result.details["reachable"] is True
    assert result.details["runtime_id"] == "unified-runtime-live"
    assert result.details["models_loaded"] == ["fall_detection"]


async def test_not_registered_and_gpu_missing_is_still_unhealthy():
    body = {"status": "unhealthy", "gpu_expected": True, "gpu_available": False,
            "gpu_reason": "CUDA not available", "models": []}
    with patch.dict(registry_mod._registered_runtimes, {}, clear=True):
        result = await _service((True, body, None)).check_ai_runtime()
    assert result.status == "unhealthy"
    assert result.error.startswith("GPU unavailable")


async def test_runtime_reported_unhealthy_reasons_surface(registered_runtime):
    body = dict(HEALTHY_BODY, status="unhealthy", reasons=["models_failed: a:1 (boom)"])
    result = await _service((True, body, None)).check_ai_runtime()
    assert result.status == "unhealthy"
    assert "models_failed: a:1 (boom)" in result.error


class TestProbe:
    """_probe_ai_runtime against a mocked HTTP transport."""

    async def _probe(self, handler):
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_client(*args, **kwargs)

        with patch("app.services.health_service.httpx.AsyncClient", side_effect=client_factory):
            return await HealthService()._probe_ai_runtime(1.0)

    async def test_ok(self):
        ok, body, err = await self._probe(lambda req: httpx.Response(200, json={"status": "healthy"}))
        assert ok and body["status"] == "healthy" and err is None

    async def test_503_not_initialized_counts_as_reachable_unhealthy(self):
        ok, body, err = await self._probe(
            lambda req: httpx.Response(503, json={"detail": "Runtime not initialized"})
        )
        assert ok
        assert body["status"] == "unhealthy"

    async def test_connection_refused(self):
        def handler(req):
            raise httpx.ConnectError("connection refused")

        ok, body, err = await self._probe(handler)
        assert not ok
        assert "ConnectError" in err

    async def test_timeout(self):
        def handler(req):
            raise httpx.ReadTimeout("slow")

        ok, _, err = await self._probe(handler)
        assert not ok
        assert err.startswith("no response within")

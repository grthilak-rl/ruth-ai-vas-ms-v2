"""geofence (store) replacing the built-in geo_fencing, and the built-ins'
retirement.

- The store model reports its zone types, which the zone editor offers.
- Labels and severities come from the violation type, unchanged: "Zone
  Intrusion" (high) and "Zone Exit" (medium).
- With every built-in model retired, UNIFIED_RUNTIME_IN_USE=false makes
  System Health show the unified runtime "disabled" (left out of overall
  health). With the flag on, a runtime with no models stays unhealthy.
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.internal import ai_runtime as registry_mod
from app.models.enums import ViolationType, resolve_violation_type
from app.services.violation_labels import ViolationLabeler
from app.services.health_service import HealthService
from app.services.model_store.enabled import read_enabled_models
from app.services.violation_severity import resolve_severity

MANIFESTS = Path(__file__).resolve().parents[3] / "ai" / "store_plugin" / "manifests"


@pytest.fixture
def store(tmp_path):
    version_dir = tmp_path / "geofence" / "1.0.0"
    version_dir.mkdir(parents=True)
    shutil.copy(MANIFESTS / "geofence.json", version_dir / "store_manifest.json")
    return read_enabled_models(tmp_path)


def test_geofence_reports_its_zone_types(store):
    info = store["geofence"]
    assert info.zone_types == ("restricted", "allowed")
    assert info.all_rules_need_zone is True  # the backend refuses it without zones
    assert info.min_confidence == 0.7  # the 0.7 gate the built-in was recorded at


def test_zone_types_are_empty_for_models_without_zone_rules(tmp_path):
    d = tmp_path / "hard_hat" / "1.0.0"
    d.mkdir(parents=True)
    shutil.copy(MANIFESTS / "hard_hat.json", d / "store_manifest.json")
    assert read_enabled_models(tmp_path)["hard_hat"].zone_types == ()


@pytest.mark.parametrize(
    "vtype, family, label, severity",
    [
        ("zone_intrusion", ViolationType.ZONE_INTRUSION, "Zone Intrusion", "high"),
        ("zone_exit", ViolationType.ZONE_EXIT, "Zone Exit", "medium"),
    ],
)
def test_types_labels_and_severities_carry_over(store, vtype, family, label, severity):
    # A family type: stored with no type_detail, like fall_detected.
    assert resolve_violation_type(vtype) == (family, None)
    before, after = ViolationLabeler({}), ViolationLabeler(store)
    for model_id in ("geo_fencing", "geofence"):  # past rows, new rows
        assert after.combined_label(family, None, model_id) == before.combined_label(family, None, model_id) == label
    assert resolve_severity(type_=family, type_detail=None, model_id="geofence",
                            store_models=store) == severity
    assert store["geofence"].rule_severity(vtype) == severity
    # and the same as the built-in default, so past rows read the same
    assert resolve_severity(type_=family, type_detail=None, model_id="geo_fencing") == severity


# ---------------------------------------------------------------------------
# System Health with every built-in retired: explicit flag, not inferred
# ---------------------------------------------------------------------------

NO_MODELS_BODY = {
    "status": "unhealthy",
    "models_loaded": 0,
    "models_ready": 0,
    "reasons": ["no_models: no models discovered"],
    "gpu_expected": True,
    "gpu_available": True,
    "models": [],
}


@pytest.fixture
def no_registered_runtime():
    with patch.dict(registry_mod._registered_runtimes, {}, clear=True):
        yield


def _service(probe):
    service = HealthService()
    service._probe_ai_runtime = AsyncMock(return_value=probe)
    return service


def _config(in_use, store_url="http://model-store-runtime:8000"):
    return patch(
        "app.integrations.unified_runtime.config.get_unified_runtime_config",
        return_value=SimpleNamespace(unified_runtime_in_use=in_use, model_store_runtime_url=store_url,
                                     model_store_runtime_id="model-store-runtime"),
    )


def test_flag_defaults_to_in_use(monkeypatch):
    from app.integrations.unified_runtime.config import UnifiedRuntimeConfig

    monkeypatch.delenv("UNIFIED_RUNTIME_IN_USE", raising=False)
    assert UnifiedRuntimeConfig().unified_runtime_in_use is True
    monkeypatch.setenv("UNIFIED_RUNTIME_IN_USE", "false")
    assert UnifiedRuntimeConfig().unified_runtime_in_use is False


async def test_flag_off_is_disabled_without_probing(no_registered_runtime):
    service = _service((True, NO_MODELS_BODY, None))
    with _config(in_use=False):
        result = await service.check_ai_runtime()
    assert result.status == "disabled"
    assert "UNIFIED_RUNTIME_IN_USE=false" in result.details["reasons"][0]
    service._probe_ai_runtime.assert_not_awaited()
    assert HealthService().determine_overall_status({"ai_runtime": result}) == "healthy"


async def test_flag_off_is_disabled_even_if_the_runtime_is_down(no_registered_runtime):
    with _config(in_use=False):
        result = await _service((False, {}, "connection refused")).check_ai_runtime()
    assert result.status == "disabled"


async def test_flag_on_with_no_models_stays_unhealthy(no_registered_runtime):
    """Not inferred from "no models": a reachable runtime with nothing
    loaded is an outage unless the flag says it was retired."""
    with _config(in_use=True):
        result = await _service((True, NO_MODELS_BODY, None)).check_ai_runtime()
    assert result.status == "unhealthy"
    assert "no_models" in result.error


async def test_flag_on_with_models_is_judged_as_before(no_registered_runtime):
    body = dict(NO_MODELS_BODY, status="healthy", models_loaded=1, models_ready=1, reasons=[],
                models=[{"model_id": "ppe_detection", "version": "1.0.0", "device": "cuda:0", "state": "ready"}])
    with _config(in_use=True):
        result = await _service((True, body, None)).check_ai_runtime()
    assert result.status in ("healthy", "degraded")  # degraded: not registered yet


async def test_flag_on_unreachable_is_unhealthy(no_registered_runtime):
    with _config(in_use=True):
        result = await _service((False, {}, "connection refused")).check_ai_runtime()
    assert result.status == "unhealthy"

"""Which confidence gate a violation has to clear before it is written.

Until now there was one gate for every model: `stream_sessions.
confidence_threshold`, 0.7 on every live session. Store models also carry
their own `min_confidence` in the manifest rule, and the plugin applies it
when it decides `violation_detected` — so the effective gate was
`max(manifest, session)` and the manifest number did nothing unless it was
higher. A model tuned to 0.4 could never record anything, silently: the
runtime logged the violation and no row appeared.

Store models are now gated on their own manifest floor. Built-in models
have no manifest and keep the session threshold.

The cases that matter are the ones that fail quietly — a model that cannot
write a violation it detected, and a model that writes one it should not —
so each gets its own test.
"""

import json
from pathlib import Path

import pytest

from app.services.model_store.enabled import StoreModelInfo, read_enabled_models

MANIFESTS = Path(__file__).resolve().parents[3] / "ai" / "store_plugin" / "manifests"
SESSION_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# The manifest -> threshold mapping
# ---------------------------------------------------------------------------


def _install(root: Path, model_id: str, rules, version: str = "1.0.0") -> None:
    d = root / model_id / version
    d.mkdir(parents=True)
    (d / "store_manifest.json").write_text(json.dumps({
        "manifest_version": 1,
        "model_id": model_id,
        "display_name": model_id,
        "weights": "w.pt",
        "task": "detect",
        "imgsz": 1280,
        "classes": {"0": "a", "1": "b"},
        "rules": rules,
    }))


def test_min_confidence_comes_from_the_rule(tmp_path):
    _install(tmp_path, "m", [{"id": "r", "classes": ["b"], "min_confidence": 0.42,
                              "violation_type": "missing_vest", "severity": "high"}])
    assert read_enabled_models(tmp_path)["m"].min_confidence == pytest.approx(0.42)


def test_several_rules_use_the_weakest_floor(tmp_path):
    """The plugin reports the max confidence among *firing* detections, and
    each of those already cleared its own rule. Gating on the lowest floor
    is the only bound that cannot contradict the plugin."""
    _install(tmp_path, "m", [
        {"id": "a", "classes": ["b"], "min_confidence": 0.8,
         "violation_type": "missing_vest", "severity": "high"},
        {"id": "b", "classes": ["b"], "min_confidence": 0.35,
         "violation_type": "missing_vest", "severity": "low"},
    ])
    assert read_enabled_models(tmp_path)["m"].min_confidence == pytest.approx(0.35)


def test_a_manifest_with_no_usable_rule_can_never_fire(tmp_path):
    """1.0 is unreachable, which is the safe direction for a model we
    cannot characterise — better silent than spraying alerts."""
    _install(tmp_path, "m", [])
    assert read_enabled_models(tmp_path)["m"].min_confidence == 1.0


def test_unreadable_manifest_is_not_a_store_model(tmp_path):
    d = tmp_path / "m" / "1.0.0"
    d.mkdir(parents=True)
    (d / "store_manifest.json").write_text("{ broken")
    assert read_enabled_models(tmp_path) == {}


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


class _Loop:
    """Just the resolver under test, with the store lookup injected."""

    def __init__(self, store):
        self._store = store

    _violation_threshold = None  # bound below


@pytest.fixture
def resolve(monkeypatch):
    """`_violation_threshold` with `enabled_store_models` faked out."""
    from app.services import inference_loop as mod

    def make(store: dict):
        monkeypatch.setattr(mod, "enabled_store_models", lambda: store)
        loop = _Loop(store)
        return lambda model_id, session=SESSION_THRESHOLD: (
            mod.InferenceLoopService._violation_threshold(loop, model_id, session)
        )

    return make


def _info(model_id: str, min_confidence: float) -> StoreModelInfo:
    return StoreModelInfo(model_id=model_id, version="1.0.0",
                          display_name=model_id, min_confidence=min_confidence)


def test_store_model_uses_its_manifest_floor(resolve):
    r = resolve({"goggles": _info("goggles", 0.4)})
    assert r("goggles") == pytest.approx(0.4)


def test_store_model_below_the_session_threshold_is_now_writable(resolve):
    """The bug this change fixes: 0.4 < 0.7 meant the row was dropped."""
    r = resolve({"goggles": _info("goggles", 0.4)})
    assert 0.5 >= r("goggles"), "a 0.5 detection must now clear the gate"


def test_store_model_above_the_session_threshold_is_respected(resolve):
    """It cuts both ways: a stricter manifest is not loosened to 0.7."""
    r = resolve({"m": _info("m", 0.9)})
    assert r("m") == pytest.approx(0.9)
    assert 0.8 < r("m"), "a 0.8 detection must still be refused"


def test_builtin_model_keeps_the_session_threshold(resolve):
    r = resolve({"goggles": _info("goggles", 0.4)})
    assert r("ppe_detection") == pytest.approx(SESSION_THRESHOLD)
    assert r("fall_detection") == pytest.approx(SESSION_THRESHOLD)


def test_builtin_follows_a_non_default_session_threshold(resolve):
    r = resolve({})
    assert r("ppe_detection", 0.55) == pytest.approx(0.55)


def test_unknown_store_model_falls_back_to_the_session_threshold(resolve):
    """An unreadable or not-yet-installed manifest must not open the gate."""
    r = resolve({})
    assert r("goggles") == pytest.approx(SESSION_THRESHOLD)


def test_a_mixed_camera_gates_each_model_separately(resolve):
    """One camera, a store model and a built-in, the same tick."""
    r = resolve({"goggles": _info("goggles", 0.4), "safety_vest": _info("safety_vest", 0.7)})
    assert r("goggles") == pytest.approx(0.4)
    assert r("safety_vest") == pytest.approx(0.7)
    assert r("ppe_detection") == pytest.approx(SESSION_THRESHOLD)


# ---------------------------------------------------------------------------
# The shipped manifests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["hard_hat", "safety_vest", "gloves", "goggles"])
def test_shipped_manifests_keep_todays_effective_gate(name):
    """Behaviour-preserving by construction.

    The old effective gate was max(manifest, 0.7) = 0.7 for every model.
    Shipping 0.7 in each manifest means the day this change deploys,
    nothing about alert volume moves. Lowering one of these is then a
    deliberate, per-model decision with a measured cost: at 0.5,
    safety_vest alone goes from 525 to 4,180 violations per 20 hours.
    """
    m = json.loads((MANIFESTS / f"{name}.json").read_text())
    floors = [r["min_confidence"] for r in m["rules"]]
    assert min(floors) == 0.7, f"{name} would change alert volume on deploy"

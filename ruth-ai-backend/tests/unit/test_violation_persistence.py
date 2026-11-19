"""Persistence: open a violation only after the result has held for N seconds.

A store manifest may carry ``"persistence": {"min_seconds": N}``. The
backend then opens a violation only once the model's result has qualified
(violation above the gate) continuously for N seconds; any miss resets the
clock. Without the block, N is 0 and a violation opens on the first
qualifying result, exactly as before. Those are the cases tested here,
through the real ``_apply_violation_rules`` with the store, the clock and
the violation write faked.
"""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.services import inference_loop as mod
from app.services.model_store.enabled import StoreModelInfo, read_enabled_models

MANIFESTS = Path(__file__).resolve().parents[3] / "ai" / "store_plugin" / "manifests"


# ---------------------------------------------------------------------------
# Manifest -> persistence_seconds
# ---------------------------------------------------------------------------


def _install(root: Path, model_id: str, extra: dict) -> None:
    d = root / model_id / "1.0.0"
    d.mkdir(parents=True)
    (d / "store_manifest.json").write_text(json.dumps({
        "model_id": model_id, "display_name": model_id, "task": "detect",
        "classes": {"0": "a"},
        "rules": [{"id": "r", "classes": ["a"], "min_confidence": 0.5,
                   "violation_type": "missing_vest", "severity": "high"}],
        **extra,
    }))


@pytest.mark.parametrize(
    "extra, expected",
    [
        ({}, 0.0),
        ({"persistence": {"min_seconds": 3}}, 3.0),
        ({"persistence": {"min_seconds": 1.5}}, 1.5),
        ({"persistence": {"min_seconds": 0}}, 0.0),
        ({"persistence": {"min_seconds": -1}}, 0.0),
        ({"persistence": {"min_seconds": 61}}, 0.0),
        ({"persistence": {"min_seconds": True}}, 0.0),
        ({"persistence": {"min_seconds": "3"}}, 0.0),
        ({"persistence": 3}, 0.0),
    ],
)
def test_persistence_seconds_from_manifest(tmp_path, extra, expected):
    _install(tmp_path, "m", extra)
    assert read_enabled_models(tmp_path)["m"].persistence_seconds == expected


@pytest.mark.parametrize("path", sorted(MANIFESTS.glob("*.json")), ids=lambda p: p.stem)
def test_shipped_manifests_have_no_persistence_yet(tmp_path, path):
    """Behaviour-neutral release: no shipped model waits before alarming."""
    manifest = json.loads(path.read_text())
    d = tmp_path / manifest["model_id"] / "1.0.0"
    d.mkdir(parents=True)
    (d / "store_manifest.json").write_text(path.read_text())
    assert read_enabled_models(tmp_path)[manifest["model_id"]].persistence_seconds == 0.0


# ---------------------------------------------------------------------------
# The rule, end to end
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def harness(monkeypatch):
    """A loop with only what `_apply_violation_rules` touches, a fake clock
    and a recording `_create_violation`."""
    clock = _Clock()
    monkeypatch.setattr(mod.time, "monotonic", clock)

    def make(persistence_seconds: float, model_id: str = "fall_pose", store_model: bool = True):
        store = {}
        if store_model:
            store[model_id] = StoreModelInfo(
                model_id=model_id, version="1.0.0", display_name=model_id,
                min_confidence=0.7, persistence_seconds=persistence_seconds,
            )
        monkeypatch.setattr(mod, "enabled_store_models", lambda: store)
        loop = mod.InferenceLoopService.__new__(mod.InferenceLoopService)
        loop._model_violation_state = {}
        created = []

        async def fake_create(**kwargs):
            created.append(clock.t)

        loop._create_violation = fake_create
        session = uuid4()

        async def tick(at: float, fires: bool, confidence: float = 0.8):
            clock.t = 1000.0 + at
            result = {"result": {"violation_detected": fires, "confidence": confidence if fires else 0.0,
                                 "detections": []}}
            await loop._apply_violation_rules(session, uuid4(), "vas", model_id, result, 0.7)

        return loop, tick, created

    return make


async def test_no_persistence_opens_on_the_first_qualifying_result(harness):
    """Today's behaviour, unchanged: open on the first hit, one violation per
    clear->violation transition, a single miss re-arms."""
    _, tick, created = harness(0)
    await tick(0.0, True)
    await tick(0.5, True)
    await tick(1.0, False)
    await tick(1.5, True)
    assert created == [1000.0, 1001.5]


async def test_violation_waits_until_held_for_the_persistence_time(harness):
    _, tick, created = harness(2)
    for at in (0.0, 0.5, 1.0, 1.5):
        await tick(at, True)
    assert created == []
    await tick(2.0, True)
    assert created == [1002.0]
    await tick(2.5, True)  # still the same violation
    assert created == [1002.0]


async def test_a_miss_resets_the_clock(harness):
    _, tick, created = harness(2)
    await tick(0.0, True)
    await tick(1.5, True)
    await tick(2.0, False)  # flicker: the clock restarts
    await tick(2.5, True)
    await tick(4.0, True)
    assert created == []
    await tick(4.5, True)
    assert created == [1004.5]


async def test_a_result_below_the_gate_counts_as_a_miss(harness):
    _, tick, created = harness(1)
    await tick(0.0, True)
    await tick(0.5, True, confidence=0.6)  # under the 0.7 manifest gate
    await tick(1.0, True)
    assert created == []
    await tick(2.0, True)
    assert created == [1002.0]


async def test_short_flicker_never_alarms(harness):
    """The 2026-10-04 pattern: 1-6 frame flickers of a false positive."""
    _, tick, created = harness(3)
    t = 0.0
    for _ in range(10):
        for _ in range(4):  # 4 frames at 2 fps: 1.5 s held
            await tick(t, True)
            t += 0.5
        await tick(t, False)
        t += 0.5
    assert created == []


async def test_builtin_models_never_wait(harness):
    _, tick, created = harness(5, model_id="ppe_detection", store_model=False)
    await tick(0.0, True)
    assert created == [1000.0]


async def test_store_lookup_failure_falls_back_to_no_wait(harness, monkeypatch):
    loop, tick, created = harness(5)

    def broken():
        raise OSError("store unreadable")

    monkeypatch.setattr(mod, "enabled_store_models", broken)
    assert loop._persistence_seconds("fall_pose") == 0.0

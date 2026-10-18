"""Store plugin and installer tests. A fake ultralytics stands in for YOLO,
so no uploaded weights are ever unpickled here."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
PLUGIN_SRC = HERE.parent / "inference.py"
MANIFESTS = HERE.parent / "manifests"


def manifest(name):
    return json.loads((MANIFESTS / f"{name}.json").read_text())


# --------------------------------------------------------------------------
# Fake ultralytics
# --------------------------------------------------------------------------


class _Arr:
    def __init__(self, a):
        self.a = np.asarray(a, dtype=float)

    def cpu(self):
        return self

    def numpy(self):
        return self.a


class _Boxes:
    def __init__(self, rows):
        rows = rows or []
        self.xyxy = _Arr([r[:4] for r in rows] or np.zeros((0, 4)))
        self.conf = _Arr([r[4] for r in rows])
        self.cls = _Arr([r[5] for r in rows])


class FakeYOLO:
    instances = []
    next_rows = []

    def __init__(self, weights):
        self.weights = weights
        self.calls = []
        FakeYOLO.instances.append(self)

    def predict(self, frame, **kwargs):
        self.calls.append(kwargs)
        rows = [r for r in FakeYOLO.next_rows if r[4] >= kwargs["conf"]]
        return [types.SimpleNamespace(boxes=_Boxes(rows))]


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    """A model dir like install_enabled builds, with the plugin imported from it."""

    def make(name):
        version_dir = tmp_path / name / "1.0.0"
        (version_dir / "weights").mkdir(parents=True)
        m = manifest(name)
        (version_dir / "weights" / m["weights"]).write_bytes(b"not a real model")
        (version_dir / "store_manifest.json").write_text(json.dumps(m))
        (version_dir / "inference.py").write_text(PLUGIN_SRC.read_text())
        monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
        spec = importlib.util.spec_from_file_location(f"store_{name}_inference", version_dir / "inference.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    FakeYOLO.instances.clear()
    FakeYOLO.next_rows = []
    return make


FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)


# --------------------------------------------------------------------------
# infer()
# --------------------------------------------------------------------------


def test_no_detections_is_no_violation(plugin):
    mod = plugin("hard_hat")
    out = mod.infer(FRAME)
    assert out["violation_detected"] is False
    assert out["detections"] == [] and out["objects"] == []
    assert out["confidence"] == 0.0
    assert out["metadata"]["source"] == "store"
    assert out["metadata"]["display_name"] == "Hard Hat"
    assert out["metadata"]["rules_active"] == ["missing_hardhat"]


def test_violation_class_fires_and_present_class_does_not(plugin):
    mod = plugin("hard_hat")
    FakeYOLO.next_rows = [
        [100, 50, 160, 110, 0.91, 0],  # hardhat (present)
        [400, 60, 450, 120, 0.83, 1],  # no-hardhat
    ]
    out = mod.infer(FRAME)
    assert out["violation_detected"] is True
    assert out["violation_type"] == "missing_hardhat"
    assert out["severity"] == "critical"
    assert out["confidence"] == pytest.approx(0.83)
    # only the violating box goes with the violation, labelled with its type
    assert [d["class_name"] for d in out["detections"]] == ["no-hardhat"]
    assert out["detections"][0]["label"] == "missing_hardhat"
    assert out["detections"][0]["bbox"] == [400.0, 60.0, 450.0, 120.0]  # frame pixels
    assert "in_zone" not in out["detections"][0]  # no zone dedup without zones
    # the overlay gets everything, violation marked
    assert [(o["class_name"], o["violation"]) for o in out["objects"]] == [
        ("hardhat", False),
        ("no-hardhat", True),
    ]


def test_below_min_confidence_never_fires(plugin):
    floor = manifest("hard_hat")["rules"][0]["min_confidence"]
    mod = plugin("hard_hat")
    FakeYOLO.next_rows = [[400, 60, 450, 120, floor - 0.01, 1]]
    out = mod.infer(FRAME)
    assert out["violation_detected"] is False
    assert out["objects"] == []  # filtered by the predict conf floor


def test_vest_reversed_class_order(plugin):
    mod = plugin("safety_vest")  # 0 = no-vest, 1 = vest
    FakeYOLO.next_rows = [[10, 10, 90, 200, 0.77, 0], [200, 10, 290, 200, 0.95, 1]]
    out = mod.infer(FRAME)
    assert out["violation_type"] == "missing_vest"
    assert [d["class_name"] for d in out["detections"]] == ["no-vest"]
    assert {o["class_name"]: o["violation"] for o in out["objects"]} == {"no-vest": True, "vest": False}


def test_gloves_severity_high(plugin):
    mod = plugin("gloves")
    FakeYOLO.next_rows = [[10, 10, 40, 40, 0.71, 1]]
    out = mod.infer(FRAME)
    assert (out["violation_type"], out["severity"]) == ("missing_gloves", "high")


def test_predict_called_with_manifest_imgsz_and_floor(plugin):
    mod = plugin("safety_vest")
    mod.infer(FRAME)
    mod.infer(FRAME)
    assert len(FakeYOLO.instances) == 1  # loaded once
    yolo = FakeYOLO.instances[0]
    assert yolo.weights.endswith("weights/bestvest.pt")
    assert yolo.calls[0]["imgsz"] == 1280
    assert yolo.calls[0]["conf"] == manifest("safety_vest")["rules"][0]["min_confidence"]
    assert yolo.calls[0]["verbose"] is False


def test_bad_frame_raises(plugin):
    mod = plugin("hard_hat")
    with pytest.raises(ValueError):
        mod.infer(None)


def test_missing_weights_raises(plugin, tmp_path):
    mod = plugin("hard_hat")
    (tmp_path / "hard_hat" / "1.0.0" / "weights" / "besthardhat.pt").unlink()
    with pytest.raises(FileNotFoundError):
        mod.infer(FRAME)


# --------------------------------------------------------------------------
# Rules: zones fail closed, severity ordering
# --------------------------------------------------------------------------


def zone_manifest():
    return {
        "model_id": "harness",
        "classes": {"0": "harness", "1": "no-harness", "2": "no-helmet"},
        "rules": [
            {"id": "missing_harness", "classes": ["no-harness"], "min_confidence": 0.5,
             "violation_type": "missing_harness", "severity": "critical", "requires_zone": "work_at_height"},
        ],
    }


def obj(cls, conf, bbox=(100, 100, 200, 300)):
    return {"bbox": list(bbox), "confidence": conf, "class_id": 1, "class_name": cls, "violation": False}


def load_rules_module():
    spec = importlib.util.spec_from_file_location("store_rules_only", PLUGIN_SRC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zone_rule_inactive_without_a_zone():
    mod = load_rules_module()
    out = mod.apply_rules([obj("no-harness", 0.9)], zone_manifest(), config={})
    assert out["violation_detected"] is False
    assert out["rules_inactive"] == ["missing_harness"] and out["rules_active"] == []


def test_zone_rule_needs_its_zone_type_and_the_anchor_inside():
    mod = load_rules_module()
    wrong_type = {"zones": [{"id": "z", "type": "restricted", "points": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]}]}
    assert mod.apply_rules([obj("no-harness", 0.9)], zone_manifest(), wrong_type)["violation_detected"] is False

    zone = {"id": "roof", "type": "work_at_height", "points": [[0, 0], [500, 0], [500, 400], [0, 400]]}
    inside = mod.apply_rules([obj("no-harness", 0.9, (100, 100, 200, 300))], zone_manifest(), {"zones": [zone]})
    assert inside["violation_detected"] is True
    assert inside["detections"][0]["in_zone"] is True and inside["detections"][0]["zone_id"] == "roof"

    # bottom centre (150, 450) is below the zone
    outside = mod.apply_rules([obj("no-harness", 0.9, (100, 300, 200, 450))], zone_manifest(), {"zones": [zone]})
    assert outside["violation_detected"] is False


def test_highest_severity_names_the_violation():
    mod = load_rules_module()
    m = {
        "classes": {"0": "a", "1": "b"},
        "rules": [
            {"id": "ra", "classes": ["a"], "min_confidence": 0.5, "violation_type": "type_a", "severity": "high"},
            {"id": "rb", "classes": ["b"], "min_confidence": 0.5, "violation_type": "type_b", "severity": "critical"},
        ],
    }
    out = mod.apply_rules([obj("a", 0.99), obj("b", 0.6)], m)
    assert out["violation_type"] == "type_b" and out["severity"] == "critical"
    assert out["confidence"] == pytest.approx(0.99)  # highest among firing detections
    assert {d["rule_id"] for d in out["detections"]} == {"ra", "rb"}


# --------------------------------------------------------------------------
# Installer: manifests valid, problems caught
# --------------------------------------------------------------------------


def load_installer():
    spec = importlib.util.spec_from_file_location("install_enabled", HERE.parent / "install_enabled.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["hard_hat", "safety_vest", "gloves", "goggles", "harness"])
def test_shipped_manifests_are_valid(name):
    """Unknown top-level keys (`diagnostics`, `_trial`) must not be rejected."""
    assert load_installer().manifest_problems(manifest(name)) == []


def test_manifest_problems_caught():
    ie = load_installer()
    m = manifest("hard_hat")
    m.update(model_id="ppe_detection", imgsz=1000)
    m["rules"][0]["classes"] = ["no-helmet"]
    m["performance"]["recommended_fps"] = 0.5
    problems = " | ".join(ie.manifest_problems(m))
    for expected in ("built-in id", "multiple of 32", "not in the model's classes", "recommended_fps"):
        assert expected in problems


def test_build_tree_layout(tmp_path):
    ie = load_installer()
    (tmp_path / "drafts" / "pk" / "weights").mkdir(parents=True)
    src = tmp_path / "drafts" / "pk" / "weights" / "besthardhat.pt"
    src.write_bytes(b"x")
    ie.build(tmp_path, [manifest("hard_hat")], tmp_path / "out")
    d = tmp_path / "out" / "hard_hat" / "1.0.0"
    assert sorted(p.name for p in d.iterdir()) == ["inference.py", "model.yaml", "store_manifest.json", "weights"]
    w = d / "weights" / "besthardhat.pt"
    assert not w.is_symlink() and w.stat().st_ino == src.stat().st_ino  # hardlink
    contract = json.loads(d.joinpath("model.yaml").read_text().split("\n", 1)[1])
    assert contract["model_id"] == "hard_hat" and contract["version"] == "1.0.0"
    assert isinstance(contract["performance"]["recommended_fps"], int)
    assert d.joinpath("inference.py").read_text() == PLUGIN_SRC.read_text()


# --------------------------------------------------------------------------
# Trial mode (per-model diagnostics)
#
# The whole point of trial mode is that it observes ONE model without
# disturbing anything else on a live plant. So the tests that matter most
# are the negative ones: what must NOT change for the models that do not
# carry a diagnostics block.
# --------------------------------------------------------------------------


DIAGNOSTICS = {"summary_log_sample": 1.0, "predict_floor": 0.01}


@pytest.fixture
def plugin_with(tmp_path, monkeypatch):
    """Like `plugin`, but the manifest can be edited before it is written."""

    def make(name, mutate=None, tag="x"):
        m = manifest(name)
        if mutate:
            mutate(m)
        version_dir = tmp_path / f"{name}_{tag}" / "1.0.0"
        (version_dir / "weights").mkdir(parents=True)
        (version_dir / "weights" / m["weights"]).write_bytes(b"not a real model")
        (version_dir / "store_manifest.json").write_text(json.dumps(m))
        (version_dir / "inference.py").write_text(PLUGIN_SRC.read_text())
        monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
        spec = importlib.util.spec_from_file_location(
            f"store_{name}_{tag}_inference", version_dir / "inference.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    FakeYOLO.instances.clear()
    FakeYOLO.next_rows = []
    return make


def add_diagnostics(m):
    m["diagnostics"] = dict(DIAGNOSTICS)


def drop_diagnostics(m):
    """`goggles.json` ships in trial mode; strip it to get the plain case."""
    m.pop("diagnostics", None)


TRIAL = {"goggles", "gloves", "harness"}
NOT_IN_TRIAL = ["hard_hat", "safety_vest"]


def test_which_models_are_in_trial_mode():
    """Documents the live trial, and fails once it is cleaned up.

    When a model leaves trial mode its `diagnostics` and `_trial` keys go,
    and this test must be updated with them — that coupling is the point.
    """
    for name in TRIAL:
        m = manifest(name)
        assert m["diagnostics"] == {"summary_log_sample": 1.0, "predict_floor": 0.01}
        assert "_trial" in m, f"{name}: a trial must carry its own removal note"
    for name in NOT_IN_TRIAL:
        assert "diagnostics" not in manifest(name)
        assert "_trial" not in manifest(name)


@pytest.mark.parametrize("name", ["hard_hat", "safety_vest", "gloves", "goggles", "harness"])
def test_every_shipped_model_gates_violations_at_0_7(name):
    """The manifest floor is now the violation gate (backend side too).

    It was max(manifest, session 0.7) before, so every model was really
    gated at 0.7 whatever its manifest said. Setting them all to 0.7
    makes that explicit and keeps behaviour identical on the day the
    backend starts honouring the manifest. Changing one of these numbers
    now changes real alert volume — see docs/model-store/STEP5_PROPOSAL
    section 11 for the measured impact.
    """
    assert manifest(name)["rules"][0]["min_confidence"] == 0.7


# --- the inertness guarantee -----------------------------------------------


@pytest.mark.parametrize("name", NOT_IN_TRIAL)
def test_models_not_under_observation_stay_clean(name):
    """A model must never end up in trial mode by accident."""
    assert "diagnostics" not in manifest(name)


@pytest.mark.parametrize("name", ["hard_hat", "safety_vest", "gloves"])
def test_without_diagnostics_predict_floor_is_the_rule_floor(plugin_with, name):
    mod = plugin_with(name, drop_diagnostics)
    mod.infer(FRAME)
    rule_floor = min(r["min_confidence"] for r in manifest(name)["rules"])
    assert FakeYOLO.instances[-1].calls[-1]["conf"] == rule_floor


@pytest.mark.parametrize("name", ["hard_hat", "safety_vest", "gloves"])
def test_without_diagnostics_nothing_is_logged(plugin_with, name, caplog):
    mod = plugin_with(name, drop_diagnostics)
    FakeYOLO.next_rows = [[400, 60, 450, 120, 0.95, 1], [10, 10, 20, 20, 0.90, 0]]
    with caplog.at_level("INFO"):
        mod.infer(FRAME)
    assert "Store detection summary" not in caplog.text


LEGACY_OUTPUT = json.loads((HERE / "legacy_output.json").read_text())
LEGACY_ROWS = [
    [400, 60, 450, 120, 0.95, 1],
    [10, 10, 20, 20, 0.90, 0],
    [500, 70, 560, 130, 0.60, 1],
]


@pytest.mark.parametrize("name", ["hard_hat", "safety_vest", "gloves"])
def test_without_diagnostics_output_is_byte_identical_to_the_legacy_plugin(
    plugin_with, name
):
    """The real guarantee: trial mode changes nothing for the other models.

    Trial mode ships to all four models at once, because every installed
    model gets a copy of this one file. So "it only affects goggles" has to
    be proved rather than asserted.

    `legacy_output.json` was generated from the plugin as it stood before
    trial mode existed (commit 8c04049), and is compared byte for byte
    against what this plugin produces now. A golden file rather than a
    `git show`: the git version passes trivially once this change is
    committed, which is exactly when the guarantee stops being checked.

    The two documented additions (`detection_count` and
    `metadata.class_summary`) are removed before comparing; everything else
    must serialise identically.
    """
    FakeYOLO.next_rows = list(LEGACY_ROWS)
    new_out = plugin_with(name, drop_diagnostics).infer(FRAME)

    new_out.pop("detection_count")
    new_out["metadata"].pop("class_summary")
    # Wall-clock, so it differs between two runs of identical code. Assert
    # it is still reported, then drop it from the comparison.
    assert isinstance(new_out["metadata"].pop("inference_ms"), float)

    assert json.dumps(new_out, sort_keys=True) == json.dumps(
        LEGACY_OUTPUT[name], sort_keys=True
    )


def test_legacy_golden_covers_the_interesting_paths():
    """Guards the guard: a golden of empty results would prove nothing."""
    for name, out in LEGACY_OUTPUT.items():
        assert out["objects"], name
        assert out["metadata"]["rules_active"], name
    # at least one model must actually fire on the golden rows
    assert any(o["violation_detected"] for o in LEGACY_OUTPUT.values())


# --- what trial mode adds --------------------------------------------------


def test_diagnostics_lowers_only_the_predict_floor(plugin_with):
    mod = plugin_with("goggles", add_diagnostics)
    mod.infer(FRAME)
    assert FakeYOLO.instances[-1].calls[-1]["conf"] == 0.01


def test_overlay_still_uses_the_rule_floor(plugin_with):
    """Sub-threshold boxes reach the summary but never the operator."""
    mod = plugin_with("goggles", add_diagnostics)
    FakeYOLO.next_rows = [
        [10, 10, 20, 20, 0.80, 1],   # above the 0.7 rule floor
        [30, 30, 40, 40, 0.08, 1],   # visible only because of predict_floor
        [50, 50, 60, 60, 0.03, 0],
    ]
    out = mod.infer(FRAME)
    assert [o["confidence"] for o in out["objects"]] == [0.80]
    assert out["detection_count"] == 1
    assert out["metadata"]["scored_count"] == 3
    assert out["metadata"]["class_summary"] == {
        "no-goggles": {"n": 2, "max_confidence": 0.80},
        "goggles": {"n": 1, "max_confidence": 0.03},
    }


def test_violations_unchanged_by_the_lowered_floor(plugin_with):
    """A rule fires on exactly the boxes it would have fired on at 0.25."""
    rows = [
        [10, 10, 20, 20, 0.80, 1],
        [30, 30, 40, 40, 0.08, 1],
        [50, 50, 60, 60, 0.03, 1],
    ]
    FakeYOLO.next_rows = list(rows)
    plain = plugin_with("goggles", drop_diagnostics, tag="plain").infer(FRAME)
    FakeYOLO.next_rows = list(rows)
    trial = plugin_with("goggles", add_diagnostics, tag="trial").infer(FRAME)

    for key in ("violation_detected", "violation_type", "severity", "confidence"):
        assert trial[key] == plain[key], key
    assert trial["detections"] == plain["detections"]
    assert trial["violation_detected"] is True and trial["confidence"] == pytest.approx(0.80)


def test_sub_threshold_only_still_reports_no_violation(plugin_with):
    """The goggles case: the model sees something, but nothing rule-worthy."""
    mod = plugin_with("goggles", add_diagnostics)
    FakeYOLO.next_rows = [[30, 30, 40, 40, 0.08, 1], [50, 50, 60, 60, 0.12, 0]]
    out = mod.infer(FRAME)
    assert out["violation_detected"] is False
    assert out["objects"] == [] and out["detection_count"] == 0
    assert out["metadata"]["class_summary"]["no-goggles"]["max_confidence"] == 0.08


def test_summary_carries_the_camera_from_config(plugin_with, caplog):
    """`config` is the only per-camera channel the plugin is given."""
    mod = plugin_with("goggles", add_diagnostics)
    FakeYOLO.next_rows = [[30, 30, 40, 40, 0.08, 1]]
    with caplog.at_level("INFO"):
        mod.infer(FRAME, config={"camera_name": "75096"})
    rec = next(r for r in caplog.records if r.message == "Store detection summary")
    assert rec.camera_name == "75096"


def test_summary_camera_is_unknown_without_config(plugin_with, caplog):
    """A trial on a camera nobody labelled must still log, not crash."""
    mod = plugin_with("goggles", add_diagnostics)
    FakeYOLO.next_rows = [[30, 30, 40, 40, 0.08, 1]]
    with caplog.at_level("INFO"):
        mod.infer(FRAME)
    rec = next(r for r in caplog.records if r.message == "Store detection summary")
    assert rec.camera_name == "unknown"


def test_camera_name_in_config_does_not_disturb_rules(plugin_with):
    """config is also where zones live; an extra key must be inert."""
    rows = [[10, 10, 20, 20, 0.95, 1]]
    FakeYOLO.next_rows = list(rows)
    plain = plugin_with("goggles", tag="a").infer(FRAME)
    FakeYOLO.next_rows = list(rows)
    labelled = plugin_with("goggles", tag="b").infer(FRAME, config={"camera_name": "75096"})
    for k in ("violation_detected", "violation_type", "confidence", "detections", "objects"):
        assert labelled[k] == plain[k], k


def test_summary_is_logged_under_trial_mode(plugin_with, caplog):
    mod = plugin_with("goggles", add_diagnostics)
    FakeYOLO.next_rows = [[30, 30, 40, 40, 0.08, 1]]
    with caplog.at_level("INFO"):
        mod.infer(FRAME)
    rec = next(r for r in caplog.records if r.message == "Store detection summary")
    assert rec.model_id == "goggles"
    assert rec.predict_floor == 0.01
    assert rec.rule_floor == manifest("goggles")["rules"][0]["min_confidence"]
    assert rec.scored_count == 1 and rec.detection_count == 0
    assert rec.violation_detected is False


def test_sample_rate_zero_logs_nothing(plugin_with, caplog):
    def mutate(m):
        m["diagnostics"] = {"summary_log_sample": 0.0, "predict_floor": 0.01}

    mod = plugin_with("goggles", mutate)
    FakeYOLO.next_rows = [[30, 30, 40, 40, 0.08, 1]]
    with caplog.at_level("INFO"):
        mod.infer(FRAME)
    assert "Store detection summary" not in caplog.text
    # ...but the floor is still lowered: the two knobs are independent.
    assert FakeYOLO.instances[-1].calls[-1]["conf"] == 0.01


def test_predict_floor_cannot_be_raised_above_the_rule_floor(plugin_with):
    """A floor above min_confidence would silently stop violations firing."""
    def mutate(m):
        m["diagnostics"] = {"predict_floor": 0.9}

    mod = plugin_with("goggles", mutate)
    mod.infer(FRAME)
    assert FakeYOLO.instances[-1].calls[-1]["conf"] == manifest("goggles")["rules"][0]["min_confidence"]


def test_detection_count_matches_objects(plugin_with):
    mod = plugin_with("safety_vest")
    FakeYOLO.next_rows = [[10, 10, 20, 20, 0.9, 0], [30, 30, 40, 40, 0.8, 1]]
    out = mod.infer(FRAME)
    assert out["detection_count"] == len(out["objects"]) == 2


# --------------------------------------------------------------------------
# Greyscale / infrared detection
#
# Confined-space cameras switch to IR at night. Those frames are three
# channels wide but visually grey, and a model trained on daylight colour
# can behave completely differently on them — so the trial summary has to
# be splittable by it, and the split has to be right.
# --------------------------------------------------------------------------


def _grey_frame(value=120):
    return np.full((720, 1280, 3), value, dtype=np.uint8)


def _colour_frame():
    f = np.zeros((720, 1280, 3), dtype=np.uint8)
    f[:, :, 0] = 200   # B
    f[:, :, 1] = 60    # G
    f[:, :, 2] = 20    # R
    return f


def test_flat_grey_frame_is_greyscale(plugin_with, caplog):
    mod = plugin_with("goggles", add_diagnostics)
    with caplog.at_level("INFO"):
        mod.infer(_grey_frame())
    rec = next(r for r in caplog.records if r.message == "Store detection summary")
    assert rec.greyscale is True
    assert rec.channel_spread == 0.0


def test_saturated_colour_frame_is_not_greyscale(plugin_with, caplog):
    mod = plugin_with("goggles", add_diagnostics)
    with caplog.at_level("INFO"):
        mod.infer(_colour_frame())
    rec = next(r for r in caplog.records if r.message == "Store detection summary")
    assert rec.greyscale is False
    assert rec.channel_spread > 100


def test_true_ir_is_bit_exact_grey(plugin_with, caplog):
    """What a real IR stream looks like: luma copied into all channels."""
    mod = plugin_with("goggles", add_diagnostics)
    with caplog.at_level("INFO"):
        mod.infer(_grey_frame(90))
    rec = next(r for r in caplog.records if r.message == "Store detection summary")
    assert rec.channel_spread == 0.0 and rec.greyscale is True


def test_slight_chroma_noise_still_reads_greyscale(plugin_with, caplog):
    """Headroom for a stream that re-encodes, without reaching a grey scene."""
    rng = np.random.default_rng(0)
    f = np.full((720, 1280, 3), 110, dtype=np.int16)
    f += rng.integers(-1, 2, size=f.shape)
    mod = plugin_with("goggles", add_diagnostics)
    with caplog.at_level("INFO"):
        mod.infer(np.clip(f, 0, 255).astype(np.uint8))
    rec = next(r for r in caplog.records if r.message == "Store detection summary")
    assert 0 < rec.channel_spread <= mod.GREYSCALE_TOLERANCE
    assert rec.greyscale is True


def test_grey_painted_scene_is_not_infrared(plugin_with, caplog):
    """Camera 75104: a colour camera pointed at a grey-painted scene.

    It read 5.5 and the first threshold (6.0) wrongly called it IR. A low
    channel spread means "little colour in this picture", which is not
    the question being asked — only night-mode IR is a domain shift for
    the model.
    """
    rng = np.random.default_rng(1)
    f = np.full((720, 1280, 3), 128, dtype=np.int16)
    f[:, :, 0] += rng.integers(0, 12, size=f.shape[:2])
    mod = plugin_with("goggles", add_diagnostics)
    with caplog.at_level("INFO"):
        mod.infer(np.clip(f, 0, 255).astype(np.uint8))
    rec = next(r for r in caplog.records if r.message == "Store detection summary")
    assert rec.channel_spread > mod.GREYSCALE_TOLERANCE
    assert rec.greyscale is False


def test_tolerance_sits_in_the_observed_fleet_gap():
    """Guards the calibration, not just the code.

    The fleet shows two populations: IR at exactly 0.0, and everything
    else at 5.3 or above. Raising the tolerance back through that gap
    would re-label a grey scene as infrared and silently mix two
    different things in the trial report.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("tol_probe", PLUGIN_SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
    spec.loader.exec_module(mod)
    assert 0 < mod.GREYSCALE_TOLERANCE < mod._OBSERVED_GREY_SCENE_SPREAD


def test_greyscale_costs_nothing_when_not_in_trial(plugin_with, caplog):
    """The spread is only computed for the summary line."""
    mod = plugin_with("hard_hat", drop_diagnostics)
    with caplog.at_level("INFO"):
        out = mod.infer(_colour_frame())
    assert "Store detection summary" not in caplog.text
    assert "channel_spread" not in out["metadata"]


def test_channel_spread_handles_a_single_channel_frame():
    """Defensive: never raise inside the logging path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cs_probe", PLUGIN_SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
    spec.loader.exec_module(mod)
    assert mod._channel_spread(np.zeros((10, 10), dtype=np.uint8)) == 0.0
    assert mod._channel_spread(np.zeros((10, 10, 1), dtype=np.uint8)) == 0.0


def test_harness_class_name_matches_the_weights_exactly():
    """`no harness` has a SPACE where every other model uses a hyphen.

    The rule's class list is matched against the manifest's own class
    names, and the installer checks those against the weights. Writing
    `no-harness` here would pass neither, but the failure mode worth
    guarding is the one that passes validation and never fires.
    """
    m = manifest("harness")
    assert m["classes"] == {"0": "harness", "1": "no harness"}
    assert m["rules"][0]["classes"] == ["no harness"]
    assert set(m["rules"][0]["classes"]) <= set(m["classes"].values())

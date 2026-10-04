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
    mod = plugin("hard_hat")
    FakeYOLO.next_rows = [[400, 60, 450, 120, 0.49, 1]]
    out = mod.infer(FRAME)
    assert out["violation_detected"] is False
    assert out["objects"] == []  # filtered by the predict conf floor (0.5)


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
    assert yolo.calls[0]["conf"] == 0.5
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


@pytest.mark.parametrize("name", ["hard_hat", "safety_vest", "gloves"])
def test_shipped_manifests_are_valid(name):
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

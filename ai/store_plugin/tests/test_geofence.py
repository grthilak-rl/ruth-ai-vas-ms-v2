"""Zone rules and the geofence manifest (the store replacement for the
built-in geo_fencing model).

The guarantee under test is parity: on the same detections and zones, the
store rule makes exactly the decision the built-in model made, as recorded
by the backend (0.7 session gate). The built-in's polygon test and frame
logic are imported from its own file, enabled or moved under
models/.disabled/ for its last release, so this keeps checking against the
real thing for as long as that file exists.

The shipped manifest anchors on the box's bottom-centre (feet); the
built-in used the box centre. Parity is checked on the manifest with the
centre anchor put back (`centre_manifest`), the rule that was proven
against the built-in; the anchor change is a deliberate difference,
pinned on its own below.

Also pinned: the new zone settings are off by default (so existing zone
rules are unchanged), normalised zones, and the `predict` block.
"""

import copy
import importlib.util
import json
import random
import sys
import types
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
PLUGIN_SRC = HERE.parent / "inference.py"
MANIFESTS = HERE.parent / "manifests"
OLD_MODEL = next(
    (
        p
        for p in (
            HERE.parents[1] / "models" / "geo_fencing" / "1.0.0" / "inference.py",
            HERE.parents[1] / "models" / ".disabled" / "geo_fencing" / "1.0.0" / "inference.py",
        )
        if p.is_file()
    ),
    HERE.parents[1] / "models" / "geo_fencing" / "1.0.0" / "inference.py",
)
SESSION_THRESHOLD = 0.7  # the backend gate built-in models were recorded at
FRAME = (1080, 1920, 3)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest():
    return json.loads((MANIFESTS / "geofence.json").read_text())


def centre_manifest():
    """The shipped manifest with the built-in's centre anchor: the parity baseline."""
    m = manifest()
    for rule in m["rules"]:
        rule["zone_anchor"] = "center"
    return m


@pytest.fixture(scope="module")
def rules_mod():
    return _load(PLUGIN_SRC, "store_zone_rules")


@pytest.fixture(scope="module")
def old():
    if not OLD_MODEL.is_file():
        pytest.skip("built-in geo_fencing removed; parity was proven while it existed")
    return _load(OLD_MODEL, "builtin_geo_fencing_inference")


@pytest.fixture(scope="module")
def ie():
    return _load(HERE.parent / "install_enabled.py", "install_enabled_zones")


# --------------------------------------------------------------------------
# Polygons and people
# --------------------------------------------------------------------------


def _polygon(rng):
    """3-8 vertices: integer pixels (so horizontal and vertical edges and
    exact on-edge points are common) or arbitrary floats."""
    n = rng.randint(3, 8)
    if rng.random() < 0.6:
        cx, cy, r = rng.randint(100, 1800), rng.randint(100, 1000), rng.randint(20, 600)
        return [[cx + rng.randint(-r, r), cy + rng.randint(-r, r)] for _ in range(n)]
    return [[rng.uniform(0, 1920), rng.uniform(0, 1080)] for _ in range(n)]


def _point(rng, polygon):
    """Random, or exactly on a vertex, an edge midpoint, or a vertex's row."""
    roll = rng.random()
    if roll < 0.2:
        return tuple(rng.choice(polygon))
    if roll < 0.4:
        a, b = rng.sample(polygon, 2)
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if roll < 0.5:
        v = rng.choice(polygon)
        return (rng.uniform(0, 1920), v[1])
    return (rng.uniform(0, 1920), rng.uniform(0, 1080))


# --------------------------------------------------------------------------
# Parity: the polygon test
# --------------------------------------------------------------------------


def test_legacy_ray_cast_matches_builtin(rules_mod, old):
    rng = random.Random(20261119)
    mismatches = []
    for _ in range(100_000):
        poly = _polygon(rng)
        x, y = _point(rng, poly)
        if old._point_in_polygon((x, y), poly) != rules_mod._legacy_ray_cast(x, y, poly):
            mismatches.append((x, y, poly))
    assert mismatches == []


def test_standard_and_legacy_tests_differ_only_on_boundaries(rules_mod):
    """Why `zone_point_test` exists: off the boundary they agree."""
    rng = random.Random(7)
    for _ in range(20_000):
        poly = [[rng.uniform(0, 1920), rng.uniform(0, 1080)] for _ in range(rng.randint(3, 8))]
        x, y = rng.uniform(0, 1920), rng.uniform(0, 1080)
        assert rules_mod._legacy_ray_cast(x, y, poly) == rules_mod._point_in_polygon(x, y, poly)


# --------------------------------------------------------------------------
# Parity: the whole frame, as the backend records it
# --------------------------------------------------------------------------


class _Arr:
    def __init__(self, a):
        self.a = np.asarray(a, dtype=float)

    def cpu(self):
        return self

    def numpy(self):
        return self.a


class _OldModel:
    """What the built-in calls: model(frame, conf, iou, classes, verbose)."""

    def __init__(self, rows):
        self.rows = rows

    def __call__(self, frame, conf, iou, classes, verbose):
        rows = [r for r in self.rows if r[4] >= conf]
        return [types.SimpleNamespace(boxes=_OldBoxes(rows))]


class _OldBoxes:
    """result.boxes as the built-in reads it: xyxy, conf, and len()."""

    def __init__(self, rows):
        self.xyxy = _Arr([r[:4] for r in rows] or np.zeros((0, 4)))
        self.conf = _Arr([r[4] for r in rows])
        self._n = len(rows)

    def __len__(self):
        return self._n


def _people(rng, polygons):
    """Persons around and inside the zones, confidences either side of 0.7."""
    rows = []
    for _ in range(rng.randint(0, 6)):
        if polygons and rng.random() < 0.6:
            cx, cy = _point(rng, rng.choice(polygons))
        else:
            cx, cy = rng.uniform(0, 1920), rng.uniform(0, 1080)
        w, h = rng.uniform(10, 300), rng.uniform(20, 600)
        conf = rng.choice([0.3, 0.5, 0.69999, 0.7, 0.70001, 0.85, 0.86, rng.uniform(0.3, 1.0)])
        rows.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, conf])
    return rows


def _old_recorded(old, rows, zones, monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.5)  # never its 1% debug-frame dump
    out = old._run_inference_with_model(np.zeros(FRAME, np.uint8), _OldModel(rows), zones,
                                        {"conf_threshold": 0.3, "iou_threshold": 0.5})
    if not out["violation_detected"] or out["confidence"] < SESSION_THRESHOLD:
        return None
    return out["violation_type"], round(out["confidence"], 9)


def _new_recorded(rules_mod, rows, zones, frame=FRAME):
    m = centre_manifest()
    floor = min(r["min_confidence"] for r in m["rules"])  # the plugin's predict floor
    objects = [
        {"bbox": r[:4], "confidence": r[4], "class_id": 0, "class_name": "person", "violation": False}
        for r in rows if r[4] >= floor
    ]
    out = rules_mod.apply_rules(objects, m, {"zones": zones}, frame_shape=frame)
    if not out["violation_detected"]:
        return None
    return out["violation_type"], round(out["confidence"], 9)


@pytest.mark.parametrize("layout", ["one_restricted", "one_allowed", "two_restricted", "two_allowed"])
def test_frame_decision_matches_builtin_plus_backend_gate(rules_mod, old, layout, monkeypatch):
    """Same zone type throughout (the editor saves one zone). With mixed
    types the built-in assigns each person one zone across both types, the
    store fires one rule per type; documented, not reachable from the UI."""
    rng = random.Random(hash(layout) & 0xFFFF)
    zone_type = "restricted" if "restricted" in layout else "allowed"
    n_zones = 2 if layout.startswith("two") else 1
    outcomes = set()
    for _ in range(5_000):
        polygons = [_polygon(rng) for _ in range(n_zones)]
        zones = [{"id": f"z{i}", "name": f"Z{i}", "type": zone_type, "points": p}
                 for i, p in enumerate(polygons)]
        rows = _people(rng, polygons)
        old_d = _old_recorded(old, rows, zones, monkeypatch)
        new_d = _new_recorded(rules_mod, rows, zones)
        assert old_d == new_d, (rows, zones)
        outcomes.add(old_d[0] if old_d else None)
    assert outcomes == {None, "zone_intrusion" if zone_type == "restricted" else "zone_exit"}


def test_firing_zone_id_matches_builtin(rules_mod, old, monkeypatch):
    """The backend opens a new violation when a person enters a new zone,
    keyed on zone_id: it must be the zone the built-in reported."""
    rng = random.Random(42)
    checked = 0
    for _ in range(3_000):
        polygons = [_polygon(rng) for _ in range(2)]
        zones = [{"id": f"z{i}", "type": "restricted", "points": p} for i, p in enumerate(polygons)]
        rows = [r for r in _people(rng, polygons) if r[4] >= 0.7]
        monkeypatch.setattr(random, "random", lambda: 0.5)
        old_out = old._run_inference_with_model(np.zeros(FRAME, np.uint8), _OldModel(rows), zones, {})
        objects = [{"bbox": r[:4], "confidence": r[4], "class_id": 0, "class_name": "person",
                    "violation": False} for r in rows]
        new_out = rules_mod.apply_rules(objects, centre_manifest(), {"zones": zones}, frame_shape=FRAME)
        old_zones = [d["zone_id"] for d in old_out["detections"] if d["in_zone"]]
        new_zones = [d["zone_id"] for d in new_out["detections"]]
        assert old_zones == new_zones
        checked += bool(old_zones)
    assert checked > 100


def test_normalised_zones_decide_as_their_pixel_equivalent(rules_mod, old, monkeypatch):
    """The editor saves normalised points; the plugin scales them to the
    frame. Off exact boundaries the decision is the pixel decision."""
    rng = random.Random(99)
    for frame in (FRAME, (1520, 2688, 3), (720, 1280, 3)):
        h, w = frame[0], frame[1]
        for _ in range(2_000):
            polygon = [[rng.uniform(0, w), rng.uniform(0, h)] for _ in range(rng.randint(3, 7))]
            pixel = [{"id": "z", "type": "restricted", "points": polygon}]
            normal = [{"id": "z", "type": "restricted", "coords": "normalized",
                       "points": [[x / w, y / h] for x, y in polygon]}]
            rows = []
            for _ in range(rng.randint(0, 5)):
                cx, cy = rng.uniform(0, w), rng.uniform(0, h)
                rows.append([cx - 20, cy - 40, cx + 20, cy + 40, rng.uniform(0.5, 1.0)])
            assert _new_recorded(rules_mod, rows, pixel, frame) == _new_recorded(rules_mod, rows, normal, frame)


def test_normalised_zone_needs_the_frame_shape(rules_mod):
    zones = [{"id": "z", "type": "restricted", "coords": "normalized", "points": [[0, 0], [1, 0], [1, 1]]}]
    obj = {"bbox": [10, 10, 50, 90], "confidence": 0.9, "class_id": 0, "class_name": "person", "violation": False}
    with pytest.raises(ValueError, match="frame shape"):
        rules_mod.apply_rules([obj], manifest(), {"zones": zones})


# --------------------------------------------------------------------------
# The zone settings, one at a time
# --------------------------------------------------------------------------

SQUARE = [[100, 100], [500, 100], [500, 500], [100, 500]]


def _rule(**settings):
    return {"id": "r", "classes": ["person"], "min_confidence": 0.5, "requires_zone": "restricted",
            "violation_type": "zone_intrusion", "severity": "high", **settings}


def _fires(rules_mod, rule, bbox, zones=None):
    m = {"rules": [rule]}
    obj = {"bbox": bbox, "confidence": 0.9, "class_id": 0, "class_name": "person", "violation": False}
    zones = zones if zones is not None else [{"id": "z", "type": "restricted", "points": SQUARE}]
    return rules_mod.apply_rules([obj], m, {"zones": zones}, frame_shape=FRAME)["violation_detected"]


def test_default_anchor_is_bottom_centre(rules_mod):
    standing_on_edge = [280, 300, 320, 520]  # centre inside, feet outside
    assert _fires(rules_mod, _rule(), standing_on_edge) is False
    assert _fires(rules_mod, _rule(zone_anchor="center"), standing_on_edge) is True


def test_zone_test_outside_fires_when_the_person_leaves(rules_mod):
    rule = _rule(zone_test="outside", requires_zone="allowed", violation_type="zone_exit")
    allowed = [{"id": "a", "type": "allowed", "points": SQUARE}]
    assert _fires(rules_mod, rule, [280, 200, 320, 300], allowed) is False   # inside
    assert _fires(rules_mod, rule, [700, 200, 740, 300], allowed) is True    # outside


def test_outside_rule_with_no_zone_of_its_type_never_fires(rules_mod):
    """Fails closed: no allowed zone drawn means no zone_exit at all."""
    rule = _rule(zone_test="outside", requires_zone="allowed", violation_type="zone_exit")
    assert _fires(rules_mod, rule, [700, 200, 740, 300], zones=[]) is False


def test_point_test_setting_selects_the_legacy_polygon_test(rules_mod):
    # A box whose bottom-centre sits exactly on the square's right edge.
    on_edge = [480, 300, 520, 500]
    standard = _fires(rules_mod, _rule(), on_edge)
    legacy = _fires(rules_mod, _rule(zone_point_test="legacy_ray_cast"), on_edge)
    assert legacy == rules_mod._legacy_ray_cast(500, 500, SQUARE)
    assert standard == rules_mod._point_in_polygon(500, 500, SQUARE)


# --------------------------------------------------------------------------
# predict: iou and classes
# --------------------------------------------------------------------------


class FakeYOLO:
    calls = []

    def __init__(self, weights):
        pass

    def predict(self, frame, **kwargs):
        FakeYOLO.calls.append(kwargs)
        return [types.SimpleNamespace(boxes=types.SimpleNamespace(
            xyxy=_Arr(np.zeros((0, 4))), conf=_Arr([]), cls=_Arr([])))]


def _plugin(tmp_path, monkeypatch, m, tag):
    d = tmp_path / tag / "1.0.0"
    (d / "weights").mkdir(parents=True)
    (d / "weights" / m["weights"]).write_bytes(b"x")
    (d / "store_manifest.json").write_text(json.dumps(m))
    (d / "inference.py").write_text(PLUGIN_SRC.read_text())
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
    return _load(d / "inference.py", f"store_{tag}_inference")


def test_geofence_predicts_persons_only_at_iou_0_5(tmp_path, monkeypatch):
    FakeYOLO.calls.clear()
    _plugin(tmp_path, monkeypatch, manifest(), "geofence").infer(np.zeros(FRAME, np.uint8))
    call = FakeYOLO.calls[-1]
    assert call["classes"] == [0] and call["iou"] == 0.5 and call["imgsz"] == 640 and call["conf"] == 0.7


def test_no_predict_block_leaves_predict_args_unchanged(tmp_path, monkeypatch):
    FakeYOLO.calls.clear()
    m = json.loads((MANIFESTS / "hard_hat.json").read_text())
    _plugin(tmp_path, monkeypatch, m, "hard_hat").infer(np.zeros(FRAME, np.uint8))
    assert "classes" not in FakeYOLO.calls[-1] and "iou" not in FakeYOLO.calls[-1]


# --------------------------------------------------------------------------
# The manifest and the installer
# --------------------------------------------------------------------------


def test_geofence_manifest_is_the_builtin_behaviour_but_anchored_on_feet():
    m = manifest()
    assert m["model_id"] == "geofence" and m["weights"] == "yolov8n.pt" and m["imgsz"] == 640
    assert m["predict"] == {"iou": 0.5, "classes": ["person"]}
    assert len(m["classes"]) == 80 and m["classes"]["0"] == "person"
    rules = {r["id"]: r for r in m["rules"]}
    assert rules["intrusion"] == {
        "id": "intrusion", "classes": ["person"], "min_confidence": 0.7, "requires_zone": "restricted",
        "zone_anchor": "bottom_center", "zone_point_test": "legacy_ray_cast",
        "violation_type": "zone_intrusion", "severity": "high"}
    assert rules["exit"] == {
        "id": "exit", "classes": ["person"], "min_confidence": 0.7, "requires_zone": "allowed",
        "zone_test": "outside", "zone_anchor": "bottom_center", "zone_point_test": "legacy_ray_cast",
        "violation_type": "zone_exit", "severity": "medium"}


def test_geofence_anchor_is_the_feet_a_deliberate_difference_from_the_builtin(rules_mod):
    """Both rules test the box's bottom-centre. A person whose body
    overlaps a zone but who stands outside it: the built-in (centre) fired
    intrusion, geofence does not; for an allowed zone, the built-in did not
    fire exit, geofence does."""
    standing_below = [280, 300, 320, 520]  # centre (300, 410) inside SQUARE, feet (300, 520) outside
    obj = {"bbox": standing_below, "confidence": 0.9, "class_id": 0, "class_name": "person", "violation": False}
    restricted = {"zones": [{"id": "r", "type": "restricted", "points": SQUARE}]}
    allowed = {"zones": [{"id": "a", "type": "allowed", "points": SQUARE}]}

    def decide(m, cfg):
        out = rules_mod.apply_rules([dict(obj)], m, cfg, frame_shape=FRAME)
        return out["violation_type"] if out["violation_detected"] else None

    assert decide(manifest(), restricted) is None
    assert decide(centre_manifest(), restricted) == "zone_intrusion"
    assert decide(manifest(), allowed) == "zone_exit"
    assert decide(centre_manifest(), allowed) is None

    feet_inside = [280, 200, 320, 400]  # feet (300, 400) inside
    obj["bbox"] = feet_inside
    assert decide(manifest(), restricted) == "zone_intrusion"
    assert decide(manifest(), allowed) is None


def test_geofence_manifest_is_valid(ie):
    assert ie.manifest_problems(manifest()) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda m: m["rules"][0].update(zone_anchor="feet"), "zone_anchor must be one of"),
        (lambda m: m["rules"][0].update(zone_test="near"), "zone_test must be one of"),
        (lambda m: m["rules"][0].update(zone_point_test="winding"), "zone_point_test must be one of"),
        (lambda m: (m["rules"][0].pop("requires_zone"), m["rules"][0].update(zone_anchor="center")),
         "zone_anchor needs requires_zone"),
        (lambda m: m["predict"].update(iou=0), "predict.iou"),
        (lambda m: m["predict"].update(classes=["unicorn"]), "not in the model's classes"),
        (lambda m: m["predict"].update(classes=["car"]), "leaves out ['person']"),
        (lambda m: m["predict"].update(classes=[]), "non-empty list"),
        (lambda m: m["predict"].update(agnostic=True), "optional iou and classes"),
    ],
)
def test_zone_and_predict_problems_caught(ie, mutate, expected):
    m = manifest()
    mutate(m)
    assert expected in " | ".join(ie.manifest_problems(m))


def test_predict_block_rejected_on_pose_models(ie):
    m = json.loads((MANIFESTS / "fall_pose.json").read_text())
    m["predict"] = {"iou": 0.5}
    assert "predict is for detect models" in " | ".join(ie.manifest_problems(m))

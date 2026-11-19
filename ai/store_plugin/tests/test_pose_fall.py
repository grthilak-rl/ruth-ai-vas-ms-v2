"""Pose task and the pose_fall rule (fall_pose, the store replacement for the
built-in fall_detection model).

The guarantee under test is parity: on the same keypoints, the store rule
makes exactly the decision the built-in model's heuristic made. The old
heuristic is imported from the built-in model's own file rather than copied,
so this keeps checking against the real thing for as long as that file
exists (it is kept, disabled, for one release).
"""

import importlib.util
import io
import json
import pickle
import random
import sys
import types
import zipfile
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
PLUGIN_SRC = HERE.parent / "inference.py"
MANIFESTS = HERE.parent / "manifests"
#: The built-in model, enabled or (after the switch, for one release) moved
#: under models/.disabled/, which the unified runtime's discovery skips.
OLD_MODEL = next(
    (
        p
        for p in (
            HERE.parents[1] / "models" / "fall_detection" / "1.0.0" / "inference.py",
            HERE.parents[1] / "models" / ".disabled" / "fall_detection" / "1.0.0" / "inference.py",
        )
        if p.is_file()
    ),
    HERE.parents[1] / "models" / "fall_detection" / "1.0.0" / "inference.py",
)

#: The session threshold the backend applied to built-in models (0.7 by
#: default); recorded = violation_detected and confidence >= this.
SESSION_THRESHOLD = 0.7


def manifest():
    return json.loads((MANIFESTS / "fall_pose.json").read_text())


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rules_mod():
    return _load(PLUGIN_SRC, "store_pose_rules")


@pytest.fixture(scope="module")
def old():
    if not OLD_MODEL.is_file():
        pytest.skip("built-in fall_detection removed; parity was proven while it existed")
    return _load(OLD_MODEL, "builtin_fall_inference")


# --------------------------------------------------------------------------
# Keypoint generators
# --------------------------------------------------------------------------

THRESHOLD_VALUES = [0.3, 0.29999, 0.30001, 0.0, 1.0]


def _person(rng, size=640.0):
    """17 keypoints with a mix of plausible and adversarial values.

    Coordinates are drawn so that every indicator threshold (50, 20, 100,
    150 px) is crossed often, and confidences sit on the 0.3 visibility edge
    a good share of the time."""
    kind = rng.random()
    cx, top = rng.uniform(0, size), rng.uniform(0, size)
    height = rng.choice([rng.uniform(20, 160), rng.uniform(150, 600)])
    out = []
    for i in range(17):
        if kind < 0.3:  # upright-ish body
            y = top + height * (i / 16.0) + rng.gauss(0, 8)
            x = cx + rng.gauss(0, height * 0.15)
        elif kind < 0.6:  # lying-ish body
            y = top + rng.gauss(0, 15)
            x = cx + height * (i / 16.0)
        else:  # noise
            x, y = rng.uniform(-50, size + 50), rng.uniform(-50, size + 50)
        conf = rng.choice(THRESHOLD_VALUES) if rng.random() < 0.3 else rng.random()
        out.append({"x": x, "y": y, "confidence": conf})
    return out


def _exact_boundary_people():
    """People built to land exactly on each strict comparison."""
    base = [{"x": 300.0, "y": 300.0, "confidence": 0.9} for _ in range(17)]

    def with_(**changes):
        p = [dict(k) for k in base]
        for idx, field, value in changes.values():
            p[idx][field] = value
        return p

    people = []
    # horizontal_body: |shoulder - hip| == 50 exactly (not < 50) and 49.999
    for dy in (50.0, 49.999, 50.001):
        people.append(with_(a=(5, "y", 300.0), b=(6, "y", 300.0), c=(11, "y", 300.0 + dy), d=(12, "y", 300.0 + dy)))
    # head_below_hips: nose == hip + 20 exactly
    for d in (20.0, 20.001):
        people.append(with_(a=(0, "y", 400.0 + d), b=(11, "y", 400.0), c=(12, "y", 400.0), e=(5, "y", 100.0), f=(6, "y", 100.0)))
    # legs_spread: ankle dx == 100 exactly
    for dx in (100.0, 100.001):
        people.append(with_(a=(15, "x", 100.0), b=(16, "x", 100.0 + dx)))
    # compact_body: exactly 10 visible (not > 10), and y span == 150
    p = [dict(k) for k in base]
    for k in p[10:]:
        k["confidence"] = 0.1
    people.append(p)
    for span in (150.0, 149.999):
        p = [dict(k) for k in base]
        p[0]["y"], p[16]["y"] = 300.0, 300.0 + span
        people.append(p)
    # visibility exactly 0.3 (not > 0.3) on every key point
    people.append([{"x": 300.0, "y": 300.0, "confidence": 0.3} for _ in range(17)])
    # nose only (shoulders and hips invisible): the shoulder/hip fallbacks
    p = [{"x": 300.0, "y": 300.0, "confidence": 0.0} for _ in range(17)]
    p[0]["confidence"] = 0.9
    people.append(p)
    # one shoulder only, nose invisible: shoulder_y falls back to 0
    p = [{"x": 300.0, "y": 30.0, "confidence": 0.0} for _ in range(17)]
    p[5]["confidence"] = 0.9
    people.append(p)
    return people


def _new_decision(rules_mod, m, keypoints):
    """(type, confidence) the store rule gives one person, in legacy space."""
    score, _ = rules_mod.pose_fall_score(keypoints, m["pose_fall"])
    bands = [r for r in m["rules"] if score > r["score_above"]]
    if not bands:
        return None, 0.0
    return max(bands, key=lambda r: r["score_above"])["violation_type"], score


def _old_decision(old, keypoints):
    is_fall, conf, ftype = old._analyze_pose_for_fall(keypoints)
    return (ftype, conf) if is_fall else (None, 0.0)


# --------------------------------------------------------------------------
# Parity: per person
# --------------------------------------------------------------------------


def test_rule_matches_builtin_heuristic_on_random_keypoints(rules_mod, old):
    m = manifest()
    rng = random.Random(20261119)
    seen = {}
    for _ in range(50_000):
        kp = _person(rng)
        new, ref = _new_decision(rules_mod, m, kp), _old_decision(old, kp)
        assert new == ref, kp
        seen[ref[0]] = seen.get(ref[0], 0) + 1
    # guard the guard: every outcome is exercised, not just "no fall"
    assert set(seen) == {None, "possible_fall", "fall_detected"}, seen
    assert min(seen.values()) > 1000, seen


def test_rule_matches_builtin_heuristic_on_exact_boundaries(rules_mod, old):
    m = manifest()
    outcomes = set()
    for kp in _exact_boundary_people():
        ref = _old_decision(old, kp)
        assert _new_decision(rules_mod, m, kp) == ref, kp
        outcomes.add(ref[0])
    # the edges are actually straddled, not all on one side
    assert outcomes == {None, "possible_fall", "fall_detected"}, outcomes


def test_manifest_constants_are_the_builtin_ones():
    """Migration, not calibration: the numbers are the old code's."""
    f = manifest()["pose_fall"]
    assert f["coords"] == "legacy_640"
    assert f["keypoint_min_confidence"] == 0.3
    assert f["missing_hip_offset"] == 100
    assert f["indicators"] == {
        "horizontal_body": {"shoulder_hip_dy_below": 50, "score": 0.8},
        "head_below_hips": {"nose_below_hip_by_more_than": 20, "score": 0.7},
        "legs_spread": {"ankle_dx_above": 100, "score": 0.6},
        "compact_body": {"visible_keypoints_above": 10, "y_span_below": 150, "score": 0.7},
    }
    m = manifest()
    # IoU is the old NMS setting. The person floor was the old 0.25 at
    # migration and is the one calibrated value so far: 0.45 on 2026-11-19
    # (BL-1 quick fix). The parity tests here feed keypoints directly, so
    # the floor (applied at predict time) does not enter them.
    assert m["pose"] == {"min_person_confidence": 0.45, "iou": 0.65}


# --------------------------------------------------------------------------
# Parity: per frame, as recorded by the backend
# --------------------------------------------------------------------------


def _old_frame(old, people_640):
    """The built-in model's frame decision, then the backend's 0.7 gate."""
    best_conf, best_type = 0.0, None
    for kp in people_640:
        is_fall, conf, ftype = old._analyze_pose_for_fall(kp)
        if is_fall and conf > best_conf:
            best_conf, best_type = conf, ftype
    if best_type is None or best_conf < SESSION_THRESHOLD:
        return None
    return best_type, best_conf, "critical"


def _to_frame(kp_640, shape):
    h, w = shape[0], shape[1]
    return [{"x": k["x"] * w / 640.0, "y": k["y"] * h / 640.0, "confidence": k["confidence"]} for k in kp_640]


@pytest.mark.parametrize("shape", [(720, 1280, 3), (1080, 1920, 3), (1520, 2688, 3), (640, 640, 3)])
def test_frame_decision_matches_builtin_plus_backend_gate(rules_mod, old, shape):
    m = manifest()
    rng = random.Random(shape[1])
    fired = 0
    for _ in range(4_000):
        people_frame = [_to_frame(_person(rng), shape) for _ in range(rng.randint(0, 4))]
        # What the old model saw is what the plugin converts back to.
        people_640 = [rules_mod.legacy_640_keypoints(kp, shape) for kp in people_frame]
        objects = [
            {"bbox": [0.0, 0.0, 10.0, 10.0], "confidence": 0.9, "class_id": 0,
             "class_name": "person", "violation": False, "keypoints": kp}
            for kp in people_frame
        ]
        out = rules_mod.apply_rules(objects, m, None, frame_shape=shape)
        ref = _old_frame(old, people_640)
        if ref is None:
            assert out["violation_detected"] is False
            continue
        fired += 1
        assert out["violation_detected"] is True
        assert (out["violation_type"], out["confidence"]) == ref[:2]
        # severity: fall stays critical; possible_fall is high (decided)
        assert out["severity"] == ("critical" if ref[0] == "fall_detected" else "high")
    assert fired > 300


def test_legacy_space_is_a_stretch_not_a_letterbox(rules_mod):
    kp = [{"x": 1280.0, "y": 720.0, "confidence": 0.5}]
    assert rules_mod.legacy_640_keypoints(kp, (720, 1280, 3)) == [{"x": 640.0, "y": 640.0, "confidence": 0.5}]


def test_possible_fall_at_0_6_is_not_a_violation(rules_mod):
    """legs_spread alone (0.6) was reported by the old model but never
    recorded: the backend's 0.7 session gate dropped it. The rule's
    min_confidence 0.7 keeps it unrecorded now that store models are gated
    on their manifest floor instead."""
    m = manifest()
    kp = [{"x": 300.0, "y": 100.0 + 25 * i, "confidence": 0.9} for i in range(17)]
    kp[15]["x"], kp[16]["x"] = 100.0, 400.0
    score, held = rules_mod.pose_fall_score(kp, m["pose_fall"])
    assert (score, held) == (0.6, ["legs_spread"])
    obj = {"bbox": [0, 0, 1, 1], "confidence": 0.9, "class_id": 0, "class_name": "person",
           "violation": False, "keypoints": kp}
    assert rules_mod.apply_rules([obj], m, None, frame_shape=(640, 640, 3))["violation_detected"] is False


def test_only_the_falling_person_goes_with_the_violation(rules_mod):
    m = manifest()
    lying = [{"x": 100.0 + 10 * i, "y": 300.0, "confidence": 0.9} for i in range(17)]
    upright = [{"x": 500.0, "y": 50.0 + 30 * i, "confidence": 0.9} for i in range(17)]
    objs = [
        {"bbox": [90, 280, 270, 320], "confidence": 0.8, "class_id": 0, "class_name": "person",
         "violation": False, "keypoints": lying},
        {"bbox": [480, 40, 520, 540], "confidence": 0.95, "class_id": 0, "class_name": "person",
         "violation": False, "keypoints": upright},
    ]
    out = rules_mod.apply_rules(objs, m, None, frame_shape=(640, 640, 3))
    assert out["violation_type"] == "fall_detected" and out["confidence"] == 0.8
    assert len(out["detections"]) == 1
    det = out["detections"][0]
    assert det["bbox"] == [90, 280, 270, 320] and det["confidence"] == 0.8  # person box conf
    assert det["score"] == 0.8 and "horizontal_body" in det["indicators"]
    assert det["label"] == "fall_detected" and det["rule_id"] == "fall"
    assert [o["violation"] for o in out["objects"]] == [True, False]


def test_unsupported_coords_raise(rules_mod):
    m = manifest()
    m["pose_fall"]["coords"] = "relative"
    obj = {"bbox": [0, 0, 1, 1], "confidence": 0.9, "class_id": 0, "class_name": "person",
           "violation": False, "keypoints": [{"x": 0, "y": 0, "confidence": 1}] * 17}
    with pytest.raises(ValueError, match="coords"):
        rules_mod.apply_rules([obj], m, None, frame_shape=(640, 640, 3))


# --------------------------------------------------------------------------
# infer() with a fake ultralytics pose model
# --------------------------------------------------------------------------


class _Arr:
    def __init__(self, a):
        self.a = np.asarray(a, dtype=float)

    def cpu(self):
        return self

    def numpy(self):
        return self.a


class FakePose:
    instances = []
    people = []  # [(bbox4, conf, [[x, y, c] * 17])]

    def __init__(self, weights):
        self.calls = []
        FakePose.instances.append(self)

    def predict(self, frame, **kwargs):
        self.calls.append(kwargs)
        rows = [p for p in FakePose.people if p[1] >= kwargs["conf"]]
        boxes = types.SimpleNamespace(
            xyxy=_Arr([r[0] for r in rows] or np.zeros((0, 4))),
            conf=_Arr([r[1] for r in rows]),
            cls=_Arr([0 for _ in rows]),
        )
        kps = types.SimpleNamespace(data=_Arr([r[2] for r in rows] or np.zeros((0, 17, 3))))
        return [types.SimpleNamespace(boxes=boxes, keypoints=kps)]


@pytest.fixture
def pose_plugin(tmp_path, monkeypatch):
    version_dir = tmp_path / "fall_pose" / "1.0.0"
    (version_dir / "weights").mkdir(parents=True)
    m = manifest()
    (version_dir / "weights" / m["weights"]).write_bytes(b"not a real model")
    (version_dir / "store_manifest.json").write_text(json.dumps(m))
    (version_dir / "inference.py").write_text(PLUGIN_SRC.read_text())
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakePose))
    FakePose.instances.clear()
    FakePose.people = []
    return _load(version_dir / "inference.py", "store_fall_pose_inference")


FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)


def _lying_person_frame_px():
    # horizontal in 640 space on a 1280x720 frame: shoulders and hips level
    return [[200.0 + 20 * i, 400.0, 0.9] for i in range(17)]


def test_infer_predicts_at_person_floor_and_old_nms_iou(pose_plugin):
    pose_plugin.infer(FRAME)
    call = FakePose.instances[-1].calls[-1]
    assert call["conf"] == 0.45 and call["iou"] == 0.65 and call["imgsz"] == 640


def test_infer_reports_a_fall(pose_plugin):
    FakePose.people = [
        ([180.0, 380.0, 560.0, 420.0], 0.6, _lying_person_frame_px()),
        ([900.0, 100.0, 960.0, 600.0], 0.2, _lying_person_frame_px()),  # below person floor
    ]
    out = pose_plugin.infer(FRAME)
    assert out["violation_detected"] is True
    assert out["violation_type"] == "fall_detected"
    assert out["severity"] == "critical"
    assert out["confidence"] == 0.8
    assert out["detection_count"] == 1
    assert len(out["objects"][0]["keypoints"]) == 17
    assert out["objects"][0]["keypoints"][0] == {"x": 200.0, "y": 400.0, "confidence": 0.9}
    assert out["metadata"]["task"] == "pose" and out["metadata"]["model_id"] == "fall_pose"
    assert out["detections"][0]["bbox"] == [180.0, 380.0, 560.0, 420.0]  # frame pixels


def test_infer_no_people_is_no_violation(pose_plugin):
    out = pose_plugin.infer(FRAME)
    assert out["violation_detected"] is False and out["objects"] == []


# --------------------------------------------------------------------------
# Installer
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ie():
    return _load(HERE.parent / "install_enabled.py", "install_enabled_pose")


def test_fall_pose_manifest_is_valid(ie):
    assert ie.manifest_problems(manifest()) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda m: m.update(task="segment"), "task must be one of"),
        (lambda m: m.pop("pose"), "pose must be an object"),
        (lambda m: m["pose"].update(min_person_confidence=0), "min_person_confidence"),
        (lambda m: m["pose"].update(iou=2), "pose.iou"),
        (lambda m: m.pop("pose_fall"), "pose_fall must be an object"),
        (lambda m: m["pose_fall"].update(coords="relative"), "coords"),
        (lambda m: m["pose_fall"]["indicators"].update(sitting={"score": 0.5}), "unknown indicator"),
        (lambda m: m["pose_fall"]["indicators"]["compact_body"].pop("y_span_below"), "y_span_below"),
        (lambda m: m["pose_fall"]["indicators"]["legs_spread"].update(score=0), "legs_spread.score"),
        (lambda m: m["rules"][0].pop("type"), "must be of type 'pose_fall'"),
        (lambda m: m["rules"][0].update(score_above=1), "score_above"),
        (lambda m: m["rules"][0].update(requires_zone="restricted"), "requires_zone"),
        (lambda m: m["rules"][0].update(classes=["no-gloves"]), "not in the model's classes"),
        (lambda m: m.update(model_id="fall_detection"), "built-in id"),
    ],
)
def test_pose_manifest_problems_caught(ie, mutate, expected):
    m = manifest()
    mutate(m)
    assert expected in " | ".join(ie.manifest_problems(m))


def test_pose_rule_on_a_detect_model_is_rejected(ie):
    m = json.loads((MANIFESTS / "hard_hat.json").read_text())
    m["rules"][0]["type"] = "pose_fall"
    assert "needs task 'pose'" in " | ".join(ie.manifest_problems(m))


def _fake_checkpoint(path, task, names):
    """A torch-zip-shaped file whose data.pkl holds only plain data, so the
    installer's restricted unpickler can read it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ckpt/data.pkl", pickle.dumps({"model": {"names": names, "task": task}, "train_args": {"imgsz": 640}}))
    path.write_bytes(buf.getvalue())


@pytest.mark.parametrize("task, ok", [("pose", True), ("detect", False)])
def test_check_matches_weights_task(ie, tmp_path, capsys, task, ok):
    m = manifest()
    w = tmp_path / "drafts" / "pk" / "weights"
    w.mkdir(parents=True)
    _fake_checkpoint(w / m["weights"], task, {0: "person"})
    mpath = tmp_path / "fall_pose.json"
    mpath.write_text(json.dumps(m))
    rc = ie.main(["--check", "--store-root", str(tmp_path), str(mpath)])
    out = capsys.readouterr().out
    assert (rc == 0) is ok, out
    if not ok:
        assert "weights task is 'detect', manifest says 'pose'" in out


def test_build_tree_for_pose(ie, tmp_path):
    m = manifest()
    (tmp_path / "drafts" / "pk" / "weights").mkdir(parents=True)
    (tmp_path / "drafts" / "pk" / "weights" / m["weights"]).write_bytes(b"x")
    ie.build(tmp_path, [m], tmp_path / "out")
    d = tmp_path / "out" / "fall_pose" / "1.0.0"
    contract = json.loads(d.joinpath("model.yaml").read_text().split("\n", 1)[1])
    assert contract["model_id"] == "fall_pose"
    assert "pose plugin" in contract["description"]
    assert json.loads(d.joinpath("store_manifest.json").read_text()) == m

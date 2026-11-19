"""Optional pose_fall settings for calibration (BL-1): person-relative
coordinates, the wide_box indicator, a minimum person size, and the
manifest's persistence block (applied by the backend; only validated here).

The release that adds them is behaviour-neutral: every setting is optional,
the shipped fall_pose manifest uses none of them, and the parity tests in
test_pose_fall.py (legacy_640 against the built-in heuristic) still pass.
These tests pin what each setting does once a manifest turns it on.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PLUGIN_SRC = HERE.parent / "inference.py"
MANIFESTS = HERE.parent / "manifests"
FRAME = (1080, 1920, 3)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rules_mod():
    return _load(PLUGIN_SRC, "store_pose_rules_options")


@pytest.fixture(scope="module")
def ie():
    return _load(HERE.parent / "install_enabled.py", "install_enabled_options")


def legacy_manifest():
    return json.loads((MANIFESTS / "fall_pose.json").read_text())


def relative_manifest():
    """fall_pose with BL-1's proposed size-relative thresholds."""
    m = legacy_manifest()
    m["pose_fall"].update(coords="person_relative", missing_hip_offset=0.15)
    ind = m["pose_fall"]["indicators"]
    ind["horizontal_body"]["shoulder_hip_dy_below"] = 0.15
    ind["head_below_hips"]["nose_below_hip_by_more_than"] = 0.05
    ind["legs_spread"]["ankle_dx_above"] = 0.5
    ind["compact_body"]["y_span_below"] = 0.35
    return m


# --------------------------------------------------------------------------
# People, in frame pixels
# --------------------------------------------------------------------------

# Standing pose as fractions of the box: (x offset from centre, y from top).
_STANDING = [
    (0.0, 0.05),                                  # nose
    (-0.02, 0.04), (0.02, 0.04), (-0.04, 0.05), (0.04, 0.05),  # eyes, ears
    (-0.1, 0.2), (0.1, 0.2),                      # shoulders
    (-0.13, 0.35), (0.13, 0.35), (-0.14, 0.48), (0.14, 0.48),  # elbows, wrists
    (-0.07, 0.5), (0.07, 0.5),                    # hips
    (-0.06, 0.75), (0.06, 0.75),                  # knees
    (-0.05, 0.98), (0.05, 0.98),                  # ankles
]


def standing(cx, top, height, conf=0.9):
    """A standing person `height` px tall; box width 0.3 x height."""
    kps = [{"x": cx + dx * height, "y": top + dy * height, "confidence": conf} for dx, dy in _STANDING]
    box = [cx - 0.15 * height, top, cx + 0.15 * height, top + height]
    return _obj(box, kps)


def lying(left, y, length, conf=0.9):
    """A person lying across the view: the standing pose rotated 90 degrees."""
    kps = [{"x": left + dy * length, "y": y + dx * length, "confidence": conf} for dx, dy in _STANDING]
    box = [left, y - 0.15 * length, left + length, y + 0.15 * length]
    return _obj(box, kps)


def _obj(box, kps):
    return {"bbox": box, "confidence": 0.9, "class_id": 0, "class_name": "person",
            "violation": False, "keypoints": kps}


def _scaled(obj, k):
    out = copy.deepcopy(obj)
    out["bbox"] = [c * k for c in obj["bbox"]]
    for kp in out["keypoints"]:
        kp["x"] *= k
        kp["y"] *= k
    return out


def _fires(rules_mod, m, obj, frame=FRAME):
    out = rules_mod.apply_rules([copy.deepcopy(obj)], m, None, frame_shape=frame)
    return out["violation_type"] if out["violation_detected"] else None


# --------------------------------------------------------------------------
# person_relative
# --------------------------------------------------------------------------


def test_small_standing_person_fires_in_legacy_but_not_relative(rules_mod):
    """The BL-1 false alarm: in legacy_640 the pixel thresholds make any
    small person 'horizontal'. Relative thresholds do not."""
    small = standing(cx=900, top=300, height=200)  # 0.19 of the frame height
    assert _fires(rules_mod, legacy_manifest(), small) == "fall_detected"
    assert _fires(rules_mod, relative_manifest(), small) is None


@pytest.mark.parametrize("height", [120, 300, 600, 1000])
def test_standing_never_fires_relative_at_any_size(rules_mod, height):
    assert _fires(rules_mod, relative_manifest(), standing(cx=960, top=40, height=height)) is None


@pytest.mark.parametrize("length", [150, 400, 900])
def test_lying_fires_relative_at_any_size(rules_mod, length):
    assert _fires(rules_mod, relative_manifest(), lying(left=200, y=700, length=length)) == "fall_detected"


@pytest.mark.parametrize("k", [0.25, 0.5, 2.0, 4.0])
def test_relative_score_does_not_depend_on_scale(rules_mod, k):
    m = relative_manifest()
    for person in (standing(cx=400, top=100, height=320), lying(left=100, y=500, length=480)):
        base = rules_mod._pose_band(copy.deepcopy(person), m["rules"], m, FRAME)
        big = rules_mod._pose_band(_scaled(person, k), m["rules"], m, (FRAME[0] * k, FRAME[1] * k, 3))
        assert (base[1], base[2]) == (big[1], big[2])


def test_relative_degenerate_box_never_fires(rules_mod):
    person = lying(left=200, y=700, length=400)
    person["bbox"] = [10, 10, 10, 10]
    assert _fires(rules_mod, relative_manifest(), person) is None


def test_relative_needs_no_frame_shape(rules_mod):
    out = rules_mod.apply_rules([lying(left=200, y=700, length=400)], relative_manifest(), None)
    assert out["violation_type"] == "fall_detected"


# --------------------------------------------------------------------------
# wide_box
# --------------------------------------------------------------------------


def _wide_only(ratio=1.5, score=0.8):
    m = relative_manifest()
    m["pose_fall"]["indicators"] = {"wide_box": {"width_over_height_above": ratio, "score": score}}
    return m


def test_wide_box_fires_on_a_wide_box(rules_mod):
    m = _wide_only()
    band, score, held = rules_mod._pose_band(lying(left=200, y=700, length=400), m["rules"], m, FRAME)
    assert (score, held, band["id"]) == (0.8, ["wide_box"], "fall")


def test_wide_box_is_strict_and_ignores_tall_boxes(rules_mod):
    m = _wide_only(ratio=2.0)
    tall = standing(cx=960, top=100, height=600)
    assert rules_mod._pose_band(tall, m["rules"], m, FRAME)[1] == 0.0
    exact = lying(left=200, y=700, length=400)
    exact["bbox"] = [0, 0, 400, 200]  # exactly 2.0: not above
    assert rules_mod._pose_band(exact, m["rules"], m, FRAME)[1] == 0.0


def test_wide_box_needs_a_visible_torso_like_every_indicator(rules_mod):
    m = _wide_only()
    person = lying(left=200, y=700, length=400)
    for i in (0, 5, 6, 11, 12):  # nose, shoulders, hips
        person["keypoints"][i]["confidence"] = 0.1
    assert rules_mod._pose_band(person, m["rules"], m, FRAME)[1] == 0.0


def test_wide_box_uses_the_true_box_not_the_legacy_stretch(rules_mod):
    """On a 1920x1080 frame a square box is 1.0 wide, not 0.56 (the legacy
    stretch squeezes x by 640/1920 and y by 640/1080)."""
    m = legacy_manifest()
    m["pose_fall"]["indicators"] = {"wide_box": {"width_over_height_above": 0.9, "score": 0.8}}
    person = standing(cx=960, top=100, height=600)
    person["bbox"] = [600, 100, 1200, 700]  # square in frame pixels
    assert rules_mod._pose_band(person, m["rules"], m, FRAME)[2] == ["wide_box"]


# --------------------------------------------------------------------------
# min_person_size
# --------------------------------------------------------------------------


def test_small_person_is_not_evaluated(rules_mod):
    m = legacy_manifest()
    m["pose_fall"]["min_person_size"] = 0.25  # 270 px on a 1080 frame
    small = standing(cx=900, top=300, height=200)
    out = rules_mod.apply_rules([small], m, None, frame_shape=FRAME)
    assert out["violation_detected"] is False
    assert out["objects"] == [small] and small["violation"] is False  # still drawn


def test_min_person_size_uses_the_longer_side(rules_mod):
    """A lying person is short but long: measured by the longer side."""
    m = relative_manifest()
    m["pose_fall"]["min_person_size"] = 0.25
    assert _fires(rules_mod, m, lying(left=200, y=700, length=400)) == "fall_detected"  # 0.37 long


def test_min_person_size_boundary_is_inclusive(rules_mod):
    m = legacy_manifest()
    m["pose_fall"]["min_person_size"] = 0.25
    at = standing(cx=900, top=300, height=270)  # exactly 0.25 of 1080
    assert rules_mod._pose_band(at, m["rules"], m, FRAME)[1] > 0
    below = standing(cx=900, top=300, height=269)
    assert rules_mod._pose_band(below, m["rules"], m, FRAME)[1] == 0.0


def test_min_person_size_needs_the_frame_shape(rules_mod):
    m = relative_manifest()
    m["pose_fall"]["min_person_size"] = 0.25
    with pytest.raises(ValueError, match="frame shape"):
        rules_mod.apply_rules([lying(left=200, y=700, length=400)], m, None)


# --------------------------------------------------------------------------
# Behaviour-neutral by default
# --------------------------------------------------------------------------


def test_shipped_manifest_uses_none_of_the_new_settings():
    m = legacy_manifest()
    assert m["pose_fall"]["coords"] == "legacy_640"
    assert "min_person_size" not in m["pose_fall"]
    assert "wide_box" not in m["pose_fall"]["indicators"]
    for path in MANIFESTS.glob("*.json"):
        assert "persistence" not in json.loads(path.read_text()), path.name


# --------------------------------------------------------------------------
# Installer
# --------------------------------------------------------------------------


def test_relative_manifest_is_valid(ie):
    m = relative_manifest()
    m["pose_fall"]["min_person_size"] = 0.1
    m["pose_fall"]["indicators"]["wide_box"] = {"width_over_height_above": 1.4, "score": 0.7}
    m["persistence"] = {"min_seconds": 3}
    assert ie.manifest_problems(m) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        # legacy pixel values left in a relative manifest would never fire
        (lambda m: m["pose_fall"]["indicators"]["horizontal_body"].update(shoulder_hip_dy_below=50),
         "horizontal_body.shoulder_hip_dy_below is a fraction"),
        (lambda m: m["pose_fall"]["indicators"]["compact_body"].update(y_span_below=150),
         "compact_body.y_span_below is a fraction"),
        (lambda m: m["pose_fall"].update(missing_hip_offset=100), "missing_hip_offset is a fraction"),
        (lambda m: m["pose_fall"]["indicators"].update(wide_box={"score": 0.7}),
         "wide_box.width_over_height_above must be a number"),
        (lambda m: m["pose_fall"].update(min_person_size=1.0), "min_person_size"),
        (lambda m: m["pose_fall"].update(min_person_size=-0.1), "min_person_size"),
        (lambda m: m["pose_fall"].update(min_person_size="big"), "min_person_size"),
        (lambda m: m.update(persistence={"min_seconds": 61}), "persistence.min_seconds"),
        (lambda m: m.update(persistence={"min_seconds": -1}), "persistence.min_seconds"),
        (lambda m: m.update(persistence={"seconds": 3}), "persistence.min_seconds"),
        (lambda m: m.update(persistence=3), "persistence.min_seconds"),
    ],
)
def test_relative_manifest_problems_caught(ie, mutate, expected):
    m = relative_manifest()
    mutate(m)
    assert expected in " | ".join(ie.manifest_problems(m))


def test_visible_keypoints_stays_a_count_in_relative(ie):
    m = relative_manifest()
    assert m["pose_fall"]["indicators"]["compact_body"]["visible_keypoints_above"] == 10
    assert ie.manifest_problems(m) == []


def test_legacy_pixel_values_still_valid_in_legacy(ie):
    assert ie.manifest_problems(legacy_manifest()) == []


def test_persistence_is_allowed_on_detect_models(ie):
    m = json.loads((MANIFESTS / "hard_hat.json").read_text())
    m["persistence"] = {"min_seconds": 2}
    assert ie.manifest_problems(m) == []

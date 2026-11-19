"""
Model store plugin: one generic inference entry point for uploaded YOLO
detection models.

A copy of this file sits in every installed store model's version dir,
next to ``store_manifest.json`` (what to load and which rules to apply) and
``weights/``. The runtime imports each copy under its own module name, so the
file is deliberately self-contained: no helper modules (they would be shared
across models through ``sys.modules``) and every path is resolved from this
file's own directory.

Result (the shape the backend consumes):
    violation_detected  any rule fired
    violation_type      the firing rule's type (highest severity wins)
    severity            that rule's severity
    confidence          highest confidence among the firing detections
    detections          the boxes the violation is about (stored with it)
    detection_count     len(objects); the runtime logs this field
    objects             every detection at or above the rule floor, for the
                        live overlay
    metadata            source "store", model/plugin identity, active rules,
                        and class_summary (per class: count and max
                        confidence)

A rule fires when a detection of one of its classes reaches its
min_confidence. A rule with ``requires_zone`` only considers detections whose
anchor (bottom centre) lies inside a zone of that type in ``config.zones``;
with no such zone it is inactive and can never fire (fails closed).

Trial mode
----------
An optional manifest block puts one model under observation without
touching any other:

    "diagnostics": {"summary_log_sample": 1.0, "predict_floor": 0.01}

``predict_floor`` lowers the floor passed to ``model.predict`` *below* the
rule's ``min_confidence``, so the sub-threshold confidence distribution
becomes visible. Rules still evaluate at their own ``min_confidence``, so
**violations are unchanged**, and ``objects`` is still filtered at the rule
floor, so **the live overlay is unchanged** — operators do not get sprayed
with low-confidence boxes. Only ``metadata.class_summary`` and the log line
see the extra detections.

``summary_log_sample`` is the probability of emitting a "Store detection
summary" log record for a given frame. It is gated on this alone and not on
whether a violation fired, so that enabling it for one model cannot make
another model start logging.

Absent the block, both default off and this file behaves exactly as it did
before trial mode existed. That is enforced by a test.

Pose models (``"task": "pose"``)
--------------------------------
A pose manifest runs an Ultralytics pose model (17 COCO keypoints per
person). Each object then also carries ``keypoints`` (17 x {x, y,
confidence}, frame pixels), and its rules are of type ``pose_fall``:

    "pose":      {"min_person_confidence": 0.25, "iou": 0.65}
    "pose_fall": {"coords": "legacy_640", "keypoint_min_confidence": 0.3,
                  "missing_hip_offset": 100, "indicators": {...}}
    "rules": [{"id": "fall", "type": "pose_fall", "classes": ["person"],
               "score_above": 0.7, "min_confidence": 0.7, ...}, ...]

``min_person_confidence`` (not the rules' ``min_confidence``) is the
detection floor, because a pose rule's ``min_confidence`` gates the fall
*score*, not the person box. Each person gets a fall score: the highest
``score`` among the ``indicators`` that hold for its keypoints (0 if none).
The person falls in the band of the rule with the highest ``score_above``
that the score exceeds, and that rule fires if the score also reaches its
``min_confidence``. The violation's ``confidence`` is the fall score; each
violating detection keeps the person box confidence and adds ``score``.

``coords`` sets the space the indicator thresholds are written in:

- ``"legacy_640"``: the built-in fall_detection model's space, the frame
  stretched (not letterboxed) to 640x640. The thresholds are the old pixel
  thresholds, and the decisions reproduce the old model's on the same
  keypoints.
- ``"person_relative"``: keypoints are divided by the person box's longer
  side S, in frame pixels. Distance thresholds (``shoulder_hip_dy_below``,
  ``nose_below_hip_by_more_than``, ``ankle_dx_above``, ``y_span_below``)
  and ``missing_hip_offset`` are then fractions of S, the same for a near
  and a far person. ``visible_keypoints_above`` stays a count. The longer
  side, not the height, because a lying person's box is short.

Optional, all absent by default, and then the result is exactly as before:

- ``pose_fall.indicators.wide_box``: ``{"width_over_height_above": r,
  "score": s}``. It holds when the person box, in frame pixels, is wider
  than r times its height. Like every indicator, it is only evaluated
  when the person has a visible nose, shoulder or hip.
- ``pose_fall.min_person_size``: a fraction of the frame height. A person
  whose box's longer side is smaller than this is not evaluated: score
  0, so no rule fires on them. They stay in ``objects``.

Persistence (alarm only after the fallen pose is held for N seconds) is not
here: a frame is judged on its own. The backend applies the manifest's
``persistence.min_seconds`` across frames.

Detection manifests are unaffected: none of this runs unless the task is
"pose", and their output is pinned by the legacy golden test.
"""

import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

PLUGIN_VERSION = "1.0.0"
MANIFEST_FILENAME = "store_manifest.json"

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

_lock = threading.Lock()
_state: Dict[str, Any] = {"model": None, "manifest": None, "device": None}


def _here() -> Path:
    return Path(__file__).resolve().parent


def load_manifest(directory: Optional[Path] = None) -> Dict[str, Any]:
    return json.loads(((directory or _here()) / MANIFEST_FILENAME).read_text())


def _ensure_loaded() -> Tuple[Any, Dict[str, Any], Any]:
    """Load the manifest and the YOLO weights once (thread-safe)."""
    if _state["model"] is not None:
        return _state["model"], _state["manifest"], _state["device"]
    with _lock:
        if _state["model"] is None:
            manifest = load_manifest()
            weights = _here() / "weights" / manifest["weights"]
            if not weights.is_file():
                raise FileNotFoundError(f"weights not found: {weights}")

            from ultralytics import YOLO  # imported lazily: heavy

            model = YOLO(str(weights))
            device = None
            try:
                import torch

                if torch.cuda.is_available():
                    device = 0
            except ImportError:  # pragma: no cover - torch ships with the runtime
                pass
            logger.info(
                "Store model loaded: %s (%s, imgsz %s, device %s)",
                manifest.get("model_id"), weights.name, manifest.get("imgsz"), device,
            )
            _state.update(model=model, manifest=manifest, device=device)
    return _state["model"], _state["manifest"], _state["device"]


# ---------------------------------------------------------------------------
# Rules (pure: tested without a model)
# ---------------------------------------------------------------------------


def _point_in_polygon(x: float, y: float, points: List[List[float]]) -> bool:
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i][0], points[i][1]
        xj, yj = points[j][0], points[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _zone_for(det: Dict[str, Any], zones: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    x1, y1, x2, y2 = det["bbox"]
    anchor_x, anchor_y = (x1 + x2) / 2.0, y2  # bottom centre: where the person stands
    for zone in zones:
        points = zone.get("points") or []
        if len(points) >= 3 and _point_in_polygon(anchor_x, anchor_y, points):
            return zone
    return None


#: COCO-17 keypoint indices the fall rule reads.
_NOSE, _L_SHOULDER, _R_SHOULDER = 0, 5, 6
_L_HIP, _R_HIP, _L_ANKLE, _R_ANKLE = 11, 12, 15, 16

#: The built-in fall_detection model stretched every frame to this square.
_LEGACY_SIZE = 640.0

POSE_FALL = "pose_fall"
COORDS_LEGACY_640 = "legacy_640"
COORDS_PERSON_RELATIVE = "person_relative"


def person_relative_keypoints(
    keypoints: List[Dict[str, float]], bbox: List[float]
) -> List[Dict[str, float]]:
    """Frame pixels -> units of the person's size: divided by the box's
    longer side, the same factor on both axes. A degenerate box gives no
    keypoints (score 0)."""
    size = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    if size <= 0:
        return []
    return [{"x": k["x"] / size, "y": k["y"] / size, "confidence": k["confidence"]} for k in keypoints]


def legacy_640_keypoints(
    keypoints: List[Dict[str, float]], frame_shape: Tuple[int, ...]
) -> List[Dict[str, float]]:
    """Frame pixels -> the built-in fall model's space: the frame stretched
    (not letterboxed) to 640x640, so x and y scale independently."""
    sx, sy = _LEGACY_SIZE / frame_shape[1], _LEGACY_SIZE / frame_shape[0]
    return [{"x": k["x"] * sx, "y": k["y"] * sy, "confidence": k["confidence"]} for k in keypoints]


def pose_fall_score(
    keypoints: List[Dict[str, float]],
    settings: Dict[str, Any],
    bbox: Optional[List[float]] = None,
) -> Tuple[float, List[str]]:
    """(fall score, indicators that held) for one person.

    A transcription of ``_analyze_pose_for_fall`` in the built-in
    ai/models/fall_detection/1.0.0/inference.py, with its constants read
    from the manifest: same visibility test, same fallbacks, same strict
    comparisons. A parity test runs both on the same keypoints. Thresholds
    are in whatever space ``keypoints`` are in (see ``coords``).

    ``bbox`` (frame pixels) is only read by the optional ``wide_box``
    indicator, which the built-in model did not have.
    """
    if len(keypoints) < 17:
        return 0.0, []
    floor = settings["keypoint_min_confidence"]

    def visible(k: Dict[str, float]) -> bool:
        return k["confidence"] > floor

    nose = keypoints[_NOSE]
    ls, rs = keypoints[_L_SHOULDER], keypoints[_R_SHOULDER]
    lh, rh = keypoints[_L_HIP], keypoints[_R_HIP]
    la, ra = keypoints[_L_ANKLE], keypoints[_R_ANKLE]

    if not any(visible(k) for k in (nose, ls, rs, lh, rh)):
        return 0.0, []

    if visible(ls) and visible(rs):
        shoulder_y = (ls["y"] + rs["y"]) / 2
    else:
        shoulder_y = nose["y"] if visible(nose) else 0
    if visible(lh) and visible(rh):
        hip_y = (lh["y"] + rh["y"]) / 2
    else:
        hip_y = shoulder_y + settings["missing_hip_offset"]

    ind = settings["indicators"]
    held: List[Tuple[str, float]] = []
    c = ind.get("horizontal_body")
    if c and abs(shoulder_y - hip_y) < c["shoulder_hip_dy_below"]:
        held.append(("horizontal_body", c["score"]))
    c = ind.get("head_below_hips")
    if c and visible(nose) and hip_y > 0 and nose["y"] > hip_y + c["nose_below_hip_by_more_than"]:
        held.append(("head_below_hips", c["score"]))
    c = ind.get("legs_spread")
    if c and visible(la) and visible(ra) and abs(la["x"] - ra["x"]) > c["ankle_dx_above"]:
        held.append(("legs_spread", c["score"]))
    c = ind.get("compact_body")
    if c:
        ys = [k["y"] for k in keypoints if visible(k)]
        if len(ys) > c["visible_keypoints_above"] and max(ys) - min(ys) < c["y_span_below"]:
            held.append(("compact_body", c["score"]))
    c = ind.get("wide_box")
    if c and bbox is not None:
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if height > 0 and width / height > c["width_over_height_above"]:
            held.append(("wide_box", c["score"]))

    if not held:
        return 0.0, []
    return max(score for _, score in held), [name for name, _ in held]


def _pose_band(
    obj: Dict[str, Any],
    pose_rules: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    frame_shape: Optional[Tuple[int, ...]],
) -> Tuple[Optional[Dict[str, Any]], float, List[str]]:
    """The pose rule whose band this person's fall score lies in, if any."""
    if not pose_rules or obj.get("keypoints") is None:
        return None, 0.0, []
    settings = manifest["pose_fall"]
    coords = settings.get("coords")
    if coords not in (COORDS_LEGACY_640, COORDS_PERSON_RELATIVE):
        raise ValueError(f"pose_fall coords {coords!r} not supported")
    size_floor = settings.get("min_person_size")
    if frame_shape is None and (coords == COORDS_LEGACY_640 or size_floor is not None):
        raise ValueError("pose rules need the frame shape")
    bbox = obj["bbox"]
    if size_floor is not None and max(bbox[2] - bbox[0], bbox[3] - bbox[1]) < size_floor * frame_shape[0]:
        return None, 0.0, []
    if coords == COORDS_LEGACY_640:
        keypoints = legacy_640_keypoints(obj["keypoints"], frame_shape)
    else:
        keypoints = person_relative_keypoints(obj["keypoints"], bbox)
    score, held = pose_fall_score(keypoints, settings, bbox)
    candidates = [
        r for r in pose_rules if obj["class_name"] in r["classes"] and score > r["score_above"]
    ]
    band = max(candidates, key=lambda r: r["score_above"]) if candidates else None
    return band, score, held


def apply_rules(
    objects: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    frame_shape: Optional[Tuple[int, ...]] = None,
) -> Dict[str, Any]:
    """Turn raw detections into the result the backend consumes.

    ``frame_shape`` is only read by pose rules (``legacy_640`` coordinates
    and ``min_person_size``)."""
    rules = manifest.get("rules", [])
    zones = (config or {}).get("zones") or []
    pose_rules = [r for r in rules if r.get("type") == POSE_FALL]

    active, inactive = [], []
    for rule in rules:
        zone_type = rule.get("requires_zone")
        if zone_type and not any(z.get("type") == zone_type for z in zones):
            inactive.append(rule["id"])
        else:
            active.append(rule["id"])

    firing: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for obj in objects:
        band, score, held = _pose_band(obj, pose_rules, manifest, frame_shape)
        for rule in rules:
            if rule["id"] not in active:
                continue
            if rule.get("type") == POSE_FALL:
                if rule is not band or score < rule["min_confidence"]:
                    continue
            elif obj["class_name"] not in rule["classes"] or obj["confidence"] < rule["min_confidence"]:
                continue
            violating = {
                "bbox": obj["bbox"],
                "confidence": obj["confidence"],
                "class_id": obj["class_id"],
                "class_name": obj["class_name"],
                "label": rule["violation_type"],
                "rule_id": rule["id"],
            }
            if rule.get("type") == POSE_FALL:
                violating["score"] = score
                violating["indicators"] = held
            zone_type = rule.get("requires_zone")
            if zone_type:
                zone = _zone_for(obj, [z for z in zones if z.get("type") == zone_type])
                if zone is None:
                    continue
                violating["in_zone"] = True
                violating["zone_id"] = zone.get("id")
            obj["violation"] = True
            firing.append((rule, violating))

    if firing:
        # A pose detection is judged on its fall score, not its box confidence.
        def strength(v: Dict[str, Any]) -> float:
            return v.get("score", v["confidence"])

        top_rule, _ = max(
            firing,
            key=lambda rv: (_SEVERITY_RANK.get(rv[0].get("severity", "medium"), 0), strength(rv[1])),
        )
        return {
            "violation_detected": True,
            "violation_type": top_rule["violation_type"],
            "severity": top_rule.get("severity", "medium"),
            "confidence": max(strength(v) for _, v in firing),
            "detections": [v for _, v in firing],
            "objects": objects,
            "rules_active": active,
            "rules_inactive": inactive,
        }
    return {
        "violation_detected": False,
        "violation_type": None,
        "severity": "low",
        "confidence": 0.0,
        "detections": [],
        "objects": objects,
        "rules_active": active,
        "rules_inactive": inactive,
    }


def _class_summary(objects: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per class: how many, and the best confidence seen.

    Computed over every scored detection, including any below the rule
    floor under trial mode — answering "did the model see anything at all?",
    which a count of rule-passing boxes cannot.
    """
    summary: Dict[str, Dict[str, Any]] = {}
    for obj in objects:
        entry = summary.setdefault(obj["class_name"], {"n": 0, "max_confidence": 0.0})
        entry["n"] += 1
        if obj["confidence"] > entry["max_confidence"]:
            entry["max_confidence"] = obj["confidence"]
    return summary


#: Mean per-pixel channel difference at or below which a frame is treated
#: as greyscale.
#:
#: Calibrated against the fleet, after a first guess of 6.0 was wrong.
#: A true IR stream duplicates the luma into all three channels, so it
#: reads **exactly 0.0** — camera 75130 does, on every frame. The value
#: is not zero only to leave room for a stream that re-encodes with a
#: little chroma noise.
#:
#: The trap this avoids: camera 75104 reads 5.5 and is NOT infrared, it
#: is a colour camera pointed at a grey-painted scene. A low channel
#: spread means "this picture has little colour in it", which is not the
#: same question as "this sensor is in night mode" — and only the latter
#: is a domain shift for the model. Observed fleet spreads are 0.0, then
#: 5.3 and upward, so 1.0 sits well inside the gap.
GREYSCALE_TOLERANCE = 1.0

#: Highest spread observed from a camera that is NOT infrared (75104, a
#: grey-painted scene). The tolerance must stay below it.
_OBSERVED_GREY_SCENE_SPREAD = 5.3


def _channel_spread(frame: np.ndarray) -> float:
    """How far from grey a frame is, as a mean 0-255 channel difference.

    Confined-space cameras switch to infrared at night and produce frames
    that are structurally colour (three channels) but visually grey. A
    model trained on daylight colour can behave completely differently on
    those, so the trial summary has to be splittable by it.

    Sampled on a stride rather than the whole frame: this runs per
    inference, and a 16x16 stride over 1280x720 is ~3,600 pixels, which
    is plenty to tell grey from colour.
    """
    if frame.ndim != 3 or frame.shape[2] < 3:
        return 0.0
    s = frame[::16, ::16, :3].astype(np.int16)
    bg = np.abs(s[:, :, 0] - s[:, :, 1]).mean()
    gr = np.abs(s[:, :, 1] - s[:, :, 2]).mean()
    return round(float(max(bg, gr)), 2)


def _np(value: Any) -> np.ndarray:
    return value.cpu().numpy() if hasattr(value, "cpu") else np.asarray(value)


def _objects_from_result(
    result: Any, names: Dict[str, str], with_keypoints: bool = False
) -> List[Dict[str, Any]]:
    """Ultralytics boxes -> plain dicts, coordinates in frame pixels.

    ``with_keypoints`` (pose models) adds each person's keypoints, frame
    pixels, unrounded: the fall rule's thresholds are compared on them, and
    rounding could move a value across one."""
    objects: List[Dict[str, Any]] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return objects
    xyxy = _np(boxes.xyxy)
    conf = _np(boxes.conf)
    cls = _np(boxes.cls)
    kpts = None
    if with_keypoints:
        kp = getattr(result, "keypoints", None)
        kpts = _np(kp.data) if kp is not None else np.zeros((len(conf), 0, 3))
    for i in range(len(conf)):
        class_id = int(cls[i])
        obj = {
            "bbox": [round(float(v), 1) for v in xyxy[i]],
            "confidence": round(float(conf[i]), 4),
            "class_id": class_id,
            "class_name": names.get(str(class_id), str(class_id)),
            "violation": False,
        }
        if kpts is not None:
            obj["keypoints"] = [
                {
                    "x": float(k[0]),
                    "y": float(k[1]),
                    # Models trained without keypoint visibility give (x, y)
                    # only; treat their points as seen.
                    "confidence": float(k[2]) if len(k) > 2 else 1.0,
                }
                for k in kpts[i]
            ]
        objects.append(obj)
    return objects


# ---------------------------------------------------------------------------
# Runtime entry point
# ---------------------------------------------------------------------------


def infer(frame: np.ndarray, config: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """Run the store model on one BGR frame. Errors propagate: the runtime
    reports them as a failed inference, which the backend logs and backs
    off on, rather than a silent "no violation"."""
    if frame is None or not isinstance(frame, np.ndarray):
        raise ValueError("frame must be a numpy array")

    model, manifest, device = _ensure_loaded()
    rules = manifest.get("rules", [])
    diagnostics = manifest.get("diagnostics") or {}
    is_pose = manifest.get("task") == "pose"

    # The rule floor is what the model is *judged* at. The predict floor can
    # be lowered beneath it for observation, but never raised above it —
    # that would silently stop rules firing. A pose rule's min_confidence
    # gates the fall score, so for pose the floor is the person floor.
    if is_pose:
        rule_floor = float(manifest["pose"]["min_person_confidence"])
    else:
        rule_floor = min((r["min_confidence"] for r in rules), default=0.25)
    predict_floor = rule_floor
    configured = diagnostics.get("predict_floor")
    if configured is not None:
        predict_floor = min(rule_floor, float(configured))

    predict_args = dict(imgsz=manifest["imgsz"], conf=predict_floor, device=device, verbose=False)
    if is_pose and manifest["pose"].get("iou") is not None:
        predict_args["iou"] = float(manifest["pose"]["iou"])

    started = time.perf_counter()
    results = model.predict(frame, **predict_args)
    inference_ms = (time.perf_counter() - started) * 1000.0

    scored = (
        _objects_from_result(results[0], manifest["classes"], with_keypoints=is_pose)
        if results
        else []
    )
    # Identity, not just equality, when no floor was lowered: the rest of the
    # function must see exactly the list it always saw.
    objects = (
        scored
        if predict_floor >= rule_floor
        else [o for o in scored if o["confidence"] >= rule_floor]
    )

    out = apply_rules(objects, manifest, config, frame_shape=frame.shape)
    out["detection_count"] = len(objects)
    out["metadata"] = {
        "source": "store",
        "model_id": manifest["model_id"],
        "display_name": manifest.get("display_name", manifest["model_id"]),
        "plugin_version": PLUGIN_VERSION,
        "imgsz": manifest["imgsz"],
        "inference_ms": round(inference_ms, 1),
        "rules_active": out.pop("rules_active"),
        "rules_inactive": out.pop("rules_inactive"),
        "frame_shape": list(frame.shape),
        "class_summary": _class_summary(scored),
    }
    if is_pose:
        out["metadata"]["task"] = "pose"

    # Trial mode only. Gated on the sample rate alone, deliberately: gating
    # on "a violation fired" as well would make every model with violations
    # start logging the moment one model is put under observation.
    sample = float(diagnostics.get("summary_log_sample", 0.0))
    if sample > 0.0 and random.random() < sample:
        out["metadata"]["predict_floor"] = predict_floor
        out["metadata"]["scored_count"] = len(scored)
        # The plugin is handed only (frame, config): no request id, no
        # stream id, so it cannot otherwise say which camera this was.
        # `config` is per-camera-per-model, so a trial can label its own
        # frames by setting {"camera_name": ...} there. Unset elsewhere,
        # which is why this reads "unknown" rather than failing.
        spread = _channel_spread(frame)
        logger.info(
            "Store detection summary",
            extra={
                "model_id": manifest["model_id"],
                "camera_name": (config or {}).get("camera_name", "unknown"),
                "channel_spread": spread,
                "greyscale": spread <= GREYSCALE_TOLERANCE,
                "detection_count": out["detection_count"],
                "scored_count": len(scored),
                "predict_floor": predict_floor,
                "rule_floor": rule_floor,
                "class_summary": out["metadata"]["class_summary"],
                "violation_detected": out["violation_detected"],
                "inference_ms": round(inference_ms, 1),
            },
        )
    return out

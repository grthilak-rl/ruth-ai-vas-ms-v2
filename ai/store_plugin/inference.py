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
    objects             every detection, for the live overlay
    metadata            source "store", model/plugin identity, active rules

A rule fires when a detection of one of its classes reaches its
min_confidence. A rule with ``requires_zone`` only considers detections whose
anchor (bottom centre) lies inside a zone of that type in ``config.zones``;
with no such zone it is inactive and can never fire (fails closed).
"""

import json
import logging
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


def apply_rules(
    objects: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Turn raw detections into the result the backend consumes."""
    rules = manifest.get("rules", [])
    zones = (config or {}).get("zones") or []

    active, inactive = [], []
    for rule in rules:
        zone_type = rule.get("requires_zone")
        if zone_type and not any(z.get("type") == zone_type for z in zones):
            inactive.append(rule["id"])
        else:
            active.append(rule["id"])

    firing: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for obj in objects:
        for rule in rules:
            if rule["id"] not in active:
                continue
            if obj["class_name"] not in rule["classes"] or obj["confidence"] < rule["min_confidence"]:
                continue
            violating = {
                "bbox": obj["bbox"],
                "confidence": obj["confidence"],
                "class_id": obj["class_id"],
                "class_name": obj["class_name"],
                "label": rule["violation_type"],
                "rule_id": rule["id"],
            }
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
        top_rule, _ = max(
            firing,
            key=lambda rv: (_SEVERITY_RANK.get(rv[0].get("severity", "medium"), 0), rv[1]["confidence"]),
        )
        return {
            "violation_detected": True,
            "violation_type": top_rule["violation_type"],
            "severity": top_rule.get("severity", "medium"),
            "confidence": max(v["confidence"] for _, v in firing),
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


def _objects_from_result(result: Any, names: Dict[str, str]) -> List[Dict[str, Any]]:
    """Ultralytics boxes -> plain dicts, coordinates in frame pixels."""
    objects: List[Dict[str, Any]] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return objects
    xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes.xyxy, "cpu") else np.asarray(boxes.xyxy)
    conf = boxes.conf.cpu().numpy() if hasattr(boxes.conf, "cpu") else np.asarray(boxes.conf)
    cls = boxes.cls.cpu().numpy() if hasattr(boxes.cls, "cpu") else np.asarray(boxes.cls)
    for i in range(len(conf)):
        class_id = int(cls[i])
        objects.append(
            {
                "bbox": [round(float(v), 1) for v in xyxy[i]],
                "confidence": round(float(conf[i]), 4),
                "class_id": class_id,
                "class_name": names.get(str(class_id), str(class_id)),
                "violation": False,
            }
        )
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
    floor = min((r["min_confidence"] for r in rules), default=0.25)

    started = time.perf_counter()
    results = model.predict(
        frame, imgsz=manifest["imgsz"], conf=floor, device=device, verbose=False
    )
    inference_ms = (time.perf_counter() - started) * 1000.0

    objects = _objects_from_result(results[0], manifest["classes"]) if results else []
    out = apply_rules(objects, manifest, config)
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
    }
    return out

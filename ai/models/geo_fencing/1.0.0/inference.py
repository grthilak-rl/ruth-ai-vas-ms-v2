"""
Geo-Fencing Model - Inference

Person detection with zone intrusion monitoring.
Uses YOLO for person detection and ray-casting algorithm for polygon intersection.

Based on geo_fencing.py detection logic, adapted to Ruth AI plugin interface.
"""

import numpy as np
import logging
import time
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Global model instance (loaded once, reused for all inferences)
_loaded_model = None
_weights_available = False

# Default configuration
DEFAULT_CONFIG = {
    "conf_threshold": 0.3,  # Lowered for better detection sensitivity
    "iou_threshold": 0.5,
    "zones": []
}


def infer(frame: np.ndarray, config: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
    """
    Run geo-fencing inference on a frame.

    Args:
        frame: Raw BGR frame as numpy array (H, W, 3)
        config: Inference configuration containing:
            - zones: List of zone definitions with points and type
            - conf_threshold: Detection confidence threshold (default: 0.5)
            - iou_threshold: IOU threshold for NMS (default: 0.5)

            Zone format:
            {
                "id": "zone_1",
                "name": "Restricted Area",
                "points": [[x1,y1], [x2,y2], [x3,y3], ...],
                "type": "restricted"  # or "allowed"
            }

            Also accepts legacy formats:
            - tank_corners: [[x1,y1], ...] - treated as single restricted zone
            - geofence_points: [[x1,y1], ...] - treated as single restricted zone

    Returns:
        Detection results matching the model.yaml output schema
    """
    global _loaded_model, _weights_available

    # Validate input
    if frame is None:
        raise ValueError("Frame is None")

    if not isinstance(frame, np.ndarray):
        raise ValueError(f"Frame must be numpy array, got {type(frame)}")

    # Try to load model on first inference
    if _loaded_model is None and not _weights_available:
        try:
            _loaded_model = _lazy_load_model()
            _weights_available = True
            logger.info("Geo-fencing model loaded successfully")
        except FileNotFoundError as e:
            logger.warning(f"Model weights not found: {e}. Using stub mode.")
            _weights_available = False
        except Exception as e:
            logger.error(f"Failed to load model: {e}. Using stub mode.")
            _weights_available = False

    # Parse configuration
    if config is None:
        config = {}

    merged_config = DEFAULT_CONFIG.copy()
    merged_config.update(config)

    # Convert legacy config formats to zones format
    zones = _normalize_zones_config(merged_config)

    start_time = time.time()

    # If model is available, run actual inference
    if _weights_available and _loaded_model is not None:
        try:
            result = _run_inference_with_model(frame, _loaded_model, zones, merged_config)
            result["metadata"]["inference_time_ms"] = round((time.time() - start_time) * 1000, 2)
            return result
        except Exception as e:
            logger.error(f"Inference failed: {e}. Falling back to stub mode.")
            # Fall through to stub response

    # Stub response when model not available
    return {
        "violation_detected": False,
        "violation_type": None,
        "severity": "low",
        "confidence": 0.0,
        "detections": [],
        "metadata": {
            "model_name": "geo_fencing",
            "model_version": "1.0.0",
            "mode": "stub",
            "inference_time_ms": round((time.time() - start_time) * 1000, 2),
            "persons_detected": 0,
            "persons_in_zone": 0,
            "note": "Model weights not loaded - deploy weights for actual inference"
        }
    }


def _normalize_zones_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize different config formats to a standard zones list.

    Supports:
    - zones: Standard format with multiple zones
    - tank_corners: Legacy format, converted to single restricted zone
    - geofence_points: Legacy format, converted to single restricted zone
    """
    zones = config.get("zones", [])

    if zones:
        return zones

    # Check for legacy formats
    legacy_points = None

    if "tank_corners" in config and config["tank_corners"]:
        legacy_points = config["tank_corners"]
    elif "geofence_points" in config and config["geofence_points"]:
        legacy_points = config["geofence_points"]

    if legacy_points:
        return [{
            "id": "zone_1",
            "name": "Restricted Zone",
            "points": legacy_points,
            "type": "restricted"
        }]

    return []


def _lazy_load_model():
    """
    Lazy load the YOLO person detection model.

    Returns:
        Loaded YOLO model instance

    Raises:
        FileNotFoundError: If weights not found
        Exception: If loading fails
    """
    from ultralytics import YOLO

    # Get weights path - prefer yolov8n.pt (general COCO model) over person.pt
    model_dir = Path(__file__).parent
    weights_path = model_dir / "weights" / "yolov8n.pt"

    # Fall back to person.pt if yolov8n.pt not found
    if not weights_path.exists():
        weights_path = model_dir / "weights" / "person.pt"

    if not weights_path.exists():
        raise FileNotFoundError(f"Model weights not found: {weights_path}")

    logger.info(f"Loading YOLO model from {weights_path}")
    model = YOLO(str(weights_path))

    return model


def _run_inference_with_model(
    frame: np.ndarray,
    model,
    zones: List[Dict[str, Any]],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Run actual inference using loaded YOLO model.

    Args:
        frame: BGR frame (H, W, 3)
        model: Loaded YOLO model
        zones: List of zone definitions
        config: Inference configuration

    Returns:
        Detection results
    """
    conf_threshold = config.get("conf_threshold", 0.5)
    iou_threshold = config.get("iou_threshold", 0.5)

    # Debug: Log frame info and save a sample frame
    logger.info(f"Running inference on frame: shape={frame.shape}, dtype={frame.dtype}, min={frame.min()}, max={frame.max()}")

    # Save debug frame occasionally (every 100th frame)
    import random
    if random.random() < 0.01:  # 1% chance to save
        try:
            import cv2
            debug_path = f"/tmp/debug_inference_frame_{int(time.time())}.jpg"
            cv2.imwrite(debug_path, frame)
            logger.info(f"Saved debug frame to {debug_path}")
        except Exception as e:
            logger.warning(f"Failed to save debug frame: {e}")

    # Run YOLO inference (class 0 is person in COCO)
    results = model(
        frame,
        conf=conf_threshold,
        iou=iou_threshold,
        classes=[0],  # Person class only
        verbose=False
    )

    # Debug: Log raw YOLO results
    if results and len(results) > 0:
        result = results[0]
        if result.boxes is not None and len(result.boxes) > 0:
            boxes = result.boxes.xyxy.cpu().numpy()
            confs = result.boxes.conf.cpu().numpy()
            logger.info(f"YOLO found {len(result.boxes)} detections")
            for i, (box, conf) in enumerate(zip(boxes, confs)):
                x1, y1, x2, y2 = box
                center = ((x1 + x2) / 2, (y1 + y2) / 2)
                logger.info(f"Detection {i}: bbox=[{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}], center=({center[0]:.0f},{center[1]:.0f}), conf={conf:.3f}")
            if zones:
                logger.info(f"Zone points: {zones[0].get('points', [])}")
        else:
            logger.info("YOLO boxes is None or empty")
    else:
        logger.info("YOLO results empty")

    detections = []
    persons_in_zone = 0
    max_in_zone_confidence = 0.0
    violation_detected = False
    violation_zone_id = None

    if results and len(results) > 0:
        result = results[0]

        if result.boxes is not None and len(result.boxes) > 0:
            boxes = result.boxes.xyxy.cpu().numpy()
            confidences = result.boxes.conf.cpu().numpy()

            for box, conf in zip(boxes, confidences):
                x1, y1, x2, y2 = box
                center = _get_box_center(box)

                # Check if person is in any zone
                in_zone = False
                zone_id = None

                for zone in zones:
                    zone_points = zone.get("points", [])
                    zone_type = zone.get("type", "restricted")

                    if len(zone_points) >= 3:
                        is_inside = _point_in_polygon(center, zone_points)

                        if zone_type == "restricted" and is_inside:
                            in_zone = True
                            zone_id = zone.get("id", "unknown")
                            violation_detected = True
                            violation_zone_id = zone_id
                            persons_in_zone += 1
                            if conf > max_in_zone_confidence:
                                max_in_zone_confidence = float(conf)
                            break
                        elif zone_type == "allowed" and not is_inside:
                            # Person left allowed zone
                            in_zone = True
                            zone_id = zone.get("id", "unknown")
                            violation_detected = True
                            violation_zone_id = zone_id
                            persons_in_zone += 1
                            if conf > max_in_zone_confidence:
                                max_in_zone_confidence = float(conf)
                            break

                detections.append({
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "confidence": float(conf),
                    "in_zone": in_zone,
                    "zone_id": zone_id
                })

    # Determine violation type and severity
    violation_type = None
    severity = "low"

    if violation_detected:
        # Check if it's a restricted zone intrusion or allowed zone exit
        for zone in zones:
            if zone.get("id") == violation_zone_id:
                if zone.get("type") == "restricted":
                    violation_type = "zone_intrusion"
                else:
                    violation_type = "zone_exit"
                break

        # Severity based on number of people and confidence
        if persons_in_zone >= 3 or max_in_zone_confidence > 0.85:
            severity = "critical"
        elif persons_in_zone >= 2 or max_in_zone_confidence > 0.7:
            severity = "high"
        else:
            severity = "medium"

    return {
        "violation_detected": violation_detected,
        "violation_type": violation_type,
        "severity": severity,
        "confidence": max_in_zone_confidence if violation_detected else 0.0,
        "detections": detections,
        "metadata": {
            "model_name": "geo_fencing",
            "model_version": "1.0.0",
            "mode": "inference",
            "inference_time_ms": 0.0,  # Will be set by caller
            "persons_detected": len(detections),
            "persons_in_zone": persons_in_zone,
            "frame_shape": list(frame.shape),
            "zones_configured": len(zones)
        }
    }


def _get_box_center(box: np.ndarray) -> Tuple[float, float]:
    """Get center point of bounding box."""
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _point_in_polygon(point: Tuple[float, float], polygon: List[List[float]]) -> bool:
    """
    Check if point is inside polygon using ray casting algorithm.

    This is the same algorithm used in geo_fencing.py.

    Args:
        point: (x, y) tuple
        polygon: List of [x, y] points defining the polygon

    Returns:
        True if point is inside polygon
    """
    x, y = point
    n = len(polygon)
    inside = False

    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


# Optional: Model initialization function (called once during loading)
def load_model(weights_path: str, **kwargs) -> Any:
    """
    Load YOLO model weights.

    Args:
        weights_path: Path to model weights directory
        **kwargs: Additional loading parameters

    Returns:
        Loaded model object (or None for MVP stub)
    """
    from pathlib import Path

    weights_dir = Path(weights_path)
    if not weights_dir.exists():
        raise FileNotFoundError(f"Weights directory not found: {weights_path}")

    return None

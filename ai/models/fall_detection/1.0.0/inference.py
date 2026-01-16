"""
Fall Detection Inference

Main inference module for fall detection using pose estimation.
This module adapts the existing FallDetector logic to the platform interface.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch

logger = logging.getLogger(__name__)

# Add lib directory to path for imports
_model_dir = Path(__file__).parent
_lib_dir = _model_dir / "lib"
if str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))

# Import YOLOv7 utilities
from utils.general import non_max_suppression_kpt
from utils.plots import output_to_keypoint

# COCO pose keypoint indices (for reference)
KEYPOINT_NAMES = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
]


def infer(frame: torch.Tensor, model: Any = None, **kwargs: Any) -> Dict[str, Any]:
    """
    Run fall detection inference on a preprocessed frame.

    Args:
        frame: Preprocessed tensor from preprocess() (1, 3, 640, 640)
        model: Loaded YOLOv7-Pose model from loader.load()
        **kwargs: Additional arguments (ignored)

    Returns:
        Detection results dictionary
    """
    if model is None:
        logger.error("Model not provided to infer()")
        return {
            "violation_detected": False,
            "error": "Model not loaded",
            "model_name": "fall_detector",
            "model_version": "1.0.0"
        }

    try:
        # Run inference
        with torch.no_grad():
            predictions = model(frame)[0]

        # Post-process predictions to extract keypoints
        detections = _postprocess_predictions(predictions)

        # Analyze poses for fall detection
        fall_detected = False
        fall_confidence = 0.0
        fall_type = None

        for detection in detections:
            is_fall, confidence, f_type = _analyze_pose_for_fall(detection["keypoints"])
            if is_fall and confidence > fall_confidence:
                fall_detected = True
                fall_confidence = confidence
                fall_type = f_type

        return {
            "violation_detected": fall_detected,
            "violation_type": fall_type,
            "severity": "critical" if fall_detected else "low",
            "confidence": fall_confidence,
            "detections": detections,
            "detection_count": len(detections),
            "model_name": "fall_detector",
            "model_version": "1.0.0"
        }

    except Exception as e:
        logger.error(f"Fall detection failed: {e}")
        return {
            "violation_detected": False,
            "error": str(e),
            "model_name": "fall_detector",
            "model_version": "1.0.0"
        }


def _postprocess_predictions(predictions: torch.Tensor) -> List[Dict]:
    """
    Post-process model predictions to extract pose keypoints.

    Args:
        predictions: Raw model output tensor

    Returns:
        List of detection dictionaries with keypoints
    """
    detections = []

    # Apply NMS with keypoint support
    output = non_max_suppression_kpt(
        predictions,
        conf_thres=0.25,
        iou_thres=0.65,
        nc=1,  # Number of classes (person only)
        nkpt=17,  # Number of keypoints
        kpt_label=True
    )

    # Process detections
    with torch.no_grad():
        output = output_to_keypoint(output)

    logger.debug(f"Detections found: {output.shape[0]}")

    # Extract detection info for each person detected
    for idx in range(output.shape[0]):
        # Get bounding box in xywh (center) format and convert to xyxy
        x_center = float(output[idx, 2])
        y_center = float(output[idx, 3])
        w = float(output[idx, 4])
        h = float(output[idx, 5])
        conf = float(output[idx, 6])

        # Convert from center format to corner format
        x1 = x_center - w / 2
        y1 = y_center - h / 2
        x2 = x_center + w / 2
        y2 = y_center + h / 2

        # Extract 17 keypoints (x, y, conf) - starting from index 7
        keypoints = []
        for kpt_idx in range(17):
            kpt_x = float(output[idx, 7 + kpt_idx * 3])
            kpt_y = float(output[idx, 7 + kpt_idx * 3 + 1])
            kpt_conf = float(output[idx, 7 + kpt_idx * 3 + 2])
            keypoints.append({
                "x": kpt_x,
                "y": kpt_y,
                "confidence": kpt_conf
            })

        detection_dict = {
            "bbox": [x1, y1, x2, y2],
            "confidence": conf,
            "keypoints": keypoints
        }
        detections.append(detection_dict)

    return detections


def _analyze_pose_for_fall(keypoints: List[Dict]) -> Tuple[bool, float, Optional[str]]:
    """
    Analyze pose keypoints to detect falls.

    Args:
        keypoints: List of keypoint dicts with 'x', 'y', 'confidence'

    Returns:
        Tuple of (is_fall, confidence, fall_type)
    """
    try:
        # Extract key body parts (0-indexed)
        nose = keypoints[0]
        left_shoulder = keypoints[5]
        right_shoulder = keypoints[6]
        left_hip = keypoints[11]
        right_hip = keypoints[12]
        left_knee = keypoints[13]
        right_knee = keypoints[14]
        left_ankle = keypoints[15]
        right_ankle = keypoints[16]

        # Check if key points are visible
        key_points_visible = [
            nose['confidence'] > 0.3,
            left_shoulder['confidence'] > 0.3,
            right_shoulder['confidence'] > 0.3,
            left_hip['confidence'] > 0.3,
            right_hip['confidence'] > 0.3
        ]

        if not any(key_points_visible):
            return False, 0.0, None

        # Calculate body orientation
        if left_shoulder['confidence'] > 0.3 and right_shoulder['confidence'] > 0.3:
            shoulder_center_y = (left_shoulder['y'] + right_shoulder['y']) / 2
        else:
            shoulder_center_y = nose['y'] if nose['confidence'] > 0.3 else 0

        if left_hip['confidence'] > 0.3 and right_hip['confidence'] > 0.3:
            hip_center_y = (left_hip['y'] + right_hip['y']) / 2
        else:
            hip_center_y = shoulder_center_y + 100  # Estimate

        # Fall detection logic
        fall_indicators = []

        # 1. Check if person is horizontal (body orientation)
        if abs(shoulder_center_y - hip_center_y) < 50:
            fall_indicators.append(("horizontal_body", 0.8))

        # 2. Check if head is lower than hips
        if nose['confidence'] > 0.3 and hip_center_y > 0:
            if nose['y'] > hip_center_y + 20:
                fall_indicators.append(("head_below_hips", 0.7))

        # 3. Check limb positions
        if left_ankle['confidence'] > 0.3 and right_ankle['confidence'] > 0.3:
            ankle_distance = abs(left_ankle['x'] - right_ankle['x'])
            if ankle_distance > 100:
                fall_indicators.append(("legs_spread", 0.6))

        # 4. Overall body compactness
        visible_kpts = [kp for kp in keypoints if kp['confidence'] > 0.3]
        if len(visible_kpts) > 10:
            y_coords = [kp['y'] for kp in visible_kpts]
            if y_coords:
                y_range = max(y_coords) - min(y_coords)
                if y_range < 150:
                    fall_indicators.append(("compact_body", 0.7))

        # Determine fall status
        if fall_indicators:
            max_confidence = max(indicator[1] for indicator in fall_indicators)

            if max_confidence > 0.7:
                return True, max_confidence, "fall_detected"
            elif max_confidence > 0.5:
                return True, max_confidence, "possible_fall"

        return False, 0.0, None

    except Exception as e:
        logger.error(f"Pose analysis failed: {e}")
        return False, 0.0, None

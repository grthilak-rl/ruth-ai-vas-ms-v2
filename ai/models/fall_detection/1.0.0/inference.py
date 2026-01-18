"""
Fall Detection Model - Inference

Phase 2 implementation with graceful degradation:
- If weights are available: Run full YOLOv7-Pose inference
- If weights are missing: Return stub response for testing

This allows the system to work end-to-end even before weights are deployed.
"""

import numpy as np
import logging
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Global model instance (loaded once, reused for all inferences)
_loaded_model = None
_weights_available = False


def infer(frame: np.ndarray, **kwargs) -> Dict[str, Any]:
    """
    Run fall detection inference.

    Args:
        frame: Raw BGR frame as numpy array (H, W, 3)

    Returns:
        Detection results matching the model.yaml output schema

    Raises:
        ValueError: If frame is invalid
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
            logger.info("Fall detection model loaded successfully")
        except FileNotFoundError as e:
            logger.warning(f"Model weights not found: {e}. Using stub mode for testing.")
            _weights_available = False
        except Exception as e:
            logger.error(f"Failed to load model: {e}. Using stub mode.")
            _weights_available = False

    # If model is available, run actual inference
    if _weights_available and _loaded_model is not None:
        try:
            return _run_inference_with_model(frame, _loaded_model)
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
        "detection_count": 0,
        "metadata": {
            "model_name": "fall_detector",
            "model_version": "1.0.0",
            "mode": "stub",
            "note": "Model weights not loaded - deploy weights for actual inference"
        }
    }


def _lazy_load_model():
    """
    Lazy load the YOLOv7-Pose model.

    Returns:
        Loaded model instance

    Raises:
        FileNotFoundError: If weights not found
        Exception: If loading fails
    """
    import torch
    import sys

    # Get weights path
    model_dir = Path(__file__).parent
    weights_path = model_dir / "weights" / "yolov7-w6-pose.pt"

    if not weights_path.exists():
        raise FileNotFoundError(f"Model weights not found: {weights_path}")

    # Add local lib directory to path for imports
    lib_dir = model_dir / "lib"
    if lib_dir.exists():
        sys.path.insert(0, str(lib_dir))

    from models.experimental import attempt_load

    # Load model
    model = attempt_load(str(weights_path), map_location='cpu')
    model.eval()

    return model


def _run_inference_with_model(frame: np.ndarray, model) -> Dict[str, Any]:
    """
    Run actual inference using loaded YOLOv7-Pose model.

    Args:
        frame: BGR frame (H, W, 3)
        model: Loaded PyTorch model

    Returns:
        Detection results
    """
    import torch
    import cv2
    import sys

    # Add local lib directory to path for utils
    model_dir = Path(__file__).parent
    lib_dir = model_dir / "lib"
    if lib_dir.exists():
        sys.path.insert(0, str(lib_dir))

    from utils.general import non_max_suppression_kpt
    from utils.plots import output_to_keypoint

    # Preprocess
    img = cv2.resize(frame, (640, 640))
    img = img[:, :, ::-1].transpose(2, 0, 1)  # BGR to RGB, HWC to CHW
    img = np.ascontiguousarray(img)
    img_tensor = torch.from_numpy(img).float()
    img_tensor /= 255.0  # Normalize
    if img_tensor.ndimension() == 3:
        img_tensor = img_tensor.unsqueeze(0)

    # Inference
    with torch.no_grad():
        predictions = model(img_tensor)[0]

    # Post-process
    output = non_max_suppression_kpt(
        predictions,
        conf_thres=0.25,
        iou_thres=0.65,
        nc=1,
        nkpt=17,
        kpt_label=True
    )

    with torch.no_grad():
        output = output_to_keypoint(output)

    # Extract detections
    detections = []
    for idx in range(output.shape[0]):
        x_center = float(output[idx, 2])
        y_center = float(output[idx, 3])
        w = float(output[idx, 4])
        h = float(output[idx, 5])
        conf = float(output[idx, 6])

        x1 = x_center - w / 2
        y1 = y_center - h / 2
        x2 = x_center + w / 2
        y2 = y_center + h / 2

        # Extract keypoints
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

        detections.append({
            "bbox": [x1, y1, x2, y2],
            "confidence": conf,
            "keypoints": keypoints
        })

    # Analyze for falls
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
        "metadata": {
            "model_name": "fall_detector",
            "model_version": "1.0.0",
            "mode": "inference",
            "frame_shape": list(frame.shape)
        }
    }


def _analyze_pose_for_fall(keypoints: List[Dict]) -> Tuple[bool, float, Optional[str]]:
    """
    Analyze pose keypoints to detect falls.

    Args:
        keypoints: List of 17 keypoint dicts with 'x', 'y', 'confidence'

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
            hip_center_y = shoulder_center_y + 100

        # Fall detection logic
        fall_indicators = []

        # 1. Check if person is horizontal
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


# Optional: Model initialization function (called once during loading)
def load_model(weights_path: str, **kwargs) -> Any:
    """
    Load YOLOv7-Pose model weights (stub for MVP).

    Args:
        weights_path: Path to model weights directory
        **kwargs: Additional loading parameters

    Returns:
        Loaded model object (or None for MVP stub)

    TODO Phase 2: Implement actual model loading:
        from pathlib import Path
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "fall-detection-model"))
        from models.experimental import attempt_load
        model = attempt_load(str(weights_path / "yolov7-w6-pose.pt"), map_location='cpu')
        model.eval()
        return model
    """
    # MVP: No model loading, just validate weights path exists
    from pathlib import Path

    weights_dir = Path(weights_path)
    if not weights_dir.exists():
        raise FileNotFoundError(f"Weights directory not found: {weights_path}")

    # Return None for MVP (model loading deferred to Phase 2)
    return None

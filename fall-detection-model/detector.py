"""
Fall Detection Model using Pose Estimation
Production inference code for detecting falls using human pose keypoints
"""

import torch
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging
import math
import sys

# Add models directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from models.experimental import attempt_load
from utils.general import non_max_suppression_kpt
from utils.plots import output_to_keypoint

logger = logging.getLogger(__name__)

class FallDetector:
    """
    Detects falls using human pose estimation and keypoint analysis
    """
    
    def __init__(self, model_path: str, confidence_threshold: float = 0.6):
        """
        Initialize the fall detector
        
        Args:
            model_path: Path to the YOLOv7 pose model weights
            confidence_threshold: Minimum confidence for detections
        """
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.model = None
        
        # COCO pose keypoint indices
        self.keypoint_names = [
            'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
            'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
            'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
            'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
        ]
        
        # Keypoint connections for skeleton drawing
        self.skeleton = [
            [16, 14], [14, 12], [17, 15], [15, 13], [12, 13],
            [6, 12], [7, 13], [6, 7], [6, 8], [7, 9],
            [8, 10], [9, 11], [2, 3], [1, 2], [1, 3],
            [2, 4], [3, 5], [4, 6], [5, 7]
        ]
        
        self._load_model()
    
    def _load_model(self):
        """Load the YOLOv7 pose model"""
        try:
            if not self.model_path.exists():
                raise FileNotFoundError(f"Model file not found: {self.model_path}")

            # Load YOLOv7 pose model using proper loader
            logger.info(f"Loading YOLOv7 pose model from {self.model_path}")
            self.model = attempt_load(str(self.model_path), map_location='cpu')
            self.model.eval()

            logger.info(f"Successfully loaded fall detection model from {self.model_path}")

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
    
    def detect(self, image: np.ndarray) -> Dict:
        """
        Detect falls in an image using pose estimation
        
        Args:
            image: Input image as numpy array (BGR format)
            
        Returns:
            Dictionary containing detection results
        """
        if self.model is None:
            raise RuntimeError("Model not loaded")
        
        try:
            # Preprocess image
            img_tensor = self._preprocess_image(image)
            
            # Run inference
            with torch.no_grad():
                predictions = self.model(img_tensor)[0]
            
            # Post-process results
            detections = self._postprocess_predictions(predictions, image.shape)
            
            # Analyze poses for fall detection
            fall_detected = False
            fall_confidence = 0.0
            fall_type = None
            
            for detection in detections:
                is_fall, confidence, f_type = self._analyze_pose_for_fall(detection["keypoints"])
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
                "model_name": "fall_detector"
            }
    
    def _preprocess_image(self, image: np.ndarray) -> torch.Tensor:
        """Preprocess image for YOLOv7 pose model"""
        # Resize image to model input size (typically 640x640)
        img = cv2.resize(image, (640, 640))
        img = img[:, :, ::-1].transpose(2, 0, 1)  # BGR to RGB, HWC to CHW
        img = np.ascontiguousarray(img)
        img = torch.from_numpy(img).float()
        img /= 255.0  # Normalize to 0-1
        if img.ndimension() == 3:
            img = img.unsqueeze(0)
        return img
    
    def _postprocess_predictions(self, predictions: torch.Tensor, orig_shape: Tuple[int, int, int]) -> List[Dict]:
        """Post-process model predictions to extract pose keypoints"""
        detections = []

        # Apply NMS with keypoint support
        output = non_max_suppression_kpt(
            predictions,
            conf_thres=0.25,  # Lower threshold to detect more people
            iou_thres=0.65,
            nc=1,  # Number of classes (person only)
            nkpt=17,  # Number of keypoints
            kpt_label=True
        )

        # Process detections
        # output_to_keypoint converts to: [batch_id, cls, x_center, y_center, w, h, conf, kpt1_x, kpt1_y, kpt1_conf, ...]
        with torch.no_grad():
            output = output_to_keypoint(output)

        logger.info(f"Detections found: {output.shape[0]}")

        # Extract detection info for each person detected
        # Format: [batch_id, cls, x_center, y_center, w, h, conf, 17*3 keypoint values]
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

            # Log first detection for debugging
            if idx == 0:
                logger.info(f"First detection - bbox: [{x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}], conf: {conf:.2f}")
                visible_kpts = sum(1 for kp in keypoints if kp['confidence'] > 0.5)
                logger.info(f"Visible keypoints: {visible_kpts}/17")

        logger.info(f"Returning {len(detections)} detections")
        return detections
    
    def _analyze_pose_for_fall(self, keypoints: List[Dict]) -> Tuple[bool, float, Optional[str]]:
        """
        Analyze pose keypoints to detect falls

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
            if abs(shoulder_center_y - hip_center_y) < 50:  # Nearly same height
                fall_indicators.append(("horizontal_body", 0.8))

            # 2. Check if head is lower than hips
            if nose['confidence'] > 0.3 and hip_center_y > 0:
                if nose['y'] > hip_center_y + 20:  # Head below hips
                    fall_indicators.append(("head_below_hips", 0.7))

            # 3. Check limb positions
            if left_ankle['confidence'] > 0.3 and right_ankle['confidence'] > 0.3:
                ankle_distance = abs(left_ankle['x'] - right_ankle['x'])
                if ankle_distance > 100:  # Legs spread wide
                    fall_indicators.append(("legs_spread", 0.6))

            # 4. Overall body compactness (person might be on ground)
            visible_kpts = [kp for kp in keypoints if kp['confidence'] > 0.3]
            if len(visible_kpts) > 10:  # Many keypoints visible
                y_coords = [kp['y'] for kp in visible_kpts]
                if y_coords:
                    y_range = max(y_coords) - min(y_coords)
                    if y_range < 150:  # Very compact vertically
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
    
    def annotate_image(self, image: np.ndarray, detections: List[Dict]) -> np.ndarray:
        """
        Draw pose keypoints and skeleton on the image
        
        Args:
            image: Input image
            detections: List of detection dictionaries with keypoints
            
        Returns:
            Annotated image
        """
        annotated_image = image.copy()
        
        for detection in detections:
            keypoints = detection["keypoints"]
            
            # Draw skeleton
            for connection in self.skeleton:
                kpt_a, kpt_b = connection
                if (kpt_a - 1 < len(keypoints) and kpt_b - 1 < len(keypoints) and
                    keypoints[kpt_a - 1][2] > 0.3 and keypoints[kpt_b - 1][2] > 0.3):
                    
                    x1, y1 = int(keypoints[kpt_a - 1][0]), int(keypoints[kpt_a - 1][1])
                    x2, y2 = int(keypoints[kpt_b - 1][0]), int(keypoints[kpt_b - 1][1])
                    cv2.line(annotated_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # Draw keypoints
            for i, (x, y, conf) in enumerate(keypoints):
                if conf > 0.3:
                    cv2.circle(annotated_image, (int(x), int(y)), 5, (0, 0, 255), -1)
            
            # Draw bounding box
            x1, y1, x2, y2 = [int(coord) for coord in detection["bbox"]]
            cv2.rectangle(annotated_image, (x1, y1), (x2, y2), (255, 0, 0), 2)
        
        return annotated_image

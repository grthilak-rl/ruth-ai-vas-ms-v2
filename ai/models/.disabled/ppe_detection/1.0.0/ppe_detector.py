"""
PPE Detection Model using YOLOv8
Production inference code for detecting Personal Protective Equipment (PPE)
Supports multiple specialized models for different PPE items
"""

import torch
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


class DetectionMode(str, Enum):
    """Detection modes for PPE analysis"""
    PRESENCE = "presence"   # Detect PPE items that are present (both_classes models)
    VIOLATION = "violation"  # Detect missing PPE items (no_classes models)
    FULL = "full"           # Run both presence and violation detection


@dataclass
class PPEModelConfig:
    """Configuration for a single PPE detection model"""
    name: str
    weight_file: str
    category: str  # "presence" or "violation"
    ppe_item: str
    confidence_threshold: float = 0.5
    enabled: bool = True


@dataclass
class PPEDetection:
    """Single PPE detection result"""
    item: str
    status: str  # "present" or "missing"
    confidence: float
    bbox: List[float]
    class_id: int
    model_source: str


@dataclass
class PPEInferenceResult:
    """Complete PPE inference result for an image"""
    detections: List[Dict]
    persons_detected: int
    violations: List[str]
    ppe_present: List[str]
    timestamp: str
    inference_time_ms: float
    model_name: str = "ppe_detector"
    model_version: str = "1.0.0"
    mode: str = "full"


class PPEDetector:
    """
    Multi-model PPE detector using YOLOv8 models
    Supports configurable model selection and detection modes
    """

    # Default confidence thresholds per PPE item
    # Some items are harder to detect, so they have lower thresholds
    DEFAULT_THRESHOLDS = {
        "hardhat": 0.5,
        "vest": 0.5,
        "goggles": 0.45,
        "gloves": 0.4,
        "boots": 0.45,
        "mask": 0.45,
        "person": 0.5,
        # Violation models (no_* prefix)
        "no_hardhat": 0.5,
        "no_vest": 0.5,
        "no_goggles": 0.45,
        "no_gloves": 0.4,
        "no_boots": 0.45,
        "no_mask": 0.45,
    }

    # Mapping from violation model to PPE item name
    VIOLATION_TO_ITEM = {
        "no_hardhat": "hardhat",
        "no_vest": "vest",
        "no_goggles": "goggles",
        "no_gloves": "gloves",
        "no_boots": "boots",
        "no_mask": "mask",
    }

    def __init__(
        self,
        weights_dir: str,
        device: str = "auto",
        global_confidence_threshold: float = 0.5,
        enabled_models: Optional[Set[str]] = None,
        custom_thresholds: Optional[Dict[str, float]] = None
    ):
        """
        Initialize the PPE detector with multiple YOLOv8 models

        Args:
            weights_dir: Path to the weights directory containing both_classes/ and no_classes/
            device: Device to run inference on ("cpu", "cuda", "auto")
            global_confidence_threshold: Default confidence threshold for all models
            enabled_models: Set of model names to enable (None = all models)
            custom_thresholds: Custom confidence thresholds per model/item
        """
        self.weights_dir = Path(weights_dir)
        self.global_confidence_threshold = global_confidence_threshold
        self.enabled_models = enabled_models
        self.custom_thresholds = custom_thresholds or {}

        # Merge custom thresholds with defaults
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **self.custom_thresholds}

        # Determine device
        if device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        # Model storage
        self.presence_models: Dict[str, any] = {}  # both_classes models
        self.violation_models: Dict[str, any] = {}  # no_classes models
        self.model_configs: Dict[str, PPEModelConfig] = {}

        # Load models
        self._discover_and_load_models()

    def _discover_and_load_models(self):
        """Discover and load all available PPE detection models"""
        try:
            from ultralytics import YOLO
        except ImportError:
            logger.error("ultralytics package not installed. Run: pip install ultralytics")
            raise RuntimeError("ultralytics package is required for YOLOv8 models")

        both_classes_dir = self.weights_dir / "both_classes"
        no_classes_dir = self.weights_dir / "no_classes"

        loaded_count = 0

        # Load presence models (both_classes)
        if both_classes_dir.exists():
            for weight_file in both_classes_dir.glob("*.pt"):
                model_name = weight_file.stem  # e.g., "hardhat", "vest"

                # Check if model is enabled
                if self.enabled_models is not None and model_name not in self.enabled_models:
                    logger.info(f"Skipping disabled model: {model_name}")
                    continue

                try:
                    logger.info(f"Loading presence model: {model_name} from {weight_file}")
                    model = YOLO(str(weight_file))
                    model.to(self.device)

                    self.presence_models[model_name] = model
                    self.model_configs[model_name] = PPEModelConfig(
                        name=model_name,
                        weight_file=str(weight_file),
                        category="presence",
                        ppe_item=model_name,
                        confidence_threshold=self.thresholds.get(model_name, self.global_confidence_threshold)
                    )
                    loaded_count += 1
                    logger.info(f"Successfully loaded presence model: {model_name}")
                except Exception as e:
                    logger.error(f"Failed to load presence model {model_name}: {e}")

        # Load violation models (no_classes)
        if no_classes_dir.exists():
            for weight_file in no_classes_dir.glob("*.pt"):
                model_name = weight_file.stem  # e.g., "no_hardhat", "no_vest"

                # Check if model is enabled
                if self.enabled_models is not None and model_name not in self.enabled_models:
                    logger.info(f"Skipping disabled model: {model_name}")
                    continue

                try:
                    logger.info(f"Loading violation model: {model_name} from {weight_file}")
                    model = YOLO(str(weight_file))
                    model.to(self.device)

                    ppe_item = self.VIOLATION_TO_ITEM.get(model_name, model_name.replace("no_", ""))

                    self.violation_models[model_name] = model
                    self.model_configs[model_name] = PPEModelConfig(
                        name=model_name,
                        weight_file=str(weight_file),
                        category="violation",
                        ppe_item=ppe_item,
                        confidence_threshold=self.thresholds.get(model_name, self.global_confidence_threshold)
                    )
                    loaded_count += 1
                    logger.info(f"Successfully loaded violation model: {model_name}")
                except Exception as e:
                    logger.error(f"Failed to load violation model {model_name}: {e}")

        logger.info(f"Loaded {loaded_count} PPE detection models "
                   f"({len(self.presence_models)} presence, {len(self.violation_models)} violation) "
                   f"on device: {self.device}")

        if loaded_count == 0:
            logger.warning("No PPE detection models were loaded. Check weights directory.")

    def get_model_status(self) -> Dict:
        """Get status of all loaded models"""
        return {
            "device": self.device,
            "presence_models": {
                name: {
                    "loaded": True,
                    "ppe_item": self.model_configs[name].ppe_item,
                    "threshold": self.model_configs[name].confidence_threshold
                }
                for name in self.presence_models
            },
            "violation_models": {
                name: {
                    "loaded": True,
                    "ppe_item": self.model_configs[name].ppe_item,
                    "threshold": self.model_configs[name].confidence_threshold
                }
                for name in self.violation_models
            },
            "total_models_loaded": len(self.presence_models) + len(self.violation_models)
        }

    def detect(
        self,
        image: np.ndarray,
        mode: DetectionMode = DetectionMode.FULL,
        models: Optional[Set[str]] = None,
        confidence_override: Optional[float] = None
    ) -> Dict:
        """
        Run PPE detection on an image

        Args:
            image: Input image as numpy array (BGR format from OpenCV)
            mode: Detection mode (presence, violation, or full)
            models: Specific models to run (None = all loaded models for mode)
            confidence_override: Override confidence threshold for this detection

        Returns:
            Dictionary containing detection results
        """
        start_time = time.time()

        all_detections: List[Dict] = []
        violations: List[str] = []
        ppe_present: List[str] = []
        persons_detected = 0

        # Run presence models if mode is PRESENCE or FULL
        if mode in (DetectionMode.PRESENCE, DetectionMode.FULL):
            presence_results = self._run_model_group(
                image,
                self.presence_models,
                "presence",
                models,
                confidence_override
            )
            all_detections.extend(presence_results["detections"])
            ppe_present.extend(presence_results["items_found"])
            persons_detected = max(persons_detected, presence_results.get("persons", 0))

        # Run violation models if mode is VIOLATION or FULL
        if mode in (DetectionMode.VIOLATION, DetectionMode.FULL):
            violation_results = self._run_model_group(
                image,
                self.violation_models,
                "violation",
                models,
                confidence_override
            )
            all_detections.extend(violation_results["detections"])
            violations.extend(violation_results["items_found"])

        # Calculate inference time
        inference_time_ms = (time.time() - start_time) * 1000

        # Determine overall violation status
        violation_detected = len(violations) > 0

        return {
            "violation_detected": violation_detected,
            "violation_type": "ppe_violation" if violation_detected else None,
            "severity": self._calculate_severity(violations),
            "confidence": self._calculate_overall_confidence(all_detections),
            "detections": all_detections,
            "persons_detected": persons_detected,
            "violations": violations,
            "ppe_present": ppe_present,
            "detection_count": len(all_detections),
            "model_name": "ppe_detector",
            "model_version": "1.0.0",
            "mode": mode.value if hasattr(mode, 'value') else mode,
            "inference_time_ms": round(inference_time_ms, 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

    def _run_model_group(
        self,
        image: np.ndarray,
        model_group: Dict[str, any],
        category: str,
        filter_models: Optional[Set[str]],
        confidence_override: Optional[float]
    ) -> Dict:
        """Run a group of models (presence or violation) on an image"""
        detections = []
        items_found = []
        persons_count = 0

        for model_name, model in model_group.items():
            # Skip if filtering and model not in filter
            if filter_models is not None and model_name not in filter_models:
                continue

            config = self.model_configs[model_name]
            threshold = confidence_override or config.confidence_threshold

            try:
                # Run inference
                results = model(image, conf=threshold, verbose=False)

                # Process results
                for result in results:
                    boxes = result.boxes
                    if boxes is None:
                        continue

                    for i in range(len(boxes)):
                        # Get detection data
                        bbox = boxes.xyxy[i].cpu().numpy().tolist()
                        confidence = float(boxes.conf[i].cpu().numpy())
                        class_id = int(boxes.cls[i].cpu().numpy())

                        # Get class name from model
                        class_name = result.names.get(class_id, str(class_id))

                        # Track persons for counting
                        if class_name.lower() == "person" or model_name == "person":
                            persons_count += 1

                        # Determine item and status
                        if category == "presence":
                            item = config.ppe_item
                            status = "present"
                            if item not in items_found and item != "person":
                                items_found.append(item)
                        else:  # violation
                            item = config.ppe_item
                            status = "missing"
                            if item not in items_found:
                                items_found.append(item)

                        detection = {
                            "item": item,
                            "status": status,
                            "confidence": round(confidence, 4),
                            "bbox": [round(coord, 2) for coord in bbox],
                            "class_id": class_id,
                            "class_name": class_name,
                            "model_source": model_name
                        }
                        detections.append(detection)

            except Exception as e:
                logger.error(f"Error running model {model_name}: {e}")
                continue

        return {
            "detections": detections,
            "items_found": items_found,
            "persons": persons_count
        }

    def _calculate_severity(self, violations: List[str]) -> str:
        """Calculate severity based on violation types"""
        if not violations:
            return "low"

        # Critical PPE items that increase severity
        critical_items = {"hardhat", "vest"}

        critical_count = sum(1 for v in violations if v in critical_items)

        if critical_count >= 2:
            return "critical"
        elif critical_count == 1:
            return "high"
        elif len(violations) >= 3:
            return "high"
        elif len(violations) >= 1:
            return "medium"
        return "low"

    def _calculate_overall_confidence(self, detections: List[Dict]) -> float:
        """Calculate overall confidence from all detections"""
        if not detections:
            return 0.0

        confidences = [d["confidence"] for d in detections]
        return round(sum(confidences) / len(confidences), 4)

    def detect_batch(
        self,
        images: List[np.ndarray],
        mode: DetectionMode = DetectionMode.FULL,
        models: Optional[Set[str]] = None,
        confidence_override: Optional[float] = None
    ) -> List[Dict]:
        """
        Run PPE detection on a batch of images

        Args:
            images: List of input images as numpy arrays (BGR format)
            mode: Detection mode
            models: Specific models to run
            confidence_override: Override confidence threshold

        Returns:
            List of detection results for each image
        """
        results = []
        for image in images:
            result = self.detect(image, mode, models, confidence_override)
            results.append(result)
        return results

    def get_supported_items(self) -> Dict[str, List[str]]:
        """Get list of supported PPE items by category"""
        presence_items = [
            self.model_configs[name].ppe_item
            for name in self.presence_models
            if self.model_configs[name].ppe_item != "person"
        ]
        violation_items = [
            self.model_configs[name].ppe_item
            for name in self.violation_models
        ]
        return {
            "presence_detection": list(set(presence_items)),
            "violation_detection": list(set(violation_items))
        }

    def update_threshold(self, model_name: str, threshold: float):
        """Update confidence threshold for a specific model"""
        if model_name in self.model_configs:
            self.model_configs[model_name].confidence_threshold = threshold
            logger.info(f"Updated threshold for {model_name} to {threshold}")
        else:
            logger.warning(f"Model {model_name} not found")

    def enable_model(self, model_name: str):
        """Enable a specific model"""
        if model_name in self.model_configs:
            self.model_configs[model_name].enabled = True
            logger.info(f"Enabled model: {model_name}")

    def disable_model(self, model_name: str):
        """Disable a specific model"""
        if model_name in self.model_configs:
            self.model_configs[model_name].enabled = False
            logger.info(f"Disabled model: {model_name}")

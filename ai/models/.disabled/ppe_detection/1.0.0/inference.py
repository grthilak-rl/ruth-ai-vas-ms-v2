"""
PPE Detection Inference Module
Multi-model YOLOv8-based PPE detector for AI Runtime

Uses lazy loading pattern - detector is initialized on first inference.
"""

import sys
from pathlib import Path
import logging
from typing import Dict, Any
import time
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Model state (lazy loaded on first inference)
_model = None
_model_initialized = False
_model_load_failed = False


def infer(frame: np.ndarray, config: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
    """Run PPE detection inference on a frame.

    Args:
        frame: Input frame (numpy array, BGR format)
        config: Inference configuration (optional)
        **kwargs: Additional arguments

    Returns:
        Dictionary containing detection results
    """
    global _model, _model_initialized, _model_load_failed

    # Validate input
    if frame is None:
        raise ValueError("Frame is None")

    if not isinstance(frame, np.ndarray):
        raise ValueError(f"Frame must be numpy array, got {type(frame)}")

    # Lazy load model on first inference
    if not _model_initialized and not _model_load_failed:
        try:
            _lazy_load_model()
            _model_initialized = True
            logger.info("PPE detection model initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PPE detection model: {e}", exc_info=True)
            _model_load_failed = True
            # Return stub response
            return _stub_response()

    # If model load failed, return stub
    if _model_load_failed or _model is None:
        return _stub_response()

    # Get configuration (use empty dict if not provided)
    if config is None:
        config = {}

    start_time = time.time()

    try:
        # Get detection mode from config
        mode = config.get("detection_mode", "full")  # "presence", "violation", or "full"

        # Run detection - result is a dict
        result = _model.detect(
            image=frame,
            mode=mode
        )

        inference_time_ms = (time.time() - start_time) * 1000

        # Get violations list
        violations = result.get("violations", [])
        violation_detected = len(violations) > 0

        # Determine violation type and severity
        violation_type = result.get("violation_type")
        severity = result.get("severity", "low")

        if violation_detected:
            # Prioritize critical PPE items
            critical_items = {"hardhat", "vest"}
            high_priority_items = {"goggles", "mask"}

            # Check for critical violations
            if any(item in violations for item in critical_items):
                severity = "critical"
                # More specific violation type
                if "hardhat" in violations:
                    violation_type = "missing_hardhat"
                elif "vest" in violations:
                    violation_type = "missing_vest"
            elif any(item in violations for item in high_priority_items):
                severity = "high"
                if "goggles" in violations:
                    violation_type = "missing_goggles"
                elif "mask" in violations:
                    violation_type = "missing_mask"
            else:
                severity = "medium"
                if not violation_type:
                    violation_type = "ppe_violation"

        # Build response conforming to model.yaml contract
        response = {
            "violation_detected": violation_detected,
            "violation_type": violation_type,
            "severity": severity,
            "confidence": round(result.get("confidence", 0.0), 3),
            "detections": result.get("detections", []),
            "persons_detected": result.get("persons_detected", 0),
            "violations": violations,
            "ppe_present": result.get("ppe_present", []),
            "metadata": {
                "inference_time_ms": round(inference_time_ms, 2),
                "model_name": result.get("model_name", "ppe_detector"),
                "model_version": result.get("model_version", "1.0.0"),
                "mode": result.get("mode", mode),
                "timestamp": result.get("timestamp", "")
            }
        }

        logger.debug(
            f"PPE detection complete: violation={violation_detected}, "
            f"persons={result.get('persons_detected', 0)}, "
            f"violations={violations}, "
            f"time={inference_time_ms:.1f}ms"
        )

        return response

    except Exception as e:
        logger.error(f"PPE detection inference failed: {e}", exc_info=True)
        # Return stub response on error
        return _stub_response()


def _lazy_load_model():
    """Lazy load the PPE detector with all models."""
    global _model

    # Import detector
    sys.path.insert(0, str(Path(__file__).parent))
    from ppe_detector import PPEDetector

    # Initialize detector with weights directory
    model_dir = Path(__file__).parent
    weights_dir = model_dir / "weights"

    if not weights_dir.exists():
        raise FileNotFoundError(f"Weights directory not found: {weights_dir}")

    logger.info(f"Initializing PPE detector with weights from: {weights_dir}")

    # Initialize detector with all models enabled
    _model = PPEDetector(
        weights_dir=str(weights_dir),
        device="auto",
        global_confidence_threshold=0.5,
        enabled_models=None  # None = all models
    )

    logger.info(f"Loaded presence models: {list(_model.presence_models.keys())}")
    logger.info(f"Loaded violation models: {list(_model.violation_models.keys())}")


def _stub_response() -> Dict[str, Any]:
    """Return stub response when model not available."""
    return {
        "violation_detected": False,
        "violation_type": None,
        "severity": "low",
        "confidence": 0.0,
        "detections": [],
        "persons_detected": 0,
        "violations": [],
        "ppe_present": [],
        "metadata": {
            "model_name": "ppe_detector",
            "model_version": "1.0.0",
            "mode": "stub",
            "note": "Model not loaded - using stub response"
        }
    }


def cleanup() -> None:
    """Cleanup model resources."""
    global _model, _model_initialized

    logger.info("Cleaning up PPE detection model")
    _model = None
    _model_initialized = False

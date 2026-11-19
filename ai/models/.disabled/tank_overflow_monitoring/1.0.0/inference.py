"""
Tank Overflow Monitoring Inference Module
Computer vision-based tank level monitoring for AI Runtime

Uses edge detection to detect liquid surface and calculate tank level percentage.
"""

import sys
from pathlib import Path
import logging
from typing import Dict, Any
import time
import numpy as np
import cv2

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Model state (lazy loaded on first inference)
_detector = None
_model_initialized = False
_model_load_failed = False

# Default configuration
DEFAULT_TANK_CONFIG = {
    "capacity_liters": 1000,
    "alert_threshold": 90,
    "tank_corners": None,  # Will be set from config or frame dimensions
}

def infer(frame: np.ndarray, config: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
    """Run tank overflow monitoring inference on a frame.

    Args:
        frame: Input frame (numpy array, BGR format)
        config: Inference configuration containing:
            - capacity_liters: Tank capacity in liters (default: 1000)
            - alert_threshold: Alert threshold percentage (default: 90)
            - tank_corners: List of 4 [x, y] points defining tank area (optional)
        **kwargs: Additional arguments

    Returns:
        Dictionary containing tank level monitoring results
    """
    global _detector, _model_initialized, _model_load_failed

    # Validate input
    if frame is None:
        raise ValueError("Frame is None")

    if not isinstance(frame, np.ndarray):
        raise ValueError(f"Frame must be numpy array, got {type(frame)}")

    # Lazy load detector on first inference
    if not _model_initialized and not _model_load_failed:
        try:
            _lazy_load_detector()
            _model_initialized = True
            logger.info("Tank overflow monitoring detector initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize tank overflow detector: {e}", exc_info=True)
            _model_load_failed = True
            return _stub_response()

    # If detector load failed, return stub
    if _model_load_failed or _detector is None:
        return _stub_response()

    # Get configuration (merge with defaults)
    if config is None:
        config = {}

    tank_config = DEFAULT_TANK_CONFIG.copy()
    tank_config.update(config)

    start_time = time.time()

    try:
        # Detect liquid level
        result = _detector.detect_level(frame, tank_config)

        inference_time_ms = (time.time() - start_time) * 1000

        level_percent = result.get("level_percent", 0.0)
        capacity = tank_config.get("capacity_liters", 1000)
        level_liters = (level_percent / 100.0) * capacity
        threshold = tank_config.get("alert_threshold", 90)

        # Determine violation status and severity
        violation_detected = False
        violation_type = None
        severity = "low"

        if level_percent >= 95:
            violation_detected = True
            violation_type = "tank_critical_high"
            severity = "critical"
        elif level_percent >= threshold:
            violation_detected = True
            violation_type = "tank_overflow_warning"
            severity = "high"
        elif level_percent <= 10:
            violation_detected = True
            violation_type = "tank_critical_low"
            severity = "critical"
        elif level_percent <= 25:
            severity = "medium"
        else:
            severity = "low"

        # Build response conforming to model.yaml contract
        response = {
            "violation_detected": violation_detected,
            "violation_type": violation_type,
            "severity": severity,
            "confidence": result.get("confidence", 0.8),
            "level_percent": round(level_percent, 2),
            "level_liters": round(level_liters, 2),
            "capacity_liters": capacity,
            "detections": result.get("detections", []),
            "metadata": {
                "inference_time_ms": round(inference_time_ms, 2),
                "model_name": "tank_overflow_monitor",
                "model_version": "1.0.0",
                "alert_threshold": threshold,
                "status": _get_status(level_percent),
                "timestamp": result.get("timestamp", "")
            }
        }

        return response

    except Exception as e:
        logger.error(f"Tank overflow monitoring inference failed: {e}", exc_info=True)
        return _stub_response()


def _lazy_load_detector():
    """Lazy load the tank overflow detector."""
    global _detector

    sys.path.insert(0, str(Path(__file__).parent))
    from tank_detector import TankOverflowDetector

    logger.info("Initializing tank overflow detector")

    _detector = TankOverflowDetector()

    logger.info("Tank overflow detector loaded successfully")


def _get_status(level_percent: float) -> str:
    """Get status string based on level percentage."""
    if level_percent >= 95:
        return "CRITICAL - OVERFLOW RISK"
    elif level_percent >= 90:
        return "WARNING - NEARLY FULL"
    elif level_percent >= 75:
        return "HIGH"
    elif level_percent <= 10:
        return "CRITICAL LOW"
    elif level_percent <= 25:
        return "LOW"
    else:
        return "NORMAL"


def _stub_response() -> Dict[str, Any]:
    """Return stub response when model not available."""
    return {
        "violation_detected": False,
        "violation_type": None,
        "severity": "low",
        "confidence": 0.0,
        "level_percent": 0.0,
        "level_liters": 0.0,
        "capacity_liters": 1000,
        "detections": [],
        "metadata": {
            "model_name": "tank_overflow_monitor",
            "model_version": "1.0.0",
            "mode": "stub",
            "note": "Model not loaded - using stub response"
        }
    }

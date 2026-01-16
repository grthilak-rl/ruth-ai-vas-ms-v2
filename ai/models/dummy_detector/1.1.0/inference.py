"""
Dummy Detector Inference v1.1.0

Enhanced version with improved "detection" logic.
Used for platform validation testing.
"""

import logging
import hashlib
from typing import Any, Dict

logger = logging.getLogger(__name__)


def infer(frame: Any, **kwargs: Any) -> Dict[str, Any]:
    """
    Run dummy detection on a frame (v1.1.0).

    Args:
        frame: Input frame (numpy array)
        **kwargs: Additional arguments (ignored)

    Returns:
        Detection result dictionary
    """
    try:
        # Compute a deterministic "detection" based on frame hash
        if hasattr(frame, 'tobytes'):
            frame_hash = hashlib.md5(frame.tobytes()).hexdigest()
        else:
            frame_hash = "unknown"

        # v1.1.0 uses different detection threshold
        first_two = frame_hash[:2] if len(frame_hash) >= 2 else 'ff'
        value = int(first_two, 16)
        detected = value < 128  # Different threshold than v1.0.0
        confidence = value / 255.0

        return {
            "event_type": "detected" if detected else "not_detected",
            "confidence": confidence,
            "frame_hash": frame_hash[:8],
            "model_name": "dummy_detector",
            "model_version": "1.1.0",  # Note: different version
        }

    except Exception as e:
        logger.error(f"Dummy detection v1.1 failed: {e}")
        return {
            "event_type": "not_detected",
            "confidence": 0.0,
            "error": str(e),
            "model_name": "dummy_detector",
            "model_version": "1.1.0",
        }

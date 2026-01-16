"""
Dummy Detector Inference

A simple model that always returns a deterministic result.
Used for platform validation testing.
"""

import logging
import hashlib
from typing import Any, Dict

logger = logging.getLogger(__name__)


def infer(frame: Any, **kwargs: Any) -> Dict[str, Any]:
    """
    Run dummy detection on a frame.

    This model simply returns a deterministic result based on
    frame properties, with no actual ML inference.

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

        # Simple deterministic logic: "detect" if hash starts with 0-7
        first_char = frame_hash[0] if frame_hash else 'f'
        detected = first_char in '01234567'
        confidence = int(first_char, 16) / 15.0 if first_char.isalnum() else 0.5

        return {
            "event_type": "detected" if detected else "not_detected",
            "confidence": confidence,
            "frame_hash": frame_hash[:8],
            "model_name": "dummy_detector",
            "model_version": "1.0.0",
        }

    except Exception as e:
        logger.error(f"Dummy detection failed: {e}")
        return {
            "event_type": "not_detected",
            "confidence": 0.0,
            "error": str(e),
            "model_name": "dummy_detector",
            "model_version": "1.0.0",
        }

"""
Fall Detection Postprocessing

Converts raw model output to standardized detection format.
"""

from typing import Any


def postprocess(raw_output: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    Postprocess inference output to standardized format.

    The inference module already returns a standardized format,
    so this function performs minimal transformation.

    Args:
        raw_output: Raw output from infer()
        **kwargs: Additional arguments (ignored)

    Returns:
        Standardized detection result
    """
    # Map internal violation_type to standard event_type
    event_type = "no_fall"
    if raw_output.get("violation_detected", False):
        violation_type = raw_output.get("violation_type")
        if violation_type == "fall_detected":
            event_type = "fall_detected"
        elif violation_type == "possible_fall":
            event_type = "possible_fall"

    # Build standardized output
    result = {
        "event_type": event_type,
        "confidence": raw_output.get("confidence", 0.0),
        "bounding_boxes": [],
        "metadata": {
            "detection_count": raw_output.get("detection_count", 0),
            "severity": raw_output.get("severity", "low"),
            "violation_type": raw_output.get("violation_type"),
        },
    }

    # Transform detections to bounding_boxes format
    for detection in raw_output.get("detections", []):
        bbox_entry = {
            "bbox": detection.get("bbox", []),
            "confidence": detection.get("confidence", 0.0),
            "keypoints": detection.get("keypoints", []),
        }
        result["bounding_boxes"].append(bbox_entry)

    return result

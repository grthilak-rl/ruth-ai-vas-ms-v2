"""
Direct test of fall_detection plugin inference

Tests that the fall_detection model can load and produce inference results
without going through the full unified runtime.
"""

import sys
import numpy as np
from pathlib import Path

# Import directly from the inference module
import importlib.util

# Load the inference module directly
inference_path = Path(__file__).parent.parent / "models/fall_detection/1.0.0/inference.py"
spec = importlib.util.spec_from_file_location("fall_detection_inference", inference_path)
inference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inference)

def test_fall_detection_real_inference():
    """Test fall_detection with real inference"""
    # Create a test frame (BGR format)
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    # Run inference
    result = inference.infer(frame)

    # Verify response structure
    assert "violation_detected" in result
    assert "violation_type" in result
    assert "confidence" in result
    assert "detections" in result
    assert "detection_count" in result
    assert "metadata" in result

    # Check mode
    mode = result.get("metadata", {}).get("mode", "unknown")
    print(f"✓ Fall detection test passed")
    print(f"  Mode: {mode}")
    print(f"  Detection count: {result['detection_count']}")
    print(f"  Violation detected: {result['violation_detected']}")

def test_fall_detection_with_real_weights():
    """Test fall_detection with actual model weights"""
    # First, try to load the model to trigger weight loading
    import torch

    weights_path = Path(__file__).parent.parent / "models/fall_detection/1.0.0/weights/yolov7-w6-pose.pt"

    if not weights_path.exists():
        print(f"⚠ Weights not found at {weights_path}, skipping real inference test")
        return

    # Need to add fall-detection-model to path for utils
    fall_detection_root = Path(__file__).parent.parent.parent / "fall-detection-model"
    if fall_detection_root.exists():
        sys.path.insert(0, str(fall_detection_root))
    else:
        print(f"⚠ Container code not found at {fall_detection_root}, skipping real inference test")
        return

    # Create a test frame
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    # Force model loading by calling infer
    result = inference.infer(frame)

    # Verify response structure
    assert "violation_detected" in result
    assert "detections" in result

    print("✓ Fall detection with weights test passed")
    print(f"  Detection count: {result.get('detection_count', 0)}")
    print(f"  Mode: {result.get('metadata', {}).get('mode', 'unknown')}")

if __name__ == "__main__":
    print("Testing fall_detection plugin directly...")
    print()

    test_fall_detection_real_inference()
    print()

    print("All tests passed!")

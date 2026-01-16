"""
Fall Detection Preprocessing

Converts raw input frames to model-ready tensors.
"""

import cv2
import numpy as np
import torch
from typing import Any


def preprocess(raw_input: Any, **kwargs: Any) -> torch.Tensor:
    """
    Preprocess an image for YOLOv7-Pose model.

    Args:
        raw_input: Input image as numpy array (BGR format, any size)
        **kwargs: Additional arguments (ignored)

    Returns:
        Preprocessed tensor ready for inference
    """
    image = raw_input

    # Ensure numpy array
    if not isinstance(image, np.ndarray):
        raise ValueError(f"Expected numpy array, got {type(image)}")

    # Resize image to model input size (640x640)
    img = cv2.resize(image, (640, 640))

    # BGR to RGB, HWC to CHW
    img = img[:, :, ::-1].transpose(2, 0, 1)
    img = np.ascontiguousarray(img)

    # Convert to tensor and normalize
    img = torch.from_numpy(img).float()
    img /= 255.0  # Normalize to 0-1

    # Add batch dimension
    if img.ndimension() == 3:
        img = img.unsqueeze(0)

    return img

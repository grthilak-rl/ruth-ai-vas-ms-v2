"""
Fall Detection Model Loader

Loads the YOLOv7-Pose model for fall detection.
This file is called by the runtime to load the model instance.
"""

from pathlib import Path
from typing import Any
import sys
import logging

logger = logging.getLogger(__name__)


def load(weights_path: Path) -> Any:
    """
    Load the YOLOv7-Pose model from weights.

    Args:
        weights_path: Path to the weights directory

    Returns:
        Loaded model instance ready for inference
    """
    # Add lib directory to path for model imports
    model_dir = weights_path.parent
    lib_dir = model_dir / "lib"

    if str(lib_dir) not in sys.path:
        sys.path.insert(0, str(lib_dir))

    # Import after adding to path
    from models.experimental import attempt_load

    # Find the weights file
    weights_file = weights_path / "yolov7-w6-pose.pt"

    if not weights_file.exists():
        raise FileNotFoundError(f"Model weights not found: {weights_file}")

    logger.info(f"Loading YOLOv7-Pose model from {weights_file}")

    # Load model (CPU by default, runtime can move to GPU if available)
    model = attempt_load(str(weights_file), map_location='cpu')
    model.eval()

    logger.info(f"Successfully loaded fall detection model")

    return model
